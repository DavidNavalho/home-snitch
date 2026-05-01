from __future__ import annotations

import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from homewiki.config import load_settings
from homewiki.ingest import build_index
from homewiki.lancedb_store import open_store
from homewiki.resolver import load_device_profiles
from homewiki.schemas import (
    SearchFilters,
    SearchRequest,
    SearchScope,
    SearchResult,
    SourceType,
)
from homewiki.search_service import LanceSearchBackend, SearchService, SearchServiceError


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DOCS = ROOT / "fixtures" / "source_docs"
BOSCH_ASSET_ID = "dishwasher-bosch-sms6zcw00g"
SIEMENS_ASSET_ID = "dishwasher-siemens-sn23ec14cg"
ROUTER_ASSET_ID = "router-asus-rt-ax88u"


class RecordingBackend:
    def __init__(self, results: list[SearchResult]) -> None:
        self.results = results
        self.calls: list[tuple[str, SearchFilters | None, int]] = []

    def search(
        self,
        query: str,
        filters: SearchFilters | None,
        limit: int,
    ) -> list[SearchResult]:
        self.calls.append((query, filters, limit))
        terms = {term.lower() for term in query.split()}
        matches: list[SearchResult] = []
        for result in self.results:
            if not _matches_filters(result, filters):
                continue
            haystack = " ".join(
                value
                for value in (
                    result.text,
                    result.section_title,
                    result.brand,
                    result.model,
                    result.device_type,
                    result.room,
                )
                if value
            ).lower()
            if not terms or any(term.strip("?.,") in haystack for term in terms):
                matches.append(result)
        return matches[:limit]

    def status(self) -> dict[str, object]:
        return {
            "status": "ok",
            "backend": "recording",
            "row_count": len(self.results),
        }


class FailingBackend:
    def search(
        self,
        query: str,
        filters: SearchFilters | None,
        limit: int,
    ) -> list[SearchResult]:
        raise RuntimeError("index is unavailable")

    def status(self) -> dict[str, object]:
        return {"status": "error"}


class StatusFailingBackend(RecordingBackend):
    def status(self) -> dict[str, object]:
        raise RuntimeError("status unavailable")


class StaticOrderBackend(RecordingBackend):
    def search(
        self,
        query: str,
        filters: SearchFilters | None,
        limit: int,
    ) -> list[SearchResult]:
        self.calls.append((query, filters, limit))
        return [
            result
            for result in self.results
            if _matches_filters(result, filters)
        ][:limit]


def test_exact_model_query_returns_device_scope_and_evidence() -> None:
    backend = RecordingBackend(_sample_results())
    service = _service(backend)

    response = service.search(
        SearchRequest(query="What does E15 mean on SMS6ZCW00G?", limit=5)
    )

    assert response.resolution.status == "exact"
    assert response.resolution.asset_id == BOSCH_ASSET_ID
    assert response.scope == SearchScope.DEVICE
    assert response.results
    assert all(result.asset_id == BOSCH_ASSET_ID for result in response.results)
    assert any("E15" in result.text for result in response.results)
    assert backend.calls[0][1] == SearchFilters(asset_id=BOSCH_ASSET_ID)


def test_explicit_asset_id_scopes_search() -> None:
    backend = RecordingBackend(_sample_results())
    service = _service(backend)

    response = service.search(
        SearchRequest(query="reset", asset_id=ROUTER_ASSET_ID, limit=5)
    )

    assert response.scope == SearchScope.DEVICE
    assert response.resolution.asset_id == ROUTER_ASSET_ID
    assert response.results
    assert all(result.asset_id == ROUTER_ASSET_ID for result in response.results)


def test_ambiguous_query_returns_candidates_without_searching() -> None:
    backend = RecordingBackend(_sample_results())
    service = _service(backend)

    response = service.search(SearchRequest(query="dishwasher error code", limit=5))

    assert response.resolution.status == "ambiguous"
    assert response.scope == SearchScope.NONE
    assert response.results == []
    assert {
        BOSCH_ASSET_ID,
        SIEMENS_ASSET_ID,
    }.issubset({candidate.asset_id for candidate in response.resolution.candidates})
    assert backend.calls == []


def test_no_match_query_with_global_fallback_searches_globally() -> None:
    backend = RecordingBackend(_sample_results())
    service = _service(backend)

    response = service.search(
        SearchRequest(
            query="where is the admin URL documented?",
            limit=5,
            allow_global_fallback=True,
        )
    )

    assert response.resolution.status == "none"
    assert response.scope == SearchScope.GLOBAL
    assert backend.calls[0][1] is None
    assert ROUTER_ASSET_ID in {result.asset_id for result in response.results}


def test_no_match_query_with_fallback_disabled_returns_none_scope() -> None:
    backend = RecordingBackend(_sample_results())
    service = _service(backend)

    response = service.search(
        SearchRequest(
            query="where is the stopcock?",
            limit=5,
            allow_global_fallback=False,
        )
    )

    assert response.resolution.status == "none"
    assert response.scope == SearchScope.NONE
    assert response.results == []
    assert backend.calls == []


def test_explicit_filters_search_when_no_device_resolves() -> None:
    backend = RecordingBackend(_sample_results())
    service = _service(backend)

    response = service.search(
        SearchRequest(
            query="admin URL",
            filters=SearchFilters(source_type=SourceType.NOTE),
            allow_global_fallback=False,
        )
    )

    assert response.resolution.status == "none"
    assert response.scope == SearchScope.FILTERED
    assert response.results
    assert all(result.source_type == SourceType.NOTE for result in response.results)


