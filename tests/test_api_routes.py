from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from homewiki.api import create_app
from homewiki.config import load_settings
from homewiki.schemas import (
    DeviceProfile,
    IngestReport,
    ManualCandidate,
    ManualDownloadResult,
    ManualSearchResult,
    SearchFilters,
    SearchResult,
    SourceType,
)
from homewiki.search_service import SearchService, SearchServiceError


class _DummyBackend:
    def __init__(self, results: list[SearchResult] | None = None) -> None:
        self.results = list(results or [])

    def search(
        self,
        query: str,
        filters: SearchFilters | None,
        limit: int,
    ) -> list[SearchResult]:
        return self.results[:limit]

    def status(self) -> dict[str, object]:
        return {"status": "ok", "backend": "dummy", "row_count": len(self.results)}


def test_post_devices_creates_device_profile(tmp_path: Path) -> None:
    client = _client(tmp_path)
    profile = {
        "asset_id": "router-asus-rt-ax88u",
        "device_type": "router",
        "brand": "ASUS",
        "model": "RT-AX88U",
        "normalized_model": "rtax88u",
        "aliases": ["router", "wifi"],
        "room": "office",
    }

    response = client.post("/devices", json=profile)

    assert response.status_code == 200
    payload = response.json()
    assert payload["device"]["asset_id"] == profile["asset_id"]
    assert payload["device"]["model"] == profile["model"]

    created_profile = tmp_path / "source_docs" / "devices" / profile["asset_id"] / "profile.yaml"
    assert created_profile.exists()


def test_post_manual_find_requires_asset_or_query(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post("/manuals/find", json={})

    assert response.status_code == 422


def test_post_manual_find_with_asset_uses_device_profile(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, include_fixtures=True)
    expected = ManualSearchResult(
        query="ignored",
        candidates=[
            ManualCandidate(
                title="Device manual",
                url="https://example.invalid/manual.pdf",
                source_host="example.invalid",
                is_pdf=True,
                rank=1,
            )
        ],
    )

    def fake_find_manual_candidates(brand: str, model: str, device_type: str | None = None, limit: int = 5, timeout: float = 10.0, search_html: str | None = None) -> ManualSearchResult:  # noqa: E501
        return expected

    monkeypatch.setattr("homewiki.api.find_manual_candidates", fake_find_manual_candidates)
    response = client.post(
        "/manuals/find",
        json={
            "asset_id": "dishwasher-bosch-sms6zcw00g",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "Bosch SMS6ZCW00G dishwasher manual pdf"
    assert payload["candidates"][0]["title"] == "Device manual"


def test_post_manual_download_forwards_to_manual_downloader(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = _client(tmp_path)
    report = ManualDownloadResult(
        asset_id="dishwasher-bosch-sms6zcw00g",
        url="https://example.invalid/manual.pdf",
        saved_path="source_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/manual.pdf",
        sidecar_path="source_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/manual.pdf.meta.yaml",
        downloaded=True,
        error=None,
    )

    def fake_download_manual(*, asset_id: str, url: str, source_root: Path, title: str | None = None, search_query: str | None = None) -> ManualDownloadResult:  # noqa: E501
        return report

    monkeypatch.setattr("homewiki.api.download_manual", fake_download_manual)
    response = client.post(
        "/manuals/download",
        json={
            "asset_id": "dishwasher-bosch-sms6zcw00g",
            "url": "https://example.invalid/manual.pdf",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["downloaded"] is True
    assert payload["saved_path"] == report.saved_path


def test_post_ingest_calls_pipeline_and_returns_report(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path)
    expected = IngestReport(converted=1, indexed=2, skipped=3, failed=4, removed=0)

    monkeypatch.setattr("homewiki.api.ingest_all", lambda **_: expected)
    response = client.post("/ingest", json={})

    assert response.status_code == 200
    payload = response.json()
    assert payload["converted"] == expected.converted
    assert payload["indexed"] == expected.indexed


def _client(tmp_path: Path, include_fixtures: bool = False) -> TestClient:
    from homewiki.resolver import load_device_profiles

    root = Path(__file__).resolve().parents[1]
    source_docs = tmp_path / "source_docs"
    markdown_docs = tmp_path / "markdown_docs"
    settings = load_settings(
        environ={
            "HOME_WIKI_SOURCE_DOCS": str(source_docs),
            "HOME_WIKI_MARKDOWN_DOCS": str(markdown_docs),
            "HOME_WIKI_DEVICE_REGISTRY": str(tmp_path / "data" / "devices.sqlite"),
            "HOME_WIKI_LANCEDB_DIR": str(tmp_path / "lancedb_data"),
            "HOME_WIKI_INGEST_MANIFEST": str(tmp_path / "data" / "ingest_manifest.sqlite"),
            "HOME_WIKI_TABLE": "homewiki_test_chunks",
            "CHAT_PROVIDER": "disabled",
            "EMBEDDING_PROVIDER": "fake",
            "EMBEDDING_API_BASE": "http://localhost:1234/v1",
            "EMBEDDING_API_KEY": "",
            "EMBEDDING_MODEL": "",
        },
        project_root=tmp_path,
    )
    devices = (
        load_device_profiles(root / "fixtures" / "source_docs")
        if include_fixtures
        else []
    )

    service = SearchService(
        settings=settings,
        backend=_DummyBackend(),
        device_provider=lambda: devices,
    )
    return TestClient(create_app(service))
