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

