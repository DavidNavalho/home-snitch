# Home Wiki Build Plan

This document captures the agreed direction for the home wiki project and breaks it into independently buildable work packages. The goal is to start with small, launchable scripts/agents, expose them through an API, and add connecting tissue iteratively.

Detailed implementation specs are split by phase under [docs/specs/README.md](specs/README.md). Treat this document as the roadmap and the phase specs as the build contracts.

## Design Principles

- Use LanceDB from the start. Do not start with a temporary retrieval backend that must be swapped out later.
- Lift and adapt SIBS project pieces where they fit: document conversion, heading-aware chunking, LanceDB schema, hybrid search, and retrieval-first answer generation.
- Keep the UI completely separate from models and agents. The UI calls an API; the API calls scripts/services/agents.
- Keep each building block runnable independently from CLI and callable from Python/API.
- Resolve the target device/model before retrieval whenever possible, then run semantic/keyword search inside that narrowed scope.
- Store device metadata both as editable files and as queryable/indexed records.
- Make model providers configurable. Start with an OpenAI-compatible Codex/chat model path for generation, and support local model experiments later. Prefer local embeddings where practical.
- Build retrieval quality before building richer chat behavior.

## Target MVP Flow

1. User adds or updates a device profile.
2. User optionally downloads or drops manuals/notes/receipts into that device folder.
3. Ingestion converts documents to Markdown.
4. Indexing chunks Markdown and stores records in LanceDB with device metadata.
5. Search resolves the intended device, filters LanceDB by `asset_id` or model metadata, and performs hybrid retrieval inside that scope.
6. Ask endpoint retrieves evidence first, then asks a configurable model to answer only from that evidence.
7. Basic local web UI calls the API for device management, search, ask, and manual ingestion.

## Priority And Parallelization

| ID | Work Package | Priority | Can Start Now? | Depends On | Parallel Notes |
| --- | --- | --- | --- | --- | --- |
| A | Project contracts and config | P0 | Yes | None | Must land first or very early. Other tracks can mock these contracts. |
| B | Device profile store | P0 | Yes | A, or agreed schema below | Can run in parallel with C and D after schema is accepted. |
| C | Document conversion lift | P0 | Yes | A | Independent of LanceDB and UI. |
| D | LanceDB embedding/search foundation | P0 | Yes | A | Can be built against synthetic chunks before ingestion is done. |
| E | Markdown chunking and index build | P0 | After B/C/D begin | B, C, D | Integrates metadata, conversion outputs, and LanceDB. |
| F | Device resolver | P0 | After B begins | B | Can be tested with fixture profiles before ingestion exists. |
| G | Search API | P0 | After D/F begin | D, F | Can start with fake search responses, then wire to LanceDB. |
| H | Ask API | P1 | After G contract | G, model config | Retrieval-before-generation only for MVP. |
| I | Manual find/download | P1 | Yes | A, B optional | Independent web acquisition block. Can write into agreed folders. |
| J | Basic local web UI | P1 | Yes, with mocked API | API contract from A/G/H | Fully separate from model code. |
| K | Fixtures and smoke tests | P0 | Yes | A | Can run in parallel and guide acceptance across all packages. |
| L | Orchestration layer | P2 | Later | B-I | Adds workflows after individual blocks work. |
| M | WiFi diagnostics block | P2 | Later | A only | Separate agent/script track; not on critical path for home wiki RAG. |

P0 items define the working spine. P1 items are useful immediately but should not block ingestion/search quality. P2 items should wait until the independent blocks are stable.

## Shared Contracts

### Folder Layout

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
        <manual>.pdf.md
      notes/
      receipts/

lancedb_data/
```

### Device Profile YAML

```yaml
asset_id: dishwasher-bosch-sms6zcw00g
device_type: dishwasher
brand: Bosch
model: SMS6ZCW00G
normalized_model: sms6zcw00g
aliases:
  - kitchen dishwasher
  - dishwasher
room: kitchen
serial_number:
purchase_date:
warranty_until:
support_url:
notes:
tags:
  - appliance
