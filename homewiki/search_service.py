"""Device-resolved search service for the Home Wiki API."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from homewiki.config import Settings, find_project_root, load_settings
from homewiki.devices import DeviceRegistryError, list_devices as list_registry_devices
from homewiki.resolver import load_device_profiles, resolve_device
from homewiki.schemas import (
    DeviceProfile,
    DeviceResolution,
    ErrorResponse,
    ResolutionStatus,
    SearchFilters,
    SearchRequest,
    SearchResponse,
    SearchResult,
    SearchScope,
    SourceType,
)


class SearchServiceError(RuntimeError):
    """Structured service error suitable for API responses."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error = ErrorResponse(code=code, message=message, details=details)


class SearchBackend(Protocol):
    """Minimal backend contract used by SearchService."""

    def search(
        self,
        query: str,
        filters: SearchFilters | None,
        limit: int,
    ) -> list[SearchResult]:
        """Return API-safe search results."""

    def status(self) -> dict[str, Any]:
        """Return backend health details."""


DeviceProvider = Callable[[], list[DeviceProfile]]


@dataclass
class SearchService:
    """Resolve devices, apply search scope rules, and query a backend."""

    settings: Settings = field(default_factory=load_settings)
    backend: SearchBackend | None = None
    device_provider: DeviceProvider | None = None

    def __post_init__(self) -> None:
        if self.backend is None:
            self.backend = LanceSearchBackend(self.settings)

    def list_devices(self) -> list[DeviceProfile]:
        if self.device_provider is not None:
            return self.device_provider()

        try:
            devices = list_registry_devices(settings=self.settings)
        except DeviceRegistryError:
            devices = []
        if devices:
            return devices
        return load_device_profiles(_source_docs_with_fixture_fallback(self.settings))

    def status(self) -> dict[str, Any]:
        devices = self.list_devices()
        try:
            backend_status = self.backend.status() if self.backend is not None else {}
        except Exception as exc:  # noqa: BLE001 - status should report, not raise.
            backend_status = {
                "status": "error",
                "error": str(exc),
            }
        return {
            "api": "ok",
            "devices": len(devices),
            "search_backend": backend_status,
        }

    def search(self, request: SearchRequest) -> SearchResponse:
        devices = self.list_devices()
        known_asset_ids = {device.asset_id for device in devices}
        if request.asset_id is not None and request.asset_id not in known_asset_ids:
            raise SearchServiceError(
                "unknown_asset_id",
                f"Device asset_id {request.asset_id!r} is not registered.",
                status_code=404,
                details={"asset_id": request.asset_id},
            )

        resolution = resolve_device(
            request.query,
            asset_id=request.asset_id,
            devices=devices,
        )
        explicit_filters = request.filters

        if resolution.status == ResolutionStatus.EXACT:
            filters = _merge_filters(
                explicit_filters,
                asset_id=resolution.asset_id,
            )
            results = self._backend_search(request.query, filters, request.limit)
            return SearchResponse(
                query=request.query,
                resolution=resolution,
                scope=SearchScope.DEVICE,
                results=results,
            )

        resolved_filter_asset = _known_filter_asset_id(explicit_filters, known_asset_ids)
        if resolved_filter_asset is not None:
            filters = _merge_filters(explicit_filters, asset_id=resolved_filter_asset)
            result_resolution = DeviceResolution(
                status=ResolutionStatus.EXACT,
                asset_id=resolved_filter_asset,
                confidence=1.0,
                matched_on=["filters.asset_id"],
                candidates=[],
                filters=filters,
            )
            results = self._backend_search(request.query, filters, request.limit)
            return SearchResponse(
                query=request.query,
                resolution=result_resolution,
                scope=SearchScope.DEVICE,
                results=results,
            )

        if (
            explicit_filters is not None
            and not explicit_filters.is_empty()
            and resolution.status == ResolutionStatus.NONE
        ):
            results = self._backend_search(
                request.query,
                explicit_filters,
                request.limit,
            )
            return SearchResponse(
                query=request.query,
                resolution=resolution,
                scope=SearchScope.FILTERED,
                results=results,
            )

        if resolution.status == ResolutionStatus.AMBIGUOUS:
            return SearchResponse(
                query=request.query,
                resolution=resolution,
                scope=SearchScope.NONE,
                results=[],
            )

        if request.allow_global_fallback:
            results = self._backend_search(request.query, None, request.limit)
            return SearchResponse(
                query=request.query,
                resolution=resolution,
                scope=SearchScope.GLOBAL,
                results=results,
            )

        return SearchResponse(
            query=request.query,
            resolution=resolution,
            scope=SearchScope.NONE,
            results=[],
        )

    def _backend_search(
        self,
        query: str,
        filters: SearchFilters | None,
        limit: int,
    ) -> list[SearchResult]:
        assert self.backend is not None
        backend_limit = min(max(limit * 4, limit + 10), 50)
        try:
            results = self.backend.search(query, filters, backend_limit)
        except SearchServiceError:
            raise
        except Exception as exc:
            raise SearchServiceError(
                "search_backend_unavailable",
                f"Search backend failed: {exc}",
                status_code=503,
            ) from exc
        return _rerank_results(query, results, limit)