def test_unknown_explicit_asset_id_is_service_error() -> None:
    service = _service(RecordingBackend(_sample_results()))

    with pytest.raises(SearchServiceError) as raised:
        service.search(
            SearchRequest(
                query="E15",
                asset_id="dishwasher-missing-model",
            )
        )

    assert raised.value.status_code == 404
    assert raised.value.error.code == "unknown_asset_id"


def test_backend_failure_becomes_structured_service_error() -> None:
    service = _service(FailingBackend())

    with pytest.raises(SearchServiceError) as raised:
        service.search(
            SearchRequest(
                query="What does E15 mean on SMS6ZCW00G?",
            )
        )

    assert raised.value.status_code == 503
    assert raised.value.error.code == "search_backend_unavailable"
    assert "index is unavailable" in raised.value.error.message


def test_status_reports_devices_and_backend() -> None:
    service = _service(RecordingBackend(_sample_results()))

    status = service.status()

    assert status["api"] == "ok"
    assert status["devices"] == 3
    assert status["search_backend"]["backend"] == "recording"


def test_status_reports_backend_status_errors_without_raising() -> None:
    service = _service(StatusFailingBackend(_sample_results()))

    status = service.status()

    assert status["api"] == "ok"
    assert status["search_backend"]["status"] == "error"
    assert "status unavailable" in status["search_backend"]["error"]


def test_backend_results_are_reranked_by_exact_code_terms() -> None:
    irrelevant = _sample_results()[0].model_copy(
        update={
            "text": "Drying performance guidance mentions water but no error code.",
            "score": 0.99,
            "section_title": "Troubleshooting > Drying",
        }
    )
    exact = _sample_results()[0].model_copy(
        update={
            "text": "E15 means the water protection system has been activated.",
            "score": 0.1,
            "section_title": "Troubleshooting > Error Codes > E15",
        }
    )
    service = _service(StaticOrderBackend([irrelevant, exact]))

    response = service.search(
        SearchRequest(
            query="What does E15 mean?",
            asset_id=BOSCH_ASSET_ID,
            limit=1,
        )
    )

    assert response.results[0].text.startswith("E15 means")


def test_lance_backend_searches_chunks_built_by_ingest() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_root = root / "source_docs"
        markdown_root = root / "markdown_docs"
        shutil.copytree(ROOT / "fixtures" / "source_docs", source_root)
        shutil.copytree(ROOT / "fixtures" / "markdown_docs", markdown_root)
        settings = load_settings(
            environ={
                "EMBEDDING_PROVIDER": "fake",
                "HOME_WIKI_SOURCE_DOCS": str(source_root),
                "HOME_WIKI_MARKDOWN_DOCS": str(markdown_root),
                "HOME_WIKI_LANCEDB_DIR": str(root / "lancedb_data"),
            },
            project_root=root,
        )
        store = open_store(settings)
        ingest_report = build_index(markdown_root, source_root, store, force=True)
        service = SearchService(
            settings=settings,
            backend=LanceSearchBackend(settings),
            device_provider=lambda: load_device_profiles(source_root),
        )

        response = service.search(
            SearchRequest(
                query="What does E15 mean on SMS6ZCW00G?",
                limit=5,
                allow_global_fallback=True,
            )
        )

        assert ingest_report.failed == 0
        assert ingest_report.indexed > 0
        assert response.scope == SearchScope.DEVICE
        assert response.results
        assert all(result.asset_id == BOSCH_ASSET_ID for result in response.results)
        assert any("E15 means" in result.text for result in response.results)


def _service(backend) -> SearchService:
    devices = load_device_profiles(SOURCE_DOCS)
    return SearchService(
        settings=load_settings(project_root=ROOT),
        backend=backend,
        device_provider=lambda: devices,
    )


def _matches_filters(result: SearchResult, filters: SearchFilters | None) -> bool:
    if filters is None or filters.is_empty():
        return True
    values = filters.model_dump(mode="json")
    for key, expected in values.items():
        if expected is None:
            continue
        if getattr(result, key) != expected:
            return False
    return True


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
            text="E24 means the drain system is blocked.",
            score=0.9,
            asset_id=SIEMENS_ASSET_ID,
            source_type=SourceType.MANUAL,
            brand="Siemens",
            model="SN23EC14CG",
            normalized_model="sn23ec14cg",
            device_type="dishwasher",
            room="utility",
            source_path="fixtures/source_docs/devices/dishwasher-siemens-sn23ec14cg/manuals/quick-manual.md",
            markdown_path="fixtures/markdown_docs/devices/dishwasher-siemens-sn23ec14cg/manuals/quick-manual.md",
            section_title="Troubleshooting > Error Codes > E24",
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
        SearchResult(
            text="Factory reset can erase wireless settings.",
            score=0.7,
            asset_id=ROUTER_ASSET_ID,
            source_type=SourceType.NOTE,
            brand="ASUS",
            model="RT-AX88U",
            normalized_model="rtax88u",
            device_type="router",
            room="office",
            source_path="fixtures/source_docs/devices/router-asus-rt-ax88u/notes/admin-notes.md",
            markdown_path="fixtures/markdown_docs/devices/router-asus-rt-ax88u/notes/admin-notes.md",
            section_title="Reset Caution",
        ),
    ]
