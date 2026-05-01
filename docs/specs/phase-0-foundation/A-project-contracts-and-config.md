# A - Project Contracts And Config

## Summary

Define stable contracts for configuration, data schemas, API payloads, filesystem layout, and provider settings. This package is the dependency boundary for all later work.

## Priority

P0. Start immediately.

## Status

Done.

Implemented contract files:

- `homewiki/config.py` for environment defaults, provider settings, API settings, and path resolution.
- `homewiki/schemas.py` for shared Pydantic v2 data/API contracts.
- `homewiki/py.typed` so installed package consumers can treat `homewiki` as typed.
- `.env.example` for the canonical local-development environment contract.
- `pyproject.toml` for install metadata and test configuration.
- `tests/test_config.py` and `tests/test_schemas.py` for deterministic contract checks.

Validation commands:

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q
python3 -m unittest discover -s tests
python3 -m compileall homewiki tests
```

During the initial implementation run, dependencies were installed into `/private/tmp/home-snitch-deps` to avoid writing dependency artifacts into the repo. A clean checkout should use `requirements-dev.txt` or `pyproject.toml` as shown above.

## Dependencies

None.

## Can Run In Parallel With

K - Fixtures And Smoke Tests.

## Goals

- Define the canonical folder layout.
- Define shared schemas for devices, ingestion, search, ask, manual acquisition, and model provider settings.
- Define environment variables and defaults.
- Keep config/schema imports lightweight and side-effect free.
- Let other workers build against shared types rather than duplicating contracts.

## Non-Goals

- No LanceDB implementation.
- No model calls.
- No UI.
- No document conversion.

## Folder Contract

```text
source_docs/
  devices/
    <asset_id>/
      profile.yaml
      profile.md
      manuals/
      notes/
      receipts/
      photos/

markdown_docs/
  devices/
    <asset_id>/
      profile.md
      manuals/
        <source_filename>.md
      notes/
      receipts/

lancedb_data/
data/
```

## Environment Contract

```text
HOME_WIKI_SOURCE_DOCS=source_docs
HOME_WIKI_MARKDOWN_DOCS=markdown_docs
HOME_WIKI_LANCEDB_DIR=lancedb_data
HOME_WIKI_TABLE=home_wiki_chunks
HOME_WIKI_DEVICE_REGISTRY=data/devices.sqlite
HOME_WIKI_INGEST_MANIFEST=data/ingest_manifest.sqlite

EMBEDDING_PROVIDER=local_gguf | openai_compatible | fake
EMBEDDING_API_BASE=http://localhost:1234/v1
EMBEDDING_API_KEY=
EMBEDDING_MODEL=
GGUF_MODEL_REPO=
GGUF_MODEL_FILE=
GGUF_N_CTX=8192
GGUF_N_THREADS=4

CHAT_PROVIDER=openai_compatible | disabled
CHAT_API_BASE=
CHAT_API_KEY=
CHAT_MODEL=

API_HOST=127.0.0.1
API_PORT=8000
UI_API_BASE=http://127.0.0.1:8000
```

`fake` embedding provider is for deterministic tests only.

## Required Schemas

### DeviceProfile

Fields:

- `asset_id: str`
- `device_type: str`
- `brand: str`
- `model: str`
- `normalized_model: str`
- `aliases: list[str]`
- `room: str | None`
- `serial_number: str | None`
- `purchase_date: date | None`
- `warranty_until: date | None`
- `support_url: str | None`
- `notes: str | None`
- `tags: list[str]`
- `created_at: datetime | None`
- `updated_at: datetime | None`

Rules:

- `asset_id` is stable and URL/file safe.
- `normalized_model` removes punctuation, whitespace, underscores, and hyphens, then lowercases.
- Empty optional fields remain present in YAML as empty/null values where practical.

### IndexChunk

Fields:

- `text: str`
- `asset_id: str | None`
- `source_type: profile | manual | note | receipt | photo_ocr | other`
- `brand: str | None`
- `model: str | None`
- `normalized_model: str | None`
- `device_type: str | None`
- `room: str | None`
- `source_path: str`
- `markdown_path: str`
- `section_title: str`
- `chunk_index: int`
- `content_hash: str`
- `modified_at: datetime | float`
- `tags: list[str]`

### DeviceResolution

Fields:

- `status: exact | ambiguous | none`
- `asset_id: str | None`
- `confidence: float`
- `matched_on: list[str]`
- `candidates: list[DeviceCandidate]`
- `filters: SearchFilters`

### SearchFilters

Fields:

- `asset_id: str | None`
- `normalized_model: str | None`
- `device_type: str | None`
- `room: str | None`
- `source_type: str | None`

### SearchRequest

Fields:

- `query: str`
- `asset_id: str | None`
- `filters: SearchFilters | None`
- `limit: int`
- `allow_global_fallback: bool`

### SearchResponse

Fields:

- `query: str`
- `resolution: DeviceResolution`
- `scope: device | filtered | global | none`
- `results: list[SearchResult]`

### AskRequest

Fields:

- `question: str`
- `asset_id: str | None`
- `limit: int`
- `allow_global_fallback: bool`

### AskResponse

Fields:

- `answer: str`
- `resolution: DeviceResolution`
- `sources: list[str]`
- `evidence: list[SearchResult]`
- `confidence: int`
- `generated: bool`
- `missing_information: list[str]`

### ManualCandidate

Fields:

- `title: str`
- `url: str`
- `source_host: str | None`
- `is_pdf: bool`
- `rank: int`

## Implementation Requirements

- Put schemas in a module that does not import implementation modules.
- Put settings in a module that only reads environment variables and resolves paths.
- Path settings must accept absolute or repo-relative values.
- Defaults must work for local development.
- Types must be serializable to JSON for API responses.
- Error models should include `code`, `message`, and optional `details`.

## Testing Strategy

### Deterministic Tests

- Import settings with no environment variables.
- Import schemas without LanceDB installed.
- Validate a complete `DeviceProfile`.
- Validate a minimal `DeviceProfile`.
- Validate invalid enum values fail for source type and resolution status.
- Confirm relative paths resolve under the repo root.
- Confirm absolute paths remain absolute.

### LLM-Assisted Evaluation

Optional. Ask an evaluator to inspect the generated schemas and answer:

- Are all fields needed by device-scoped retrieval present?
- Can UI, API, ingestion, and search be built without inventing new payload shapes?
- Are provider settings separated from UI settings?

The expected evaluator result is: "No blocking schema gaps for Phase 1 work; any suggestions are additive."

## Expected Scenario Results

### Scenario A1 - Default Config

Input: no relevant environment variables.

Expected:

- Source docs default to `source_docs`.
- Markdown docs default to `markdown_docs`.
- LanceDB directory defaults to `lancedb_data`.
- Table defaults to `home_wiki_chunks`.
- Chat provider can be disabled or unconfigured without import failure.

### Scenario A2 - DeviceProfile Validation

Input:

```yaml
asset_id: dishwasher-bosch-sms6zcw00g
device_type: dishwasher
brand: Bosch
model: SMS6ZCW00G
normalized_model: sms6zcw00g
aliases:
  - kitchen dishwasher
