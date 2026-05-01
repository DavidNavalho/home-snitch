from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from homewiki.api import ask_endpoint, create_app, handle_ask_request
from homewiki.config import load_settings
from homewiki.resolver import load_device_profiles
from homewiki.schemas import (
    DeviceResolution,
    ResolutionStatus,
    SearchFilters,
    SearchRequest,
    SearchResponse,
    SearchResult,
    SearchScope,
    SourceType,
)
from homewiki.search_service import SearchService, SearchServiceError


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DOCS = ROOT / "fixtures" / "source_docs"
BOSCH_ASSET_ID = "dishwasher-bosch-sms6zcw00g"


def test_handle_ask_request_returns_evidence_only_payload() -> None:
    seen_requests: list[SearchRequest] = []

    def search(request: SearchRequest) -> SearchResponse:
        seen_requests.append(request)
        return _search_response(request.query)

    status, payload = handle_ask_request(
        {
            "question": "What does E15 mean?",
            "asset_id": BOSCH_ASSET_ID,
            "limit": 4,
            "allow_global_fallback": False,
        },
        search=search,
        settings=load_settings(environ={"CHAT_PROVIDER": "disabled"}),
    )

    assert status == 200
    assert payload["generated"] is False
    assert payload["confidence"] == 7
    assert payload["resolution"]["status"] == "exact"
    assert payload["sources"] == [
        "fixtures/markdown_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/quick-manual.md"
    ]
    assert seen_requests[0].query == "What does E15 mean?"
    assert seen_requests[0].asset_id == BOSCH_ASSET_ID
    assert seen_requests[0].limit == 4


def test_ask_endpoint_returns_schema_serializable_dict() -> None:
    payload = ask_endpoint(
        {"question": "What does E15 mean?", "asset_id": BOSCH_ASSET_ID},
        search=lambda request: _search_response(request.query),
        settings=load_settings(environ={"CHAT_PROVIDER": "disabled"}),
    )

    assert payload["generated"] is False
    assert payload["evidence"][0]["source_type"] == "manual"
    assert payload["evidence"][0]["modified_at"] == 0.0
    assert payload["resolution"]["filters"]["asset_id"] == BOSCH_ASSET_ID


def test_handle_ask_request_returns_validation_error_payload() -> None:
    status, payload = handle_ask_request(
        {"question": "", "limit": 0},
        search=lambda request: _search_response(request.query),
    )

    assert status == 422
    assert payload["error"]["code"] == "validation_error"
    assert payload["error"]["details"]["errors"]


def test_handle_ask_request_preserves_search_service_error() -> None:
    def search(_: SearchRequest) -> SearchResponse:
        raise SearchServiceError(
            "unknown_asset_id",
            "Device asset_id is not registered.",
            status_code=404,
            details={"asset_id": "dishwasher-missing-model"},
        )

    status, payload = handle_ask_request(
        {
            "question": "What does E15 mean?",
            "asset_id": "dishwasher-missing-model",
        },
        search=search,
    )

    assert status == 404
    assert payload["error"]["code"] == "unknown_asset_id"
    assert payload["error"]["details"] == {
        "asset_id": "dishwasher-missing-model"
    }


def test_post_ask_uses_search_service_and_returns_evidence_only() -> None:
    client = _client()

    response = client.post(
        "/ask",
        json={
            "question": "What does E15 mean?",
            "asset_id": BOSCH_ASSET_ID,
            "allow_global_fallback": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["generated"] is False
    assert payload["resolution"]["status"] == "exact"
    assert payload["sources"] == [
        "fixtures/markdown_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/quick-manual.md"
    ]
    assert payload["evidence"][0]["asset_id"] == BOSCH_ASSET_ID
    assert "water protection system" in payload["answer"]


def test_post_ask_ambiguous_search_does_not_generate() -> None:
    client = _client()

    response = client.post(
        "/ask",
        json={
            "question": "dishwasher error code",
            "allow_global_fallback": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["generated"] is False
    assert payload["resolution"]["status"] == "ambiguous"
    assert payload["evidence"] == []
    assert payload["missing_information"] == ["device selection"]


def test_post_ask_unknown_asset_returns_search_service_error() -> None:
    client = _client()

    response = client.post(
        "/ask",
        json={
            "question": "What does E15 mean?",
            "asset_id": "dishwasher-missing-model",
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_asset_id"


class RecordingBackend:
    def __init__(self, results: list[SearchResult]) -> None:
        self.results = results

    def search(
        self,
        query: str,
        filters: SearchFilters | None,
        limit: int,
    ) -> list[SearchResult]:
        matches = []
        for result in self.results:
            if filters is not None and not filters.is_empty():
                values = filters.model_dump(mode="json")
                if any(
                    getattr(result, key) != expected
                    for key, expected in values.items()
                    if expected is not None
                ):
                    continue
            matches.append(result)
        return matches[:limit]

    def status(self) -> dict[str, object]:
        return {
            "status": "ok",
            "backend": "recording",
            "row_count": len(self.results),
        }


def _client() -> TestClient:
    devices = load_device_profiles(SOURCE_DOCS)
    service = SearchService(
        settings=load_settings(
            environ={"CHAT_PROVIDER": "disabled"},
            project_root=ROOT,
        ),
        backend=RecordingBackend(_sample_results()),
        device_provider=lambda: devices,
    )
    return TestClient(create_app(service))


def _sample_results() -> list[SearchResult]:
    return [_search_response("E15").results[0]]


def _search_response(query: str) -> SearchResponse:
    return SearchResponse(
        query=query,
        resolution=DeviceResolution(
            status=ResolutionStatus.EXACT,
            asset_id=BOSCH_ASSET_ID,
            confidence=1.0,
            matched_on=["asset_id"],
            candidates=[],
            filters=SearchFilters(asset_id=BOSCH_ASSET_ID),
        ),
        scope=SearchScope.DEVICE,
        results=[
            SearchResult(
                text=(
                    "E15 means the water protection system has been activated "
                    "or water has been detected in the base area."
                ),
                score=1.0,
                asset_id=BOSCH_ASSET_ID,
                source_type=SourceType.MANUAL,
                brand="Bosch",
                model="SMS6ZCW00G",
                normalized_model="sms6zcw00g",
                device_type="dishwasher",
                room="kitchen",
                source_path=(
                    "fixtures/source_docs/devices/dishwasher-bosch-sms6zcw00g/"
                    "manuals/quick-manual.md"
                ),
                markdown_path=(
                    "fixtures/markdown_docs/devices/dishwasher-bosch-sms6zcw00g/"
                    "manuals/quick-manual.md"
                ),
                section_title="Troubleshooting > Error Codes > E15",
                chunk_index=0,
                content_hash="bosch-e15",
                modified_at=0.0,
                tags=["appliance"],
            )
        ],
    )
