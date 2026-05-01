# D - LanceDB Embedding/Search Foundation

## Summary

Implement the LanceDB storage and low-level hybrid search layer. This package owns embedding provider setup, table schema, indexes, and filtered hybrid retrieval.

## Priority

P0. Start after Phase 0 contracts.

## Dependencies

- A - Project Contracts And Config.
- SIBS reference `lancedb_store.py` and `gguf_embeddings.py`.

## Can Run In Parallel With

B, C, F, I, and J. It can use synthetic chunks before ingestion exists.

## Goals

- Use LanceDB from the start.
- Support local embedding paths and OpenAI-compatible embedding endpoints.
- Provide deterministic fake embeddings for tests.
- Support metadata-filtered hybrid search.
- Create search indexes needed for model/error-code retrieval.

## Non-Goals

- No document conversion.
- No device resolver.
- No chat answer generation.
- No UI.

## Files And Modules

- `homewiki/embeddings.py`
- `homewiki/lancedb_store.py`
- optional `homewiki/gguf_embeddings.py` adapted from SIBS

## Embedding Providers

### `local_gguf`

Lift/adapt SIBS `gguf_embeddings.py`:

- Load GGUF embedding model via `llama-cpp-python`.
- Allow `GGUF_MODEL_REPO`, `GGUF_MODEL_FILE`, `GGUF_N_CTX`, `GGUF_N_THREADS`.
- Register with LanceDB before table open/search.

### `openai_compatible`

Use an OpenAI-compatible embeddings endpoint:

- `EMBEDDING_API_BASE`
- `EMBEDDING_API_KEY`
- `EMBEDDING_MODEL`

This may target LM Studio if its embeddings endpoint is compatible.

### `fake`

Test-only deterministic embedding provider:

- Fixed dimension.
- Stable vector generated from text hash.
- No network/model dependency.

## Table Schema

Table: `home_wiki_chunks`

Fields:

- `text`
- `vector`
- `asset_id`
- `source_type`
- `brand`
- `model`
- `normalized_model`
- `device_type`
- `room`
- `source_path`
- `markdown_path`
- `section_title`
- `chunk_index`
- `content_hash`
- `modified_at`
- `tags`

## Python Contract

```python
open_store(settings: Settings) -> LanceStore

index_chunks(
    chunks: list[IndexChunk],
    mode: Literal["append", "overwrite", "upsert"] = "append",
) -> IndexResult

delete_chunks_for_markdown_path(markdown_path: str) -> int

hybrid_search(
    query: str,
    filters: SearchFilters | None = None,
    limit: int = 8,
) -> list[SearchResult]
```

## Search Requirements

- Use LanceDB hybrid search: vector plus full-text.
- Use RRF reranking where supported.
- Exact model numbers and error codes must remain findable through FTS.
- If `asset_id` filter is provided, results must only include that `asset_id`.
- If `normalized_model` filter is provided, results must only include that model.
- Scalar indexes should be created for:
  - `asset_id`
  - `normalized_model`
  - `device_type`
  - `room`
  - `source_type`
  - `section_title`

## Implementation Requirements

- Build schema dynamically after embedding dimension is known.
- Ensure embedding registration happens before table open.
- Support small corpora without requiring vector index training.
- Create FTS index on `text`.
- Keep raw vectors out of API-facing search responses.
- Expose status with table name, row count, embedding provider, and db path.

## Error Handling

- Missing embedding provider config should fail clearly unless provider is `fake`.
- Model download/load errors should mention provider and model.
- Search against missing table should return a clear status/error, not a stack trace.

## Testing Strategy

### Deterministic Tests

- Use `EMBEDDING_PROVIDER=fake`.
- Index synthetic chunks for two devices.
- Search exact error code with `asset_id` filter.
- Search natural-language query with `asset_id` filter.
- Verify global search can return multiple devices.
- Verify filtered search never returns chunks outside the filter.
- Verify delete by markdown path removes rows.

### Optional Model Tests

Run only with `RUN_MODEL_TESTS=1`:

- Index/search using `local_gguf`.
- Index/search using `openai_compatible` endpoint if configured.

### LLM-Assisted Evaluation

Optional. Give the evaluator top search results for a fixture query. Expected result: evaluator says results are relevant and scoped to the requested device; it should fail if unrelated device chunks appear in a scoped search.

## Expected Scenario Results

### Scenario D1 - Synthetic Scoped Search

Chunks:

- Bosch dishwasher chunk: `E15 means water protection system activated.`
- ASUS router chunk: `Reset button restores factory settings.`

