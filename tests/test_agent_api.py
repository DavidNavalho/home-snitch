from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from homewiki.api import create_app
from homewiki.agent import parse_tool_call
from homewiki.config import load_settings
from homewiki.resolver import load_device_profiles
from homewiki.schemas import (
    AgentAction,
    ManualCandidate,
    ManualSearchResult,
    SearchFilters,
    SearchResult,
    SourceType,
)
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
            matches.append(result)
        return matches[:limit]

    def status(self) -> dict[str, object]:
        return {
            "status": "ok",
            "backend": "recording",
            "row_count": len(self.results),
        }


def test_parse_tool_call_builds_strict_ask_inputs() -> None:
    tool_call = parse_tool_call(
        "ask asset_id=dishwasher-bosch-sms6zcw00g limit=4 What does E15 mean?"
    )

    assert tool_call.action == AgentAction.ASK
    assert tool_call.inputs == {
        "question": "What does E15 mean?",
        "asset_id": BOSCH_ASSET_ID,
        "limit": 4,
        "allow_global_fallback": False,
    }


def test_post_agent_execute_ask_runs_existing_ask_service() -> None:
    client = _client()

    response = client.post(
        "/agent/execute",
        json={
            "input": (
                "ask asset_id=dishwasher-bosch-sms6zcw00g "
                "limit=4 What does E15 mean?"
            )
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["plan"][0]["tool_call"]["action"] == "ask"
    assert payload["plan"][0]["tool_call"]["inputs"]["question"] == "What does E15 mean?"
    assert payload["steps"][0]["status"] == "success"
    assert payload["result"]["generated"] is False
    assert payload["result"]["resolution"]["asset_id"] == BOSCH_ASSET_ID


def test_post_agent_execute_lists_devices() -> None:
    client = _client()

    response = client.post("/agent/execute", json={"input": "list devices"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["plan"][0]["tool_call"]["action"] == "list_devices"
    assert {device["asset_id"] for device in payload["result"]["devices"]} >= {
        BOSCH_ASSET_ID,
        ROUTER_ASSET_ID,
    }


def test_post_agent_execute_manual_find_uses_device_profile(monkeypatch) -> None:
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

    def fake_find_manual_candidates(
        brand: str,
        model: str,
        device_type: str | None = None,
        limit: int = 5,
        timeout: float = 10.0,
        search_html: str | None = None,
    ) -> ManualSearchResult:
        return expected

    monkeypatch.setattr("homewiki.agent.find_manual_candidates", fake_find_manual_candidates)
    client = _client()

    response = client.post(
        "/agent/execute",
        json={"input": "find manuals asset_id=dishwasher-bosch-sms6zcw00g limit=3"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["plan"][0]["tool_call"]["action"] == "manual_find"
    assert payload["steps"][0]["status"] == "success"
    assert payload["result"]["query"] == "Bosch SMS6ZCW00G dishwasher manual pdf"
    assert payload["result"]["candidates"][0]["title"] == "Device manual"


def test_post_agent_execute_add_device_writes_profile(tmp_path: Path) -> None:
    client = _client(tmp_path=tmp_path, include_fixture_devices=False)

    response = client.post(
        "/agent/execute",
        json={"input": "add device brand=ASUS model=RT-AX88U type=router room=office"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["plan"][0]["tool_call"]["action"] == "add_device"
    assert payload["result"]["device"]["asset_id"] == "router-asus-rtax88u"
    assert (
        tmp_path
        / "source_docs"
        / "devices"
        / "router-asus-rtax88u"
        / "profile.yaml"
    ).exists()


def test_post_agent_execute_invalid_download_returns_parse_error() -> None:
    client = _client()

    response = client.post("/agent/execute", json={"input": "download manual"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "agent_parse_error"


def _client(
    *,
    tmp_path: Path | None = None,
    include_fixture_devices: bool = True,
) -> TestClient:
    project_root = tmp_path or ROOT
    settings = load_settings(
        environ={
            "HOME_WIKI_SOURCE_DOCS": str(project_root / "source_docs"),
            "HOME_WIKI_MARKDOWN_DOCS": str(project_root / "markdown_docs"),
            "HOME_WIKI_DEVICE_REGISTRY": str(project_root / "data" / "devices.sqlite"),
            "HOME_WIKI_LANCEDB_DIR": str(project_root / "lancedb_data"),
            "HOME_WIKI_INGEST_MANIFEST": str(project_root / "data" / "ingest_manifest.sqlite"),
            "HOME_WIKI_TABLE": "homewiki_agent_test_chunks",
            "CHAT_PROVIDER": "disabled",
            "EMBEDDING_PROVIDER": "fake",
            "EMBEDDING_API_BASE": "http://localhost:1234/v1",
            "EMBEDDING_API_KEY": "",
            "EMBEDDING_MODEL": "",
        },
        project_root=project_root,
    )
    devices = load_device_profiles(SOURCE_DOCS) if include_fixture_devices else []
    service = SearchService(
        settings=settings,
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
