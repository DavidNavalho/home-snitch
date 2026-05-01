# I - Manual Find/Download

## Summary

Find likely manual PDFs for a device and save a selected/simple candidate into the correct `source_docs` device folder. This is a standalone acquisition block.

## Priority

P1. Can start after Phase 0 contracts. It should not block local ingestion/search.

## Dependencies

- A - Project Contracts And Config.
- B - Device Profile Store optional for asset lookup.
- K web fixtures for deterministic tests.

## Can Run In Parallel With

B, C, D, F, and J.

## Goals

- Build query from brand/model/device type.
- Return candidate manual links.
- Download an approved or first simple PDF candidate.
- Save files under the device folder.
- Allow offline tests using stored HTML/PDF fixtures.

## Non-Goals

- No robust vendor-specific scraper in MVP.
- No automatic trust/risk ranking beyond simple heuristics.
- No conversion or indexing.

## Files And Modules

- `homewiki/manuals.py`
- `scripts/manual_find.py`
- `scripts/manual_download.py`

## CLI Contract

Find:

```bash
python scripts/manual_find.py \
  --brand Bosch \
  --model SMS6ZCW00G \
  --device-type dishwasher
```

Download direct URL:

```bash
python scripts/manual_download.py \
  --asset-id dishwasher-bosch-sms6zcw00g \
  --url https://example.com/manual.pdf
```

Find and download simplest candidate:

```bash
python scripts/manual_download.py \
  --asset-id dishwasher-bosch-sms6zcw00g \
  --brand Bosch \
  --model SMS6ZCW00G \
  --device-type dishwasher \
  --first
```

## Python Contract

```python
find_manual_candidates(
    brand: str,
    model: str,
    device_type: str | None = None,
    limit: int = 5,
) -> ManualSearchResult

download_manual(
    asset_id: str,
    url: str,
    source_root: Path,
) -> ManualDownloadResult
```

## API Contract

```text
POST /manuals/find
POST /manuals/download
```

## Implementation Requirements

- Search query should include brand, model, optional device type, `manual`, and `pdf`.
- Prefer direct `.pdf` URLs.
- Validate PDF by content type or `%PDF` file signature.
- Save under:

```text
source_docs/devices/<asset_id>/manuals/<stable_filename>.pdf
```

- Write optional sidecar metadata:

```text
<stable_filename>.pdf.meta.yaml
```

Sidecar fields:

- `source_url`
- `downloaded_at`
- `title`
- `search_query`

- Do not trigger conversion/indexing directly. Later orchestration can do that.

## Error Handling

- No candidates found should return an empty candidate list, not a crash.
- Non-PDF response should fail download with a clear error.
- Network timeouts should be reported with URL and timeout.
- Unknown `asset_id` should fail unless caller supplies a destination override.

## Testing Strategy

### Deterministic Tests

- Parse stored search HTML fixture and return candidates.
- Rank direct PDF above generic web pages.
- Download stored PDF fixture from a local test server or mocked HTTP response.
- Reject non-PDF body.
- Write sidecar metadata.

### Optional Web Tests

Run only with `RUN_WEB_TESTS=1`:

- Perform a live manual search for a known public model.
- Do not assert exact URL; assert at least one plausible PDF/manual candidate.

### LLM-Assisted Evaluation

Optional. Give evaluator candidate titles/URLs and device info. Expected result: evaluator identifies whether candidates are plausibly manuals for the correct brand/model and flags generic SEO pages.

## Expected Scenario Results

### Scenario I1 - Fixture Candidate Search

Input: brand `Bosch`, model `SMS6ZCW00G`, device type `dishwasher`, stored search HTML.

Expected:

- At least one candidate returned.
- Top direct PDF candidate has `is_pdf=true`.
- Candidate title or URL contains `Bosch` or `SMS6ZCW00G`.

### Scenario I2 - Direct PDF Download

Input URL: fixture PDF, asset `dishwasher-bosch-sms6zcw00g`.

Expected:

- PDF saved under `source_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/`.
- File starts with `%PDF`.
- Sidecar metadata includes source URL.

### Scenario I3 - Reject HTML Page

Input URL returns HTML page.

Expected:

- Download fails.
- No `.pdf` file is written.
- Error says response was not PDF-looking.

## Acceptance Criteria

- Manual search/download works independently.
- Deterministic tests do not require live web access.
- Downloaded files land where conversion will later find them.

## Implementation Notes

This package is implemented on the `manual-find-download` branch.

Contract ownership:

- Runtime code imports payload models from `homewiki.schemas`.
- Runtime code imports settings from `homewiki.config`.
- Do not redefine manual request/result/candidate payload shapes in scripts, API adapters, or orchestration layers.

Implemented entry points:

- `homewiki.manuals.build_manual_search_query(...)`
- `homewiki.manuals.find_manual_candidates(...)`
- `homewiki.manuals.parse_manual_search_html(...)`
- `homewiki.manuals.download_manual(...)`
- `homewiki.manuals.stable_manual_filename(...)`
- `scripts/manual_find.py`
- `scripts/manual_download.py`

Search behavior:

- Queries are built as `<brand> <model> [device_type] manual pdf`.
- Live search uses DuckDuckGo HTML search and stdlib HTML parsing.
- Deterministic tests pass fixture HTML through `search_html` or CLI `--fixture-html`.
- Candidate parsing normalizes DuckDuckGo redirect URLs via the `uddg` query parameter.
- Ranking is heuristic only: direct `.pdf` URLs rank above generic manual-looking pages, then brand/model/device term matches adjust order.
- Search failures return `ManualSearchResult(query=..., candidates=[])` because the shared search result contract has no error field.

Download behavior:

- `download_manual(...)` requires an existing `source_docs/devices/<asset_id>/` folder and validates `asset_id` with `homewiki.schemas.is_safe_asset_id`.
- The downloader accepts normal `http(s)` URLs and `file://` URLs, which keeps fixture tests deterministic.
- PDF validation accepts either `Content-Type: application/pdf` or a body that starts with `%PDF` after leading whitespace.
- Saved filenames are deterministic: a slug from the URL basename or title plus a short SHA-256 URL digest.
- Sidecars are written beside the PDF as `<filename>.pdf.meta.yaml` with `source_url`, `downloaded_at`, `title`, and `search_query`.
- The downloader never triggers conversion, indexing, registry sync, or orchestration.

Failure behavior:

- Download failures return `ManualDownloadResult(downloaded=false, error=...)` and do not write a PDF.
- Non-PDF responses use an error containing `not PDF-looking`.
- Unknown assets fail with an `Unknown asset_id` error unless a later caller adds an explicit destination override.
- Network timeouts include the URL and timeout value in the error.

Useful deterministic commands:

```bash
python3 scripts/manual_find.py \
  --brand Bosch \
  --model SMS6ZCW00G \
  --device-type dishwasher \
  --fixture-html fixtures/web/duckduckgo-manual-search.html
```

```bash
python3 scripts/manual_download.py \
  --asset-id dishwasher-bosch-sms6zcw00g \
  --url "file://$(pwd)/fixtures/web/manual.pdf" \
  --source-root fixtures/source_docs \
  --title "Fixture manual"
```

Verification used for this implementation:

```bash
.venv/bin/python -m pytest tests/test_manuals.py -q
.venv/bin/python -m pytest -q
```

Current result: `22 passed, 1 skipped`; the skipped test is the optional live web search gated by `RUN_WEB_TESTS=1`.