```

`profile.yaml` is the structured source of truth. `profile.md` is a human-readable source document that also gets indexed.

### LanceDB Chunk Record

Each indexed chunk should include:

```text
id
text
vector
asset_id
source_type: profile | manual | note | receipt | photo_ocr | other
brand
model
normalized_model
device_type
room
source_path
markdown_path
section_title
chunk_index
content_hash
modified_at
tags
```

### Device Resolution Result

```json
{
  "status": "exact | ambiguous | none",
  "asset_id": "dishwasher-bosch-sms6zcw00g",
  "confidence": 0.95,
  "matched_on": ["model", "alias"],
  "candidates": [],
  "filters": {
    "asset_id": "dishwasher-bosch-sms6zcw00g"
  }
}
```

Search should use the returned filters. If resolution is ambiguous, the API should return candidates rather than pretending it knows the right device.

## Work Package Specs

### A. Project Contracts And Config

Objective: define stable module, CLI, API, folder, and configuration contracts so parallel work can proceed independently.

Files/modules:

- `docs/home_wiki_build_plan.md`
- `.env.example`
- package layout, e.g. `homewiki/`
- shared schema module, e.g. `homewiki/schemas.py`
- shared settings module, e.g. `homewiki/config.py`

Configuration:

```text
HOME_WIKI_SOURCE_DOCS=source_docs
HOME_WIKI_MARKDOWN_DOCS=markdown_docs
HOME_WIKI_LANCEDB_DIR=lancedb_data
HOME_WIKI_TABLE=home_wiki_chunks
HOME_WIKI_DEVICE_REGISTRY=data/devices.sqlite or data/devices.json

EMBEDDING_PROVIDER=local_gguf | openai_compatible
EMBEDDING_API_BASE=http://localhost:1234/v1
EMBEDDING_API_KEY=
EMBEDDING_MODEL=

CHAT_PROVIDER=openai_compatible
CHAT_API_BASE=
CHAT_API_KEY=
CHAT_MODEL=
```

Implementation details:

- Add typed settings object.
- Add shared Pydantic models for device profiles, resolution results, search requests/responses, ask requests/responses, ingestion results, and manual candidates.
- Keep provider config separate from UI config.
- Define all path defaults relative to repo root unless absolute paths are supplied.

CLI/API contracts:

- No business CLI required here.
- API version prefix can be omitted for MVP, but contracts should be typed.

Acceptance criteria:

- Importing config/schemas has no side effects beyond reading environment variables.
- All other packages can depend on shared schemas without importing LanceDB or model clients.

Parallel safety:

- This package is the dependency boundary. It should avoid importing implementation modules.

### B. Device Profile Store

Objective: create, update, read, and list home device profiles as both editable files and indexed records.

Files/modules:

- `homewiki/devices.py`
- `scripts/device_add.py`
- `source_docs/devices/<asset_id>/profile.yaml`
- `source_docs/devices/<asset_id>/profile.md`
- optional registry: `data/devices.sqlite` or `data/devices.json`

Inputs:

- Brand, model, device type, room, aliases, serial number, purchase date, warranty date, notes, tags.

Outputs:

- Valid `profile.yaml`.
- Generated `profile.md`.
- Registry entry for quick lookup/resolution.

Implementation details:

- Generate `asset_id` from `device_type`, `brand`, and `model`.
- Generate `normalized_model` by lowercasing and removing spaces, hyphens, underscores, and punctuation.
- Validate uniqueness of `asset_id`.
- Preserve user-provided fields when updating.
- Render `profile.md` from YAML so the profile itself is searchable.
- Store profile records in a registry for fast resolver use. The YAML remains the source of truth.

CLI:

```bash
python scripts/device_add.py \
  --device-type dishwasher \
  --brand Bosch \
  --model SMS6ZCW00G \
  --room kitchen \
  --alias "kitchen dishwasher"
