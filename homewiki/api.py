"""FastAPI application for local Home Wiki APIs."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from homewiki.devices import upsert_device
from homewiki.ask_service import SearchCallable, answer_question, default_search
from homewiki.config import Settings
from homewiki.config import load_settings
from homewiki.llm import ChatClient, ChatConfigurationError, create_chat_client
from homewiki.manuals import build_manual_search_query, download_manual, find_manual_candidates
from homewiki.ingest import ingest_all
from homewiki.schemas import (
    DeviceCreateResponse,
    DeviceProfile,
    AskRequest,
    AskResponse,
    ErrorResponse,
    ManualDownloadResult,
    ManualDownloadRequest,
    ManualFindRequest,
    ManualSearchResult,
    SearchRequest,
    SearchResponse,
    IngestReport,
)
from homewiki.search_service import (
    SearchService,
    SearchServiceError,
    create_search_service,
)
from homewiki.devices import DeviceStoreError
from homewiki.lancedb_store import open_store


def ask_endpoint(
    payload: dict[str, Any],
    *,
    search: SearchCallable | None = None,
    chat_client: ChatClient | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Handle POST /ask payloads and return an API-safe AskResponse dict."""

    request = AskRequest.model_validate(payload)
    response = answer_question(
        request,
        search=search or default_search,
        chat_client=chat_client,
        settings=settings,
    )
    return response.to_json_dict()


def handle_ask_request(
    payload: dict[str, Any],
    *,
    search: SearchCallable | None = None,
    chat_client: ChatClient | None = None,
    settings: Settings | None = None,
) -> tuple[int, dict[str, Any]]:
    """Return an HTTP-like status and JSON payload for POST /ask."""

    try:
        return (
            200,
            ask_endpoint(
                payload,
                search=search,
                chat_client=chat_client,
                settings=settings,
            ),
        )
    except ValidationError as exc:
        return (
            422,
            {
                "error": ErrorResponse(
                    code="validation_error",
                    message="Invalid ask request.",
                    details={"errors": exc.errors()},
                ).to_json_dict()
            },
        )
    except SearchServiceError as exc:
        return (
            exc.status_code,
            {"error": exc.error.to_json_dict()},
        )
    except ChatConfigurationError as exc:
        return (
            500,
            {
                "error": ErrorResponse(
                    code="chat_configuration_error",
                    message=str(exc),
                ).to_json_dict()
            },
        )
    except Exception as exc:
        return (
            503,
            {
                "error": ErrorResponse(
                    code="ask_service_unavailable",
                    message=str(exc),
                ).to_json_dict()
            },
        )


def create_app(
    search_service: SearchService | None = None,
    *,
    chat_client: ChatClient | None = None,
) -> FastAPI:
    """Create the Home Wiki API app with injectable service dependencies."""

    service = search_service or create_search_service()
    app = FastAPI(title="Home Wiki API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.search_service = service
    app.state.chat_client = chat_client or create_chat_client(service.settings)

    @app.exception_handler(SearchServiceError)
    async def search_service_error_handler(_, exc: SearchServiceError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.error.to_json_dict()},
        )

    @app.exception_handler(ChatConfigurationError)
    async def chat_configuration_error_handler(
        _,
        exc: ChatConfigurationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={
                "error": ErrorResponse(
                    code="chat_configuration_error",
                    message=str(exc),
                ).to_json_dict()
            },
        )

    @app.get("/status")
    def status(service: Annotated[SearchService, Depends(_get_search_service)]):
        return service.status()

    @app.get("/devices")
    def devices(service: Annotated[SearchService, Depends(_get_search_service)]):
        return {
            "devices": [device.to_json_dict() for device in service.list_devices()],
        }

    @app.post("/devices", response_model=DeviceCreateResponse)
    def create_device(
        profile: DeviceProfile,
        service: Annotated[SearchService, Depends(_get_search_service)],
    ):
        try:
            saved = upsert_device(profile, settings=service.settings)
        except DeviceStoreError as exc:
            raise SearchServiceError(
                "device_store_error",
                f"could not persist device {profile.asset_id!r}: {exc}",
                status_code=500,
            ) from exc

        return {"device": saved.to_json_dict()}

    @app.post("/manuals/find", response_model=ManualSearchResult)
    def manuals_find(
        request: ManualFindRequest,
        service: Annotated[SearchService, Depends(_get_search_service)],
    ) -> ManualSearchResult:
        profile = _resolve_device_for_asset(service, request.asset_id)
        if profile is None and not request.query:
            raise SearchServiceError(
                "unknown_asset_id",
                f"device asset_id {request.asset_id!r} is not registered.",
                status_code=404,
                details={"asset_id": request.asset_id},
            )

        if profile is not None:
            brand = profile.brand
            model = profile.model
            device_type = profile.device_type
            query = request.query or build_manual_search_query(
                brand=brand,
                model=model,
                device_type=device_type,
            )
        else:
            assert request.query is not None
            query = request.query
            brand, model, device_type = _parse_manual_query(request.query)

        result = find_manual_candidates(
            brand=brand,
            model=model,
            device_type=device_type or None,
            limit=request.limit,
        )
        return result.model_copy(update={"query": query})

    @app.post("/manuals/download", response_model=ManualDownloadResult)
    def download_manual_route(
        request: ManualDownloadRequest,
        service: Annotated[SearchService, Depends(_get_search_service)],
    ):
        return download_manual(
            asset_id=request.asset_id,
            url=request.url,
            source_root=service.settings.paths.source_docs,
        )

    @app.post("/ingest", response_model=IngestReport)
    def ingest(
        service: Annotated[SearchService, Depends(_get_search_service)],
    ) -> IngestReport:
        store = open_store(service.settings)
        try:
            return ingest_all(
                source_root=service.settings.paths.source_docs,
                markdown_root=service.settings.paths.markdown_docs,
                store=store,
            )
        except Exception as exc:
            raise SearchServiceError(
                "ingest_failed",
                f"ingest failed: {exc}",
                status_code=503,
            ) from exc

    @app.post("/search", response_model=SearchResponse)
    def search(
        request: SearchRequest,
        service: Annotated[SearchService, Depends(_get_search_service)],
    ) -> SearchResponse:
        return service.search(request)

    @app.post("/ask", response_model=AskResponse)
    def ask(
        request: AskRequest,
        service: Annotated[SearchService, Depends(_get_search_service)],
        chat: Annotated[ChatClient | None, Depends(_get_chat_client)],
    ) -> AskResponse:
        return answer_question(
            request,
            search=service.search,
            chat_client=chat,
            settings=service.settings,
        )

    return app


def _get_search_service(request: Request) -> SearchService:
    return request.app.state.search_service


def _get_chat_client(request: Request) -> ChatClient | None:
    return request.app.state.chat_client


def _resolve_device_for_asset(
    service: SearchService,
    asset_id: str | None,
) -> DeviceProfile | None:
    if not asset_id:
        return None

    for device in service.list_devices():
        if device.asset_id == asset_id:
            return device
    return None


def _parse_manual_query(query: str) -> tuple[str, str, str | None]:
    parts = [part.strip() for part in query.split() if part.strip()]
    if len(parts) >= 2:
        return parts[0], parts[1], None
    if len(parts) == 1:
        return parts[0], "", None
    return "", "", None


settings = load_settings()
app = create_app()


__all__ = [
    "app",
    "ask_endpoint",
    "create_app",
    "handle_ask_request",
    "settings",
]
