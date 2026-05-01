"""Manual search and PDF download helpers.

This module owns behavior only. Payload shapes come from ``homewiki.schemas`` so
API and orchestration layers can reuse the same contracts without translation.

Search is intentionally simple for the MVP: build a DuckDuckGo HTML query,
parse anchors from the returned page, then rank direct PDF/manual-looking links
using lightweight brand/model/device terms. Tests can pass ``search_html`` to
avoid network access and exercise the same parser against ``fixtures/web``.

Downloads validate that the response is PDF-looking by content type or ``%PDF``
signature, write into ``source_docs/devices/<asset_id>/manuals/``, and create a
small YAML sidecar. This module does not convert or index downloaded files.
"""

from __future__ import annotations

import hashlib
import json
import re
import socket
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse
from urllib.request import Request, urlopen

from homewiki.schemas import (
    ManualCandidate,
    ManualDownloadResult,
    ManualSearchResult,
    is_safe_asset_id,
)


DEFAULT_SEARCH_BASE_URL = "https://duckduckgo.com/html/"
DEFAULT_TIMEOUT_SECONDS = 10.0
USER_AGENT = (
    "Mozilla/5.0 (compatible; HomeWikiManualFinder/0.1; "
    "+https://example.invalid/homewiki)"
)


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a" or self._href is not None:
            return
        attr_map = {key.lower(): value for key, value in attrs}
        href = attr_map.get("href")
        if href:
            self._href = href
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        title = " ".join(" ".join(self._text).split())
        self.links.append((title, self._href))
        self._href = None
        self._text = []


def build_manual_search_query(
    brand: str,
    model: str,
    device_type: str | None = None,
) -> str:
    """Build the MVP manual search query from device identifiers."""

    parts = [brand.strip(), model.strip()]
    if device_type and device_type.strip():
        parts.append(device_type.strip())
    parts.extend(["manual", "pdf"])
    return " ".join(part for part in parts if part)


