"""FastAPI application for local Home Wiki APIs."""

from __future__ import annotations

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
    ErrorResponse,
    SearchRequest,
    SearchResponse,
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


settings = load_settings()
app = create_app()


__all__ = [
    "app",
    "ask_endpoint",
    "create_app",
    "handle_ask_request",
    "settings",
]