Query: `E15`, filter `asset_id=dishwasher-bosch-sms6zcw00g`.

Expected:

- Top results include only Bosch dishwasher chunks.
- Text includes `E15`.
- Router chunk is absent.

### Scenario D2 - Global Search

Query: `reset`.

Expected:

- Results may include router and appliance chunks.
- Response metadata identifies each source asset.

### Scenario D3 - Missing Provider Config

Input: `EMBEDDING_PROVIDER=openai_compatible` without model/base configuration.

Expected:

- Store initialization fails clearly.
- Error references missing embedding configuration.

## Acceptance Criteria

- LanceDB table can be created and searched with fake embeddings.
- Filtered hybrid search works.
- Optional local/LM Studio embedding paths are configurable without changing API contracts.

## Implementation Handoff Notes

This implementation lives in:

- `homewiki/embeddings.py`
- `homewiki/lancedb_store.py`
- `homewiki/gguf_embeddings.py`
- `tests/test_lancedb_store.py`

Coordination rule: downstream code should import payload and settings contracts from `homewiki.schemas` and `homewiki.config`. Do not redefine `IndexChunk`, `SearchFilters`, `SearchResult`, `IndexResult`, or settings shapes locally.

### Store Lifecycle

Use explicit settings when integrating:

```python
from homewiki.config import load_settings
from homewiki.lancedb_store import open_store

settings = load_settings()
store = open_store(settings)
```

`open_store(settings)` returns a `LanceStore` and also sets the module-level active store used by `index_chunks(...)`, `hybrid_search(...)`, `delete_chunks_for_markdown_path(...)`, and `get_status(...)`.

### Indexing Contract

`LanceStore.index_chunks(chunks, mode=...)` accepts `list[IndexChunk]` from `homewiki.schemas`.

Modes:

- `append`: adds rows to an existing table, or creates the table if missing.
- `overwrite`: recreates the table with a dynamically sized vector schema based on the configured embedding provider output.
- `upsert`: merges by `markdown_path` and `chunk_index`, replacing matching chunks and inserting new ones.

The table schema is built after vectors are generated so the vector field dimension matches the provider. For small corpora, no ANN vector index is required; LanceDB scans vectors directly while FTS and scalar indexes are present.

### Search Contract

`LanceStore.hybrid_search(query, filters=None, limit=8)` returns `list[SearchResult]` from `homewiki.schemas`; raw vectors are intentionally excluded.

Search uses:

- Explicit provider-generated query vector.
- LanceDB hybrid search over `vector` plus FTS `text`.
- RRF reranking via `lancedb.rerankers.RRFReranker`.
- SQL-style scalar prefilters for `asset_id`, `normalized_model`, `device_type`, `room`, and `source_type`.

Exact model numbers and error codes are preserved through the FTS side of hybrid search. Scoped searches must stay scoped; tests cover both `asset_id` and `normalized_model` filters.

### Provider Notes

`EMBEDDING_PROVIDER=fake` is deterministic and offline. It uses fixed-size lexical hashing vectors, which are suitable for tests but not semantic production search.

`EMBEDDING_PROVIDER=openai_compatible` posts to `{EMBEDDING_API_BASE}/embeddings` using the OpenAI embeddings response shape. `EMBEDDING_API_BASE` and `EMBEDDING_MODEL` are required; `EMBEDDING_API_KEY` is optional for local endpoints such as LM Studio.

`EMBEDDING_PROVIDER=local_gguf` imports `homewiki.gguf_embeddings` before constructing the LanceDB GGUF embedding function. `GGUF_MODEL_FILE` is required. `GGUF_MODEL_REPO` is required unless `GGUF_MODEL_FILE` is an existing local path or path-like value.

### Dependencies

Core search adds `lancedb>=0.30,<1` to project dependencies. Local GGUF support is optional under the `local-gguf` extra:

```bash
python -m pip install -e '.[local-gguf]'
```

### Status And Errors

`LanceStore.status()` and `get_status()` return table name, row count, embedding provider, and db path. A missing table reports `status="missing_table"` with a clear error string instead of exposing a LanceDB stack trace.

Missing provider configuration raises `EmbeddingConfigurationError`. Runtime embedding failures raise `EmbeddingProviderError`. LanceDB storage/search failures raise `LanceStoreError`.

### Verification

Offline verification uses the fake provider and does not need network or model files:

```bash
EMBEDDING_PROVIDER=fake python -m pytest tests/test_lancedb_store.py
```

The full local suite run used during implementation:

```bash
PYTHONPATH=/tmp/home-snitch-lancedb-deps:. python3 -m pytest
```