def find_manual_candidates(
    brand: str,
    model: str,
    device_type: str | None = None,
    limit: int = 5,
    *,
    search_html: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> ManualSearchResult:
    """Find likely manual links for a device.

    Pass ``search_html`` in tests to avoid live network access. Without it, the
    function performs a simple DuckDuckGo HTML search and parses the result page.
    Network failures return an empty candidate list because the result contract
    has no error field.
    """

    query = build_manual_search_query(brand, model, device_type)
    if search_html is None:
        try:
            search_html = _fetch_search_html(query, timeout=timeout)
        except OSError:
            return ManualSearchResult(query=query, candidates=[])

    return parse_manual_search_html(
        search_html,
        query=query,
        limit=limit,
        brand=brand,
        model=model,
        device_type=device_type,
    )


def parse_manual_search_html(
    html: str,
    *,
    query: str,
    limit: int = 5,
    brand: str | None = None,
    model: str | None = None,
    device_type: str | None = None,
    base_url: str = "https://duckduckgo.com/",
) -> ManualSearchResult:
    """Parse search-result HTML into ranked manual candidates."""

    parser = _AnchorParser()
    parser.feed(html)

    terms = _ranking_terms(query, brand=brand, model=model, device_type=device_type)
    seen: set[str] = set()
    scored: list[tuple[float, int, ManualCandidate]] = []

    for original_rank, (raw_title, raw_url) in enumerate(parser.links, start=1):
        url = _normalize_result_url(raw_url, base_url=base_url)
        if not url or url in seen:
            continue
        seen.add(url)

        title = raw_title.strip() or url
        if not _looks_manual_related(title, url):
            continue

        parsed = urlparse(url)
        is_pdf = _url_looks_like_pdf(url)
        candidate = ManualCandidate(
            title=title,
            url=url,
            source_host=parsed.netloc or None,
            is_pdf=is_pdf,
            rank=original_rank,
        )
        scored.append((_candidate_score(candidate, terms), original_rank, candidate))

    scored.sort(key=lambda item: (-item[0], item[1]))
    candidates: list[ManualCandidate] = []
    for rank, (_, _original_rank, candidate) in enumerate(scored[:limit], start=1):
        candidates.append(candidate.model_copy(update={"rank": rank}))

    return ManualSearchResult(query=query, candidates=candidates)


def download_manual(
    asset_id: str,
    url: str,
    source_root: Path,
    *,
    title: str | None = None,
    search_query: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> ManualDownloadResult:
    """Download a PDF manual into ``source_docs/devices/<asset_id>/manuals``."""

    if not is_safe_asset_id(asset_id):
        return _download_error(asset_id, url, "asset_id is not a safe folder name")

    source_root = Path(source_root)
    device_dir = source_root / "devices" / asset_id
    if not device_dir.is_dir():
        return _download_error(
            asset_id,
            url,
            f"Unknown asset_id {asset_id!r}; device folder not found: {device_dir}",
        )

    try:
        body, content_type = _fetch_url_bytes(url, timeout=timeout)
    except TimeoutError:
        return _download_error(
            asset_id,
            url,
            f"Timed out downloading {url} after {timeout:g}s",
        )
    except OSError as exc:
        return _download_error(asset_id, url, f"Failed to download {url}: {exc}")

    if not _is_pdf_response(body, content_type):
        return _download_error(
            asset_id,
            url,
            f"Response was not PDF-looking for {url}",
        )

    manuals_dir = device_dir / "manuals"
    manuals_dir.mkdir(parents=True, exist_ok=True)
    saved_path = manuals_dir / stable_manual_filename(url, title=title)
    saved_path.write_bytes(body)

    sidecar_path = saved_path.with_suffix(saved_path.suffix + ".meta.yaml")
    _write_sidecar(
        sidecar_path,
        source_url=url,
        title=title,
        search_query=search_query,
    )

    return ManualDownloadResult(
        asset_id=asset_id,
        url=url,
        saved_path=str(saved_path),
        sidecar_path=str(sidecar_path),
        downloaded=True,
        error=None,
    )


def stable_manual_filename(url: str, *, title: str | None = None) -> str:
    """Return a deterministic, collision-resistant PDF filename for a URL."""

    parsed = urlparse(url)
    basename = unquote(Path(parsed.path).name)
    stem = basename[:-4] if basename.lower().endswith(".pdf") else ""
    if not stem and title:
        stem = title
    if not stem:
        stem = "manual"

    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._").lower()
    slug = re.sub(r"-+", "-", slug)[:80].strip("-._") or "manual"
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
    return f"{slug}-{digest}.pdf"


def _fetch_search_html(query: str, *, timeout: float) -> str:
    url = f"{DEFAULT_SEARCH_BASE_URL}?q={quote_plus(query)}"
    body, _content_type = _fetch_url_bytes(url, timeout=timeout)
    return body.decode("utf-8", errors="replace")


def _fetch_url_bytes(url: str, *, timeout: float) -> tuple[bytes, str | None]:
    request: str | Request
    if urlparse(url).scheme in {"http", "https"}:
        request = Request(url, headers={"User-Agent": USER_AGENT})
    else:
        request = url

    try:
        with urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type")
            return response.read(), content_type
    except (TimeoutError, socket.timeout) as exc:
        raise TimeoutError from exc
    except ValueError as exc:
        raise OSError(str(exc)) from exc
    except URLError as exc:
        if isinstance(exc.reason, socket.timeout):
            raise TimeoutError from exc
        raise OSError(exc.reason) from exc


def _normalize_result_url(raw_url: str, *, base_url: str) -> str | None:
    raw_url = unescape(raw_url).strip()
    if not raw_url:
        return None

    parsed = urlparse(raw_url)
    if not parsed.scheme:
        raw_url = urljoin(base_url, raw_url)
        parsed = urlparse(raw_url)

    query = parse_qs(parsed.query)
    if "uddg" in query and query["uddg"]:
        raw_url = unquote(query["uddg"][0])
        parsed = urlparse(raw_url)

    if parsed.scheme not in {"http", "https"}:
        return None
    return raw_url


def _ranking_terms(
    query: str,
    *,
    brand: str | None,
    model: str | None,
    device_type: str | None,
) -> list[str]:
    terms = [term for term in [brand, model, device_type] if term]
    if terms:
        return terms
    ignored = {"manual", "pdf", "user", "guide"}
    return [term for term in query.split() if term.lower() not in ignored]


def _candidate_score(candidate: ManualCandidate, terms: list[str]) -> float:
    text = f"{candidate.title} {candidate.url}".lower()
    normalized_text = _normalize_for_match(text)
    score = 0.0

    if candidate.is_pdf:
        score += 30.0
    if "manual" in text:
        score += 15.0
    if "pdf" in text:
        score += 5.0

    for term in terms:
        lower_term = term.lower()
        normalized_term = _normalize_for_match(term)
        if lower_term and lower_term in text:
            score += 20.0
            continue
        if normalized_term and normalized_term in normalized_text:
            score += 20.0

    return score


def _looks_manual_related(title: str, url: str) -> bool:
    text = f"{title} {url}".lower()
    return "manual" in text or "pdf" in text or _url_looks_like_pdf(url)


def _url_looks_like_pdf(url: str) -> bool:
    return unquote(urlparse(url).path).lower().endswith(".pdf")


def _normalize_for_match(value: str) -> str:
    return "".join(char.lower() for char in value if char.isalnum())


def _is_pdf_response(body: bytes, content_type: str | None) -> bool:
    if content_type and "application/pdf" in content_type.lower():
        return True
    return body.lstrip().startswith(b"%PDF")


def _write_sidecar(
    path: Path,
    *,
    source_url: str,
    title: str | None,
    search_query: str | None,
) -> None:
    downloaded_at = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    fields = {
        "source_url": source_url,
        "downloaded_at": downloaded_at,
        "title": title,
        "search_query": search_query,
    }
    lines = [f"{key}: {_yaml_scalar(value)}" for key, value in fields.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _yaml_scalar(value: str | None) -> str:
    if value is None:
        return "null"
    return json.dumps(value, ensure_ascii=True)


def _download_error(asset_id: str, url: str, error: str) -> ManualDownloadResult:
    return ManualDownloadResult(
        asset_id=asset_id,
        url=url,
        saved_path=None,
        sidecar_path=None,
        downloaded=False,
        error=error,
    )


__all__ = [
    "build_manual_search_query",
    "download_manual",
    "find_manual_candidates",
    "parse_manual_search_html",
    "stable_manual_filename",
]
