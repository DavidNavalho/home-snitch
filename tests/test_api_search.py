from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from homewiki.config import load_settings
from homewiki.api import create_app
from homewiki.resolver import load_device_profiles
from homewiki.schemas import SearchFilters, SearchResult, SourceType
from homewiki.search_service import SearchService

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DOCS = ROOT / "fixtures" / "source_docs"
BOSCH_ASSET_ID = "dishwasher-bosch-sms6zcw00g"
ROUTER_ASSET_ID = "router-asus-rt-ax88u"


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
            if query.lower().strip("?") in result.text.lower() or any(
                term.strip("?").lower() in result.text.lower()
                for term in query.split()
            ):
                matches.append(result)
        return matches[:limit]

    def status(self) -> dict[str, object]:
        return {
            "status": "ok",
            "backend": "recording",
            "row_count": len(self.results),
        }


def test_get_status_endpoint() -> None:
    client = _client()

    response = client.get("/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["api"] == "ok"
    assert payload["devices"] == 3
    assert payload["search_backend"]["backend"] == "recording"


def test_get_devices_endpoint() -> None:
    client = _client()

    response = client.get("/devices")

    assert response.status_code == 200
    payload = response.json()
    assert {device["asset_id"] for device in payload["devices"]} >= {
        BOSCH_ASSET_ID,
        ROUTER_ASSET_ID,
    }


def test_get_device_information_endpoint_lists_profile_and_documents() -> None:
    client = _client()

    response = client.get(f"/devices/{BOSCH_ASSET_ID}/information")

    assert response.status_code == 200
    payload = response.json()
    assert payload["device"]["asset_id"] == BOSCH_ASSET_ID
    assert payload["device"]["support_url"] == "https://www.bosch-home.com/support"
    assert {
        (document["source_type"], document["name"])
        for document in payload["documents"]
    } >= {
        ("profile", "profile.yaml"),
        ("manual", "quick-manual.md"),
    }
    manual = next(
        document
        for document in payload["documents"]
        if document["source_type"] == "manual"
    )
    assert manual["available_as_markdown"] is True
    assert manual["source_path"].endswith("manuals/quick-manual.md")
    assert manual["markdown_path"].endswith("manuals/quick-manual.md")


def test_post_search_exact_scoped_result() -> None:
    client = _client()

    response = client.post(
        "/search",
        json={
            "query": "What does E15 mean on SMS6ZCW00G?",
            "limit": 5,
            "allow_global_fallback": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["resolution"]["status"] == "exact"
    assert payload["resolution"]["asset_id"] == BOSCH_ASSET_ID
    assert payload["scope"] == "device"
    assert payload["results"]
    assert all(result["asset_id"] == BOSCH_ASSET_ID for result in payload["results"])
    assert "E15" in payload["results"][0]["text"]


def test_post_search_ambiguous_is_http_200() -> None:
    client = _client()

    response = client.post(
        "/search",
        json={
            "query": "dishwasher error code",
            "limit": 5,
            "allow_global_fallback": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["resolution"]["status"] == "ambiguous"
    assert payload["scope"] == "none"
    assert payload["results"] == []
    assert len(payload["resolution"]["candidates"]) >= 2


def test_post_search_validation_error_for_missing_query() -> None:
    client = _client()

    response = client.post("/search", json={"limit": 5})

    assert response.status_code == 422


def test_post_search_unknown_asset_returns_structured_error() -> None:
    client = _client()

    response = client.post(
        "/search",
        json={
            "query": "E15",
            "asset_id": "dishwasher-missing-model",
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_asset_id"


def _client() -> TestClient:
    devices = load_device_profiles(SOURCE_DOCS)
    service = SearchService(
        settings=load_settings(project_root=ROOT),
        backend=RecordingBackend(_sample_results()),
        device_provider=lambda: devices,
    )
    return TestClient(create_app(service))


def _sample_results() -> list[SearchResult]:
    return [
        SearchResult(
            text="E15 means the water protection system has been activated.",
            score=1.0,
            asset_id=BOSCH_ASSET_ID,
            source_type=SourceType.MANUAL,
            brand="Bosch",
            model="SMS6ZCW00G",
            normalized_model="sms6zcw00g",
            device_type="dishwasher",
            room="kitchen",
            source_path="fixtures/source_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/quick-manual.md",
            markdown_path="fixtures/markdown_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/quick-manual.md",
            section_title="Troubleshooting > Error Codes > E15",
        ),
        SearchResult(
            text="Admin URL: http://router.asus.com",
            score=0.8,
            asset_id=ROUTER_ASSET_ID,
            source_type=SourceType.NOTE,
            brand="ASUS",
            model="RT-AX88U",
            normalized_model="rtax88u",
            device_type="router",
            room="office",
            source_path="fixtures/source_docs/devices/router-asus-rt-ax88u/notes/admin-notes.md",
            markdown_path="fixtures/markdown_docs/devices/router-asus-rt-ax88u/notes/admin-notes.md",
            section_title="Access",
        ),
    ]
