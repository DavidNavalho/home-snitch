"""FastAPI application for local Home Wiki APIs."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from homewiki.ask_service import SearchCallable, answer_question, default_search
from homewiki.config import Settings
from homewiki.config import load_settings
from homewiki.llm import ChatClient, ChatConfigurationError
from homewiki.schemas import (
    AskRequest,
    AskResponse,
    DeviceDocument,
    DeviceInformationResponse,
    DeviceProfile,
    ErrorResponse,
    SearchRequest,
    SearchResponse,
    SourceType,
)
from homewiki.search_service import (
    SearchService,
    SearchServiceError,
    create_search_service,
)


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

    app = FastAPI(title="Home Wiki API", version="0.1.0")
    app.state.search_service = search_service or create_search_service()
    app.state.chat_client = chat_client

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