@dataclass
class LanceSearchBackend:
    """Thin adapter over the LanceDB foundation."""

    settings: Settings = field(default_factory=load_settings)

    def search(
        self,
        query: str,
        filters: SearchFilters | None,
        limit: int,
    ) -> list[SearchResult]:
        from homewiki.lancedb_store import LanceStore, LanceStoreError

        try:
            return LanceStore(self.settings).hybrid_search(
                query,
                filters=filters,
                limit=limit,
            )
        except LanceStoreError as exc:
            raise SearchServiceError(
                "lancedb_unavailable",
                str(exc),
                status_code=503,
            ) from exc

    def status(self) -> dict[str, Any]:
        from homewiki.lancedb_store import get_status

        return get_status(self.settings)


@dataclass
class FixtureSearchBackend:
    """Deterministic file-backed backend used before the index pipeline is ready."""

    results: list[SearchResult]

    @classmethod
    def from_settings(cls, settings: Settings) -> "FixtureSearchBackend":
        markdown_root = settings.paths.markdown_docs
        if not (markdown_root / "devices").exists():
            markdown_root = find_project_root() / "fixtures" / "markdown_docs"
        devices = load_device_profiles(_source_docs_with_fixture_fallback(settings))
        return cls.from_markdown_docs(markdown_root, devices)

    @classmethod
    def from_markdown_docs(
        cls,
        markdown_root: Path,
        devices: list[DeviceProfile],
    ) -> "FixtureSearchBackend":
        device_by_id = {device.asset_id: device for device in devices}
        results: list[SearchResult] = []
        for path in sorted((markdown_root / "devices").glob("**/*.md")):
            results.extend(_results_from_markdown(path, device_by_id))
        return cls(results=results)

    def search(
        self,
        query: str,
        filters: SearchFilters | None,
        limit: int,
    ) -> list[SearchResult]:
        query_terms = _terms(query)
        ranked: list[tuple[float, int, SearchResult]] = []
        for index, result in enumerate(self.results):
            if not _matches_filters(result, filters):
                continue
            score = _lexical_score(query_terms, result)
            if score <= 0:
                continue
            ranked.append((score, index, result.model_copy(update={"score": score})))

        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [item[2] for item in ranked[:limit]]

    def status(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "backend": "fixture",
            "row_count": len(self.results),
        }


def create_search_service(
    *,
    settings: Settings | None = None,
    backend: SearchBackend | None = None,
    device_provider: DeviceProvider | None = None,
) -> SearchService:
    """Create the default service with injectable seams for tests and E wiring."""

    return SearchService(
        settings=settings or load_settings(),
        backend=backend,
        device_provider=device_provider,
    )


def _merge_filters(
    filters: SearchFilters | None,
    *,
    asset_id: str | None,
) -> SearchFilters:
    base = filters.model_dump(mode="json") if filters is not None else {}
    base["asset_id"] = asset_id
    return SearchFilters.model_validate(base)


def _source_docs_with_fixture_fallback(settings: Settings) -> Path:
    if (settings.paths.source_docs / "devices").exists():
        return settings.paths.source_docs
    return find_project_root() / "fixtures" / "source_docs"


def _known_filter_asset_id(
    filters: SearchFilters | None,
    known_asset_ids: set[str],
) -> str | None:
    if filters is None or filters.asset_id is None:
        return None
    if filters.asset_id not in known_asset_ids:
        raise SearchServiceError(
            "unknown_asset_id",
            f"Device asset_id {filters.asset_id!r} is not registered.",
            status_code=404,
            details={"asset_id": filters.asset_id},
        )
    return filters.asset_id


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


