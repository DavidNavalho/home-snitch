"""FastAPI application for local Home Wiki APIs."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from homewiki.config import load_settings
from homewiki.schemas import SearchRequest, SearchResponse
from homewiki.search_service import (
    SearchService,
    SearchServiceError,
    create_search_service,
)


def create_app(search_service: SearchService | None = None) -> FastAPI:
    """Create the Home Wiki API app with injectable service dependencies."""

    app = FastAPI(title="Home Wiki API", version="0.1.0")
    app.state.search_service = search_service or create_search_service()

    @app.exception_handler(SearchServiceError)
    async def search_service_error_handler(_, exc: SearchServiceError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.error.to_json_dict()},
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

    return app


def _get_search_service(request: Request) -> SearchService:
    return request.app.state.search_service


settings = load_settings()
app = create_app()


__all__ = ["app", "create_app", "settings"]