```

Python contract:

```python
upsert_device(profile: DeviceProfile) -> DeviceProfile
list_devices() -> list[DeviceProfile]
get_device(asset_id: str) -> DeviceProfile | None
```

Acceptance criteria:

- Adding a device creates both YAML and Markdown.
- Re-running with the same model updates rather than duplicates.
- Registry can list devices without scanning every source file each time.

Parallel safety:

- Can be built independently from LanceDB.
- Device resolver can use fixture profiles while this is under development.

### C. Document Conversion Lift

Objective: adapt the SIBS conversion approach so source documents become inspectable Markdown while preserving folder structure.

Files/modules:

- `homewiki/conversion.py`
- `scripts/docs_convert.py`
- lifted/adapted logic from `/Users/jinx/gits/sibs/SIBS-LLMs/scripts/convert_docs_to_markdown.py`

Supported inputs:

- PDF, DOCX, DOC, XLSX, CSV, HTML, JSON, TXT, Markdown, PPTX where practical.

Outputs:

- Markdown files under `markdown_docs/` mirroring `source_docs/`.
- Conversion report with converted/skipped/failed counts.

Implementation details:

- Reuse SIBS PDF cleanup where it helps.
- Reuse Excel-to-Markdown table handling.
- Use `markitdown` for formats where it is already reliable.
- Preserve relative folder paths.
- Include source metadata/frontmatter where useful:

```yaml
---
source_path: source_docs/devices/...
source_type: manual
asset_id: dishwasher-bosch-sms6zcw00g
---
```

- Skip unchanged files by mtime/content hash.
- Report failures without stopping the whole run unless `--fail-fast` is set.

CLI:

```bash
python scripts/docs_convert.py
python scripts/docs_convert.py --source source_docs --output markdown_docs --force
```

Python contract:

```python
convert_tree(source_root: Path, markdown_root: Path, force: bool = False) -> ConversionReport
```

Acceptance criteria:

- A PDF manual becomes a readable `.md` file.
- A `profile.md` remains readable and is copied/normalized.
- Folder structure is preserved.
- Conversion does not require LanceDB or a model.

Parallel safety:

- Independent of indexing and API.

### D. LanceDB Embedding/Search Foundation

Objective: provide the LanceDB table schema, embedding provider abstraction, and low-level hybrid search.

Files/modules:

- `homewiki/embeddings.py`
- `homewiki/lancedb_store.py`
- lifted/adapted logic from SIBS `lancedb_store.py` and `gguf_embeddings.py`

Embedding provider options:

- `local_gguf`: SIBS-style `llama-cpp-python` GGUF embedding function.
- `openai_compatible`: call an OpenAI-compatible embeddings endpoint, potentially LM Studio if configured and compatible.

Implementation details:

- Use one LanceDB table for chunks initially: `home_wiki_chunks`.
- Register embedding function before opening tables.
- Build schema dynamically after embedding model dimensions are known.
- Create FTS index on `text`.
- Create scalar indexes on `asset_id`, `normalized_model`, `device_type`, `room`, `source_type`, and `section_title`.
- Use hybrid search with RRF reranking.
- Expose low-level search that accepts a metadata filter.

Python contract:

```python
index_chunks(chunks: list[IndexChunk], mode: str = "append") -> IndexResult