def _results_from_markdown(
    path: Path,
    device_by_id: dict[str, DeviceProfile],
) -> list[SearchResult]:
    raw = path.read_text(encoding="utf-8")
    metadata, body = _split_frontmatter(raw)
    asset_id = metadata.get("asset_id")
    device = device_by_id.get(asset_id or "")
    source_type = SourceType(metadata.get("source_type", SourceType.OTHER.value))
    source_path = metadata.get("source_path", str(path))
    markdown_path = str(path)

    chunks: list[SearchResult] = []
    headings: list[str] = []
    paragraph: list[str] = []
    chunk_index = 0

    def flush() -> None:
        nonlocal chunk_index
        text = " ".join(line.strip() for line in paragraph if line.strip()).strip()
        paragraph.clear()
        if not text:
            return
        chunks.append(
            SearchResult(
                text=text,
                score=None,
                asset_id=asset_id,
                source_type=source_type,
                brand=device.brand if device else None,
                model=device.model if device else None,
                normalized_model=device.normalized_model if device else None,
                device_type=device.device_type if device else None,
                room=device.room if device else None,
                source_path=source_path,
                markdown_path=markdown_path,
                section_title=" > ".join(headings[-3:]) if headings else "Document",
                chunk_index=chunk_index,
                content_hash=None,
                modified_at=0.0,
                tags=list(device.tags) if device else [],
            )
        )
        chunk_index += 1

    for line in body.splitlines():
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            flush()
            level = len(heading.group(1))
            title = heading.group(2)
            headings = headings[: max(level - 1, 0)]
            headings.append(title)
            continue
        if not line.strip():
            flush()
        else:
            paragraph.append(line)
    flush()
    return chunks


def _split_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    if not raw.startswith("---\n"):
        return {}, raw
    _, frontmatter, body = raw.split("---", 2)
    metadata: dict[str, str] = {}
    for line in frontmatter.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()
    return metadata, body


_STOPWORDS = {
    "a",
    "an",
    "and",
    "does",
    "for",
    "how",
    "is",
    "it",
    "mean",
    "of",
    "on",
    "or",
    "the",
    "to",
    "what",
    "where",
}


def _terms(value: str) -> set[str]:
    return {
        term
        for term in re.findall(r"[a-z0-9]+", value.lower())
        if term not in _STOPWORDS
    }


def _lexical_score(query_terms: set[str], result: SearchResult) -> float:
    if not query_terms:
        return 0.0
    text_terms = _terms(result.text)
    metadata = " ".join(
        value
        for value in (
            result.section_title,
            result.brand,
            result.model,
            result.normalized_model,
            result.device_type,
            result.room,
        )
        if value
    )
    metadata_terms = _terms(metadata)
    text_overlap = len(query_terms & text_terms)
    metadata_overlap = len(query_terms & metadata_terms)
    return float((text_overlap * 2) + metadata_overlap)


def _rerank_results(
    query: str,
    results: list[SearchResult],
    limit: int,
) -> list[SearchResult]:
    if not results:
        return []

    query_terms = _terms(query)
    code_terms = _code_terms(query)
    if not query_terms and not code_terms:
        return results[:limit]

    ranked = [
        (_result_query_match_score(query_terms, code_terms, result), index, result)
        for index, result in enumerate(results)
    ]
    ranked.sort(
        key=lambda item: (
            -item[0],
            -(item[2].score or 0.0),
            item[1],
        )
    )
    return [item[2] for item in ranked[:limit]]


def _result_query_match_score(
    query_terms: set[str],
    code_terms: set[str],
    result: SearchResult,
) -> float:
    text = result.text or ""
    metadata = " ".join(
        value
        for value in (
            result.section_title,
            result.source_path,
            result.markdown_path,
            result.brand,
            result.model,
            result.normalized_model,
            result.device_type,
            result.room,
        )
        if value
    )
    text_terms = _terms(text)
    metadata_terms = _terms(metadata)
    score = float(
        (len(query_terms & text_terms) * 4)
        + (len(query_terms & metadata_terms) * 2)
    )

    if code_terms:
        compact_text = _compact_code_text(f"{text} {metadata}")
        for code in code_terms:
            if code in compact_text:
                score += 20.0
    return score


def _code_terms(query: str) -> set[str]:
    terms: set[str] = set()
    for match in re.finditer(
        r"\be\s*[:\-]?\s*\d{2}(?:\s*-\s*\d{2})?\b",
        query.lower(),
    ):
        compact = _compact_code_text(match.group(0))
        if compact:
            terms.add(compact)
    return terms


def _compact_code_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


__all__ = [
    "DeviceProvider",
    "FixtureSearchBackend",
    "LanceSearchBackend",
    "SearchBackend",
    "SearchService",
    "SearchServiceError",
    "create_search_service",
]
