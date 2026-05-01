# E - Markdown Chunking And Index Build

## Summary

Turn converted Markdown and device profiles into LanceDB-ready chunks with complete metadata. This package integrates device metadata, conversion output, chunking, incremental indexing, and stale-row cleanup.

## Priority

P0. Start after B, C, and D contracts are usable.

## Dependencies

- B - Device Profile Store.
- C - Document Conversion Lift.
- D - LanceDB Embedding/Search Foundation.
- K fixtures.

## Can Run In Parallel With

G can begin against mocked search/store behavior. H can begin later against mocked G.

## Goals

- Chunk Markdown by headings.
- Preserve section breadcrumb context.
- Attach device metadata to every chunk.
- Index chunks into LanceDB.
- Re-index changed files and remove stale chunks.
- Provide a combined ingest command.

## Non-Goals

- No chat generation.
- No manual web search.
- No UI logic.

## Files And Modules

- `homewiki/chunking.py`
- `homewiki/ingest.py`
- `scripts/index_build.py`
- `scripts/ingest.py`

## CLI Contract

Index existing Markdown:

```bash
python scripts/index_build.py
python scripts/index_build.py --markdown markdown_docs --source source_docs --db lancedb_data
```

Convert and index:

```bash
python scripts/ingest.py
python scripts/ingest.py --force-convert
python scripts/ingest.py --force-index
```

## Python Contract

```python
split_markdown_document(
    markdown_path: Path,
    metadata: DocumentMetadata,
) -> list[IndexChunk]

build_index(
    markdown_root: Path,
    source_root: Path,
    store: LanceStore,
    force: bool = False,
) -> IngestReport

ingest_all(
    source_root: Path,
    markdown_root: Path,
    store: LanceStore,
    force_convert: bool = False,
    force_index: bool = False,
) -> IngestReport
```

## Chunking Requirements

- Split on Markdown headings `#` through `######`.
- Text before first heading becomes `Introduction`.
- Merge chunks shorter than configured minimum into neighboring chunks.
- Prefix or preserve parent heading context.
- Store `section_title` as breadcrumb, for example:

```text
Troubleshooting > Error Codes
```

- Fall back to paragraph/window chunking later if documents have poor headings. MVP can record low-heading quality warnings.

## Metadata Attachment Rules

For any file under:

```text
markdown_docs/devices/<asset_id>/...
```

Load:

```text
source_docs/devices/<asset_id>/profile.yaml
```

Attach:

- `asset_id`
- `brand`
- `model`
- `normalized_model`
- `device_type`
- `room`
- `tags`

Infer `source_type`:

- `profile.md` -> `profile`
- path contains `/manuals/` -> `manual`
- path contains `/notes/` -> `note`
- path contains `/receipts/` -> `receipt`
- otherwise -> `other`

## Incremental Indexing Requirements

- Compute content hash for each Markdown file.
- Store hash and chunk count in an ingest manifest.
- Skip unchanged files unless forced.
- On changed file:
  - delete existing chunks for `markdown_path`;
  - insert new chunks.
- On deleted Markdown file:
  - delete stale chunks.
- Report changed, skipped, failed, and removed counts.

## Error Handling

- Missing profile for a device path should produce a warning and either:
  - skip file, preferred for device-scoped docs; or
  - index with missing metadata only if explicitly allowed.
- Empty Markdown files should be skipped with warning.
- LanceDB insertion failure should include markdown path and chunk count.

## Testing Strategy

### Deterministic Tests

- Split fixture manual into expected section breadcrumbs.
- Attach metadata from fixture profile.
- Infer source type from path.
- Index fixture chunks with fake embeddings.
- Re-run indexing and verify unchanged files are skipped.
- Modify a file and verify old chunks are replaced.
- Delete a file and verify stale chunks are removed.

### LLM-Assisted Evaluation

Optional. Give evaluator original fixture Markdown and chunk list. Expected result: evaluator confirms chunks preserve troubleshooting/error-code context and do not mix unrelated devices.

## Expected Scenario Results

### Scenario E1 - Profile And Manual Index

Input:

- Bosch dishwasher `profile.yaml`
- Bosch dishwasher `profile.md`
- Bosch dishwasher manual Markdown containing `## Troubleshooting` and `### Error Codes`

Expected:

- Chunks indexed with `asset_id=dishwasher-bosch-sms6zcw00g`.
- Manual error-code chunk has section title containing `Troubleshooting > Error Codes`.
- `source_type` is `manual` for manual chunk and `profile` for profile chunk.

### Scenario E2 - Incremental Skip

Input: run `index_build` twice without changes.

Expected:

- First run indexes documents.
- Second run reports skipped unchanged documents.
- LanceDB row count does not double.

### Scenario E3 - Changed Manual

Input: modify manual text for `E15`.

Expected:

- Existing chunks for that manual are deleted/replaced.
- Search returns updated text, not stale text.

### Scenario E4 - Missing Profile

Input: Markdown under `markdown_docs/devices/unknown-device/manuals/manual.md` with no source profile.

Expected:

- Ingest report records warning or failure.
- No incorrectly scoped chunks are inserted for unknown asset by default.

## Acceptance Criteria

- Converted fixture docs become LanceDB rows with correct metadata.
- Incremental indexing is idempotent.
- Stale chunks are removed.
- Scoped search has the metadata it needs.

