"""FastAPI application for local Home Wiki APIs."""

from __future__ import annotations

from pathlib import Path
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
    AskRequest,
    AskResponse,
    DeviceCreateResponse,
    DeviceDocument,
    DeviceInformationResponse,
    DeviceProfile,
    ErrorResponse,
    IngestReport,
    ManualDownloadResult,
    ManualDownloadRequest,
    ManualFindRequest,
    ManualSearchResult,
    SearchRequest,
    SearchResponse,
    SourceType,
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

    @app.get(
        "/devices/{asset_id}/information",
        response_model=DeviceInformationResponse,
    )
    def device_information(
        asset_id: str,
        service: Annotated[SearchService, Depends(_get_search_service)],
    ) -> DeviceInformationResponse:
        device = _find_device(asset_id, service.list_devices())
        if device is None:
            raise SearchServiceError(
                "unknown_asset_id",
                f"Device asset_id {asset_id!r} is not registered.",
                status_code=404,
                details={"asset_id": asset_id},
            )
        return DeviceInformationResponse(
            device=device,
            documents=_list_device_documents(service.settings, device.asset_id),
        )

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


def _find_device(asset_id: str, devices: list[DeviceProfile]) -> DeviceProfile | None:
    for device in devices:
        if device.asset_id == asset_id:
            return device
    return None


def _resolve_device_for_asset(
    service: SearchService,
    asset_id: str | None,
) -> DeviceProfile | None:
    if not asset_id:
        return None
    return _find_device(asset_id, service.list_devices())


def _parse_manual_query(query: str) -> tuple[str, str, str | None]:
    parts = [part.strip() for part in query.split() if part.strip()]
    if len(parts) >= 2:
        return parts[0], parts[1], None
    if len(parts) == 1:
        return parts[0], "", None
    return "", "", None


def _list_device_documents(settings: Settings, asset_id: str) -> list[DeviceDocument]:
    source_root = _docs_root_with_fixture_fallback(
        settings.paths.source_docs,
        settings.paths.project_root,
        "source_docs",
        asset_id,
    )
    markdown_root = _docs_root_with_fixture_fallback(
        settings.paths.markdown_docs,
        settings.paths.project_root,
        "markdown_docs",
        asset_id,
    )
    source_device_dir = source_root / "devices" / asset_id
    markdown_device_dir = markdown_root / "devices" / asset_id
    documents: list[DeviceDocument] = []
    seen_markdown_paths: set[Path] = set()

    if source_device_dir.exists():
        for source_path in sorted(
            path for path in source_device_dir.rglob("*") if path.is_file()
        ):
            if _should_skip_source_document(source_path, source_device_dir):
                continue
            markdown_path = _matching_markdown_path(
                source_path,
                source_device_dir,
                markdown_device_dir,
            )
            if markdown_path is not None:
                seen_markdown_paths.add(markdown_path)
            documents.append(
                DeviceDocument(
                    source_type=_source_type_for_device_path(
                        source_path.relative_to(source_device_dir)
                    ),
                    name=source_path.name,
                    source_path=_display_path(source_path, settings.paths.project_root),
                    markdown_path=(
                        _display_path(markdown_path, settings.paths.project_root)
                        if markdown_path is not None
                        else None
                    ),
                    available_as_markdown=markdown_path is not None,
                    size_bytes=source_path.stat().st_size,
                )
            )

    if markdown_device_dir.exists():
        for markdown_path in sorted(
            path for path in markdown_device_dir.rglob("*") if path.is_file()
        ):
            if markdown_path in seen_markdown_paths:
                continue
            documents.append(
                DeviceDocument(
                    source_type=_source_type_for_device_path(
                        markdown_path.relative_to(markdown_device_dir)
                    ),
                    name=markdown_path.name,
                    source_path=None,
                    markdown_path=_display_path(
                        markdown_path,
                        settings.paths.project_root,
                    ),
                    available_as_markdown=True,
                    size_bytes=markdown_path.stat().st_size,
                )
            )

    return sorted(
        documents,
        key=lambda document: (
            _source_type_sort_key(document.source_type),
            document.name,
            document.source_path or document.markdown_path or "",
        ),
    )


def _docs_root_with_fixture_fallback(
    configured_root: Path,
    project_root: Path,
    fixture_name: str,
    asset_id: str,
) -> Path:
    if (configured_root / "devices" / asset_id).exists():
        return configured_root
    fixture_root = project_root / "fixtures" / fixture_name
    if (fixture_root / "devices" / asset_id).exists():
        return fixture_root
    return configured_root


def _should_skip_source_document(path: Path, device_dir: Path) -> bool:
    if path.name == "profile.md" and (device_dir / "profile.yaml").exists():
        return True
    return path.suffix.lower() in {".yaml", ".yml"} and path.name != "profile.yaml"


def _matching_markdown_path(
    source_path: Path,
    source_device_dir: Path,
    markdown_device_dir: Path,
) -> Path | None:
    relative_path = source_path.relative_to(source_device_dir)
    if source_path.name in {"profile.yaml", "profile.md"}:
        candidates = [markdown_device_dir / "profile.md"]
    else:
        candidates = [markdown_device_dir / relative_path]
        if source_path.suffix.lower() != ".md":
            candidates.append(markdown_device_dir / Path(f"{relative_path}.md"))

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _source_type_for_device_path(relative_path: Path) -> SourceType:
    parts = set(relative_path.parts)
    if relative_path.name.startswith("profile."):
        return SourceType.PROFILE
    if "manuals" in parts:
        return SourceType.MANUAL
    if "notes" in parts:
        return SourceType.NOTE
    if "receipts" in parts:
        return SourceType.RECEIPT
    if "photos" in parts:
        return SourceType.PHOTO_OCR
    return SourceType.OTHER


def _source_type_sort_key(source_type: SourceType) -> int:
    order = {
        SourceType.PROFILE: 0,
        SourceType.MANUAL: 1,
        SourceType.NOTE: 2,
        SourceType.RECEIPT: 3,
        SourceType.PHOTO_OCR: 4,
        SourceType.OTHER: 5,
    }
    return order[source_type]


def _display_path(path: Path, project_root: Path) -> str:
    try:
        return str(path.relative_to(project_root))
    except ValueError:
        return str(path)


settings = load_settings()
app = create_app()


__all__ = [
    "app",
    "ask_endpoint",
    "create_app",
    "handle_ask_request",
    "settings",
]