hybrid_search(
    query: str,
    filters: SearchFilters | None = None,
    limit: int = 8,
) -> list[SearchResult]
```

Filter behavior:

- If `asset_id` is present, filter by exact `asset_id`.
- Else if `normalized_model` is present, filter by exact normalized model.
- Else if device type/room are present, use those as weaker filters.
- Else search globally.

Acceptance criteria:

- Synthetic chunks can be indexed and searched.
- Exact model/error-code queries work through keyword search.
- Natural-language troubleshooting questions work through semantic search.
- Searches can be limited to one `asset_id`.

Parallel safety:

- Can be built with synthetic chunks before conversion/indexing are ready.

### E. Markdown Chunking And Index Build

Objective: turn converted Markdown plus device metadata into LanceDB records.

Files/modules:

- `homewiki/chunking.py`
- `homewiki/ingest.py`
- `scripts/index_build.py`
- `scripts/ingest.py` as combined convert+index runner

Inputs:

- `markdown_docs/`
- `source_docs/devices/<asset_id>/profile.yaml`

Outputs:

- LanceDB rows in `home_wiki_chunks`.
- Ingestion manifest recording content hashes and chunk counts.

Implementation details:

- Split by Markdown headings.
- Preserve parent heading context: `Troubleshooting > Error Codes`.
- Merge tiny chunks forward to avoid useless embeddings.
- Attach metadata from nearest device profile based on folder path.
- Infer `source_type` from path: `manuals`, `notes`, `receipts`, `profile`.
- Use content hashes for incremental indexing.
- Delete/reindex chunks for changed documents.
- Remove LanceDB rows for deleted Markdown files.

CLI:

```bash
python scripts/index_build.py
python scripts/ingest.py
python scripts/ingest.py --force-convert --force-index
```

Python contract:

```python
build_index(markdown_root: Path, source_root: Path, db_dir: Path) -> IngestReport
```

Acceptance criteria:

- A device profile and manual become searchable LanceDB chunks with the same `asset_id`.
- Re-running ingestion skips unchanged files.
- Deleting a source/Markdown file removes stale chunks.

Parallel safety:

- Depends on B, C, and D contracts, but can be developed using fixtures.

### F. Device Resolver

Objective: identify the intended device/model from a user query or explicit UI selection before retrieval.

Files/modules:

- `homewiki/resolver.py`
- `scripts/device_resolve.py`

Inputs:

- User query.
- Optional explicit `asset_id`.
- Device registry.

Outputs:

- `DeviceResolution` result with `exact`, `ambiguous`, or `none`.
- Search filters to pass to LanceDB.

Implementation details:

- If request includes `asset_id`, validate it and return exact resolution.
- Extract model-like tokens from query: alphanumeric strings with digits, hyphens, slashes, or brand-specific patterns.
- Normalize query tokens and compare against `normalized_model`.
- Match aliases, room, device type, and brand.
- Score candidates:
  - exact normalized model match: high confidence;
  - alias + device type: medium;
  - room + device type: medium/low;
  - brand only: low.
- Return ambiguous if top candidates are close or confidence is below threshold.

CLI:

```bash
python scripts/device_resolve.py "E15 on kitchen dishwasher"
```

Python contract:

```python
resolve_device(query: str, asset_id: str | None = None) -> DeviceResolution
```

Acceptance criteria:

- Exact model queries resolve to one device.
- Alias queries resolve when unique.
- Ambiguous queries return candidates instead of guessing.
- No-match queries return `none` and allow global search fallback.

Parallel safety:

- Can be built using static YAML fixtures before indexing exists.

### G. Search API

Objective: expose retrieval through an HTTP API that performs device resolution and filtered hybrid search.

Files/modules:

- `homewiki/api.py`
- `homewiki/search_service.py`

Endpoint:

```text
POST /search
```

Request:

```json
{
  "query": "E15 on dishwasher",
  "asset_id": null,
  "limit": 8,
  "allow_global_fallback": true
}
```

Response:

```json
{
  "query": "E15 on dishwasher",
  "resolution": {
    "status": "exact",
    "asset_id": "dishwasher-bosch-sms6zcw00g",
    "confidence": 0.95
  },
  "results": [
    {
      "source_path": "...",
      "section_title": "Troubleshooting > Error Codes",
      "asset_id": "dishwasher-bosch-sms6zcw00g",
      "score": 0.82,
      "text": "..."
    }
  ]
}
```

Implementation details:

- Call resolver first.
- If exact, pass `asset_id` filter to LanceDB.
- If ambiguous, return candidates and no answer unless request explicitly allows global fallback.
- If none and fallback allowed, search globally and mark result scope as global.
- Return source metadata and sections visibly.

Acceptance criteria:

- Search can be scoped to a specific device.
- Global fallback is explicit in the response.
- UI can show ambiguous device candidates.

Parallel safety:

- API can be built against resolver/search mocks while D/F finish.

### H. Ask API

Objective: answer questions from retrieved home wiki evidence using configurable chat models.

Files/modules:

- `homewiki/ask_service.py`
- `homewiki/llm.py`
- `homewiki/prompts.py`

Endpoint:

```text
POST /ask
```

Request:

```json
{
  "question": "What does E15 mean on the dishwasher?",
  "asset_id": "dishwasher-bosch-sms6zcw00g",
  "limit": 8
}
```

Response:

```json
{
  "answer": "...",
  "resolution": {},
  "sources": ["...manual.pdf.md"],
  "evidence": [],
  "confidence": 7,
  "generated": true,
  "missing_information": []
}
```

Implementation details:

- Use retrieval-before-generation for MVP.
- Call `/search` service internally.
- If search is ambiguous, return candidates instead of generating an answer.
- If no evidence, say the home wiki does not contain enough information.
- Prompt must require citations and prohibit unsupported claims.
- Generation provider should be OpenAI-compatible.
- If no chat model is configured, return retrieved evidence only.

Prompt rules:

- Answer only from provided evidence.
- Prefer exact model/error-code matches.
- Do not invent repair steps, warranty status, or phone numbers.
- Separate found evidence from missing information.
- Mention source filenames/sections.

Acceptance criteria:

- Ask never generates without retrieval.
- Ask refuses/defers when resolution is ambiguous.
- Ask returns useful evidence-only output when model config is absent.

Parallel safety:

- Can be built after G contract exists, even with mock search responses.

### I. Manual Find/Download

Objective: given brand/model/device, find likely manual PDFs and save the selected/simple candidate into the correct source folder.

Files/modules:

- `homewiki/manuals.py`
- `scripts/manual_find.py`
- `scripts/manual_download.py`

Inputs:

- Brand, model, device type, optional `asset_id`.

Outputs:

- Candidate list.
- Downloaded PDF under `source_docs/devices/<asset_id>/manuals/`.

Implementation details:

- Start simplest: search web for `<brand> <model> <device> manual pdf`.
- Prefer direct PDF-looking URLs.
- Validate downloaded content starts with PDF signature or has PDF content type.
- Save with stable filename.
- Record source URL in sidecar metadata file if useful:

```text
manual.pdf
manual.pdf.meta.yaml
```

CLI:

```bash
python scripts/manual_find.py --brand Bosch --model SMS6ZCW00G --device dishwasher
python scripts/manual_download.py --asset-id dishwasher-bosch-sms6zcw00g --url https://...
```

API endpoints:

```text
POST /manuals/find
POST /manuals/download
```

Acceptance criteria:

- Candidate search returns URLs and titles.
- Download saves a PDF under the device folder.
- Downloaded manuals are picked up by the normal conversion/indexing flow.

Parallel safety:

- Can be built independently after folder/schema agreement.

### J. Basic Local Web UI

Objective: provide a simple browser UI that only talks to the API and contains no model logic.

Files/modules:

- `ui/`
- optional frontend dev server, or static HTML served separately

Views:

- Devices: list/add/edit minimal profiles.
- Manuals: find/download manual candidates for a selected device.
- Search: query local index, show scope, snippets, and sources.
- Ask: question box, optional device selector, answer and evidence.

Implementation details:

- UI calls API endpoints only.
- No direct LanceDB access.
- No direct model provider access.
- Keep design utilitarian and compact.
- Show when search is device-scoped versus global.
- Show ambiguity and ask user to choose device when needed.

Acceptance criteria:

- User can add a device.
- User can trigger ingest.
- User can search and ask through API.
- Ambiguous device resolution is visible.

Parallel safety:

- Can start with mocked API responses once endpoint contracts are defined.

### K. Fixtures And Smoke Tests

Objective: provide repeatable local fixtures that prove each block works and prevent regressions.

Files/modules:

- `tests/`
- `fixtures/source_docs/devices/...`
- `fixtures/markdown_docs/...`

Fixtures:

- One device profile.
- One short manual-like Markdown file with troubleshooting/error-code sections.
- One PDF fixture if practical.
- Ambiguous two-device fixture for resolver tests.

Test coverage:

- Device profile creation.
- Model normalization.
- Device resolution exact/ambiguous/none.
- Markdown chunking preserves section breadcrumbs.
- LanceDB index/search can filter by `asset_id`.
- Search API returns scoped results.
- Ask API does not generate when evidence is missing.

Acceptance criteria:

- One command runs local smoke tests.
- Tests do not require external web access.
- Model-dependent tests are optional/skipped unless env vars are set.

Parallel safety:

- Can be built early and used by every other track.

### L. Orchestration Layer

Objective: connect independent blocks into larger workflows once the blocks are stable.

Example workflows:

- Add device -> find manual -> download -> convert -> index -> search smoke test.
- Ask broken-device question -> resolve device -> search local docs -> answer -> optionally suggest online lookup.
- Scheduled reindex of changed docs.

Implementation details:

- Keep orchestration thin.
- Do not bury block-specific behavior in the orchestrator.
- Prefer simple workflow scripts before adding a heavier agent framework.

Acceptance criteria:

- Workflows call the same public functions/CLI contracts as manual usage.
- Any single block can still run independently.

### M. WiFi Diagnostics Block

Objective: separate future block to diagnose current WiFi/network conditions and suggest better network choices for downloads.

Initial scope:

- Collect current SSID, signal quality, gateway, DNS reachability, ping latency, and download test if allowed.
- Optionally compare known WiFi networks if the OS exposes them.
- Recommend whether to postpone/download over another network.

Implementation notes:

- Keep separate from home wiki RAG.
- Expose through API later as another independent agent/tool.

## First Implementation Sequence

1. Land A: contracts/config/schemas.
2. Land K fixtures in parallel with A.
3. Land B device profile store.
4. Land D LanceDB foundation using synthetic chunks.
5. Land C document conversion lift.
6. Land F resolver using device fixtures.
7. Land E ingestion/index integration.
8. Land G search API.
9. Land H ask API.
10. Land J simple UI against API.
11. Land I manual find/download when core local ingestion/search is stable, or in parallel if someone else owns it.

## Immediate Parallel Starts

These can begin now without waiting for the whole system:

- A: contracts/config/schemas.
- B: device profile store, using the schema in this document.
- C: document conversion lift from SIBS.
- D: LanceDB foundation with synthetic chunks.
- I: manual find/download, writing into the agreed folder layout.
- J: UI shell with mocked API responses.
- K: fixtures and smoke tests.

The main coordination point is the shared schema. Once A is landed, the other tracks should depend on those types rather than redefining request/response shapes.