room: kitchen
tags:
  - appliance
```

Expected:

- Schema validates.
- `aliases` is a list.
- `tags` is a list.
- No model/provider imports happen during validation.

### Scenario A3 - SearchResponse Contract

Input: ambiguous device resolution with two candidates.

Expected:

- `resolution.status` is `ambiguous`.
- `results` can be empty.
- Response is still valid.
- UI has enough data to ask user to pick a device.

## Acceptance Criteria

- Shared schema and config modules exist.
- All schema tests pass without network access.
- Phase 1 implementers can import common types without pulling in LanceDB, FastAPI, model clients, or web search code.

## Implementation Notes For Downstream Workers

### Import Boundary

Downstream packages should import shared contracts from:

```python
from homewiki.config import load_settings
from homewiki.schemas import DeviceProfile, SearchRequest, SearchResponse
```

`homewiki.config` is stdlib-only. It reads environment variables when `load_settings()` is called, resolves paths, validates enum-like provider values, and returns immutable dataclasses. It does not create directories, open databases, load `.env` files, start servers, or import implementation modules.

`homewiki.schemas` imports only Pydantic and stdlib modules. It does not import LanceDB, FastAPI, model clients, conversion tools, web search, or filesystem service modules.

### Settings Behavior

- Relative path environment values resolve under the project root.
- Absolute path environment values remain absolute and are not canonicalized through platform symlink aliases.
- Defaults are suitable for local development and deterministic tests.
- `EMBEDDING_PROVIDER=fake` is allowed for tests only; production embedding implementations should fail clearly if `local_gguf` or `openai_compatible` is selected without required model settings.
- `CHAT_PROVIDER=disabled` is a first-class configuration for evidence-only ask behavior.

### Schema Behavior

- All public models inherit from `ContractModel`, which forbids unexpected fields and supports `to_json_dict()` for API-safe JSON serialization.
- Enums serialize as their wire values, for example `manual`, `exact`, and `device`.
- `DeviceProfile.normalized_model` is validated against `normalize_model_identifier(model)`, which lowercases and removes all non-alphanumeric characters.
- `asset_id` values must be lowercase letters, numbers, and hyphens.
- `SearchResult` is the API-facing evidence shape and intentionally excludes raw vectors.
- `DeviceCandidate` is the candidate item shape used by `DeviceResolution.candidates`.
- `ErrorResponse` is the common structured error payload with `code`, `message`, and optional `details`.

### Additional Shared Shapes

The implementation includes additive contracts needed by later specs so workers do not invent local variants:

- `DocumentMetadata`
- `SearchResult`
- `ManualSearchResult`
- `ManualDownloadResult`
- `FileConversionResult`
- `ConversionReport`
- `IndexResult`
- `IngestReport`
- `RegistrySyncResult`
- `ProviderSettings`

These are stable enough for Phase 1 work. Add fields only when a downstream implementation has a concrete need; do not fork duplicate result/report models inside implementation modules.

### Explicit Non-Implementation

This package does not implement:

- Device profile file writes or registry sync.
- Runtime directory creation.
- YAML serialization rules beyond schema shape.
- LanceDB table creation or search.
- Embeddings, model calls, conversion, web/manual download, API endpoints, or UI.

Those belong to later work packages and should build against these contracts.
