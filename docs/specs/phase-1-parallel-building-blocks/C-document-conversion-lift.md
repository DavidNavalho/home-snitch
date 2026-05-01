# C - Document Conversion Lift

## Summary

Adapt the document conversion approach from the SIBS project so home wiki source files become inspectable Markdown while preserving folder structure and device metadata.

## Priority

P0. Start after Phase 0 contracts.

## Status

Implemented for the MVP conversion path on branch/worktree:

- Branch: `document-conversion-lift`
- Worktree: `/private/tmp/home-snitch-document-conversion-lift`

Implemented files:

- `homewiki/conversion.py`
- `scripts/docs_convert.py`
- `tests/test_conversion.py`

Validation commands run in the worktree:

```bash
PYTHONPATH=/private/tmp/home-snitch-deps:. python3 -m pytest -q
PYTHONPATH=/private/tmp/home-snitch-deps:. python3 -m unittest discover -s tests
PYTHONPATH=/private/tmp/home-snitch-deps:. python3 -m compileall homewiki scripts tests
PYTHONPATH=/private/tmp/home-snitch-deps:. ./scripts/docs_convert.py --source fixtures/source_docs --output /private/tmp/home-snitch-converted-check --force --json
```

Current result:

- Full pytest suite: `22 passed`.
- Full unittest suite: `21 tests OK`.
- CLI fixture conversion: succeeds.

No required test path depends on live web access, LanceDB, embeddings, chat providers, or office/PDF conversion packages.

## Dependencies

- A - Project Contracts And Config.
- SIBS reference implementation at `/Users/jinx/gits/sibs/SIBS-LLMs/scripts/convert_docs_to_markdown.py`.

## Can Run In Parallel With

B, D, F, I, and J.

## Goals

- Convert supported files under `source_docs/` to Markdown under `markdown_docs/`.
- Preserve relative folder structure.
- Reuse SIBS conversion/cleanup where it makes sense.
- Keep Markdown visible and easy to inspect.
- Run independently from LanceDB and models.

## Non-Goals

- No vector indexing.
- No device resolution.
- No web download.
- No OCR in MVP unless a source PDF already has text extraction support.

## Supported Inputs

Required MVP:

- `.md`
- `.txt`
- `.pdf`
- `.csv`
- `.html`
- `.json`

Best-effort via `markitdown` or existing SIBS logic:

- `.doc`
- `.docx`
- `.xls`
- `.xlsx`
- `.ppt`
- `.pptx`
- `.xml`

## Files And Modules

- `homewiki/conversion.py`
- `scripts/docs_convert.py`
- `tests/test_conversion.py`

The implementation imports all payload/result shapes from `homewiki.schemas` and reads defaults through `homewiki.config`. It does not redefine schema payloads locally.

## CLI Contract

```bash
python scripts/docs_convert.py
python scripts/docs_convert.py --source source_docs --output markdown_docs
python scripts/docs_convert.py --force
python scripts/docs_convert.py --fail-fast
python scripts/docs_convert.py --json
```

## Python Contract

```python
convert_tree(
    source_root: Path,
    markdown_root: Path,
    force: bool = False,
    fail_fast: bool = False,
) -> ConversionReport
```

## Output Rules

Source:

```text
source_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/user-manual.pdf
```

Output:

```text
markdown_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/user-manual.pdf.md
```

Markdown files should include frontmatter when metadata is known:

```yaml
---
source_path: source_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/user-manual.pdf
source_type: manual
asset_id: dishwasher-bosch-sms6zcw00g
markdown_path: markdown_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/user-manual.pdf.md
---
```

## Current Implementation Notes

### Public Entry Points

- Python: `homewiki.conversion.convert_tree(source_root, markdown_root, force=False, fail_fast=False) -> ConversionReport`
- CLI: `scripts/docs_convert.py`

`scripts/docs_convert.py` uses `load_settings()` from `homewiki.config` when `--source` or `--output` are not supplied. This keeps the command aligned with A's environment contract.

### Source Discovery And Output Paths

`discover_files()` walks the source root recursively and only includes supported extensions. Unsupported files are ignored by discovery rather than reported as failed conversions.

Output paths preserve source tree shape:

- `.md` input keeps the same relative filename under `markdown_docs`.
- Non-Markdown input gets `.md` appended to the full source filename.

Examples:

```text
source_docs/devices/router-asus-rt-ax88u/notes/admin-notes.md
-> markdown_docs/devices/router-asus-rt-ax88u/notes/admin-notes.md

source_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/user-manual.pdf
-> markdown_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/user-manual.pdf.md
```

### Frontmatter

Every generated Markdown file gets deterministic frontmatter:

- `source_path`
- `source_type`
- `asset_id` when the path is under `devices/<asset_id>/...`
- `markdown_path`

`source_type` is inferred from path:

- `profile.md` -> `profile`
- path containing `manuals` -> `manual`
- path containing `notes` -> `note`
- path containing `receipts` -> `receipt`
- otherwise -> `other`

### Format Support

Implemented without required extra conversion dependencies:

- `.md`: copies/normalizes existing Markdown and strips any existing frontmatter before adding canonical Home Wiki frontmatter.
- `.txt`: wraps text with a generated title.
- `.csv`: renders a Markdown table using Python's stdlib `csv` module.
- `.json`: renders sorted, indented fenced JSON.
- `.html` / `.htm`: extracts visible text using Python's stdlib HTML parser and preserves headings/list items where practical.
- `.xml`: renders fenced XML.
- `.pdf`: first tries optional PyMuPDF (`fitz`) if installed, then a small text-stream fallback for simple text-based PDF fixtures, then optional `markitdown`.
- `.xls` / `.xlsx`: first tries optional pandas Excel loading and renders sheets as Markdown tables, then optional `markitdown`.

Best-effort optional support:

- `.doc`, `.docx`, `.ppt`, `.pptx` require the `markitdown` CLI in the current implementation.
- Native Excel conversion requires optional pandas plus the relevant engine (`openpyxl` for `.xlsx`, `xlrd` for `.xls`). These are intentionally not required by default.

### Incremental Behavior

By default, conversion skips a file when the output Markdown exists and is newer than or equal to the source file. `--force` reconverts regardless of timestamps.

### Failure Behavior

Failed conversions are recorded in `ConversionReport.files` as `FileConversionResult(status="failed", error=...)`. The run continues by default. With `fail_fast=True` or `--fail-fast`, conversion stops after the first failure and returns the partial report.

The CLI exits with:

- `0` when `report.failed == 0`
- `1` when any conversion failed

### Independence Boundaries

This package does not import or call LanceDB, embedding providers, chat providers, resolver code, API code, manual download code, or UI code.

## Handoff Notes For Later Packages

- E should consume `markdown_docs` output and can rely on canonical frontmatter being present on every converted file.
- E should still infer/load full device metadata from `source_docs/devices/<asset_id>/profile.yaml`; C only attaches path-level metadata and does not parse profile YAML.
- B can generate/update source `profile.md` files without needing to know conversion internals; C will copy them into `markdown_docs` with canonical frontmatter.
- I can download manuals into `source_docs/devices/<asset_id>/manuals/`; C will map those files into matching Markdown paths.
- G/H/J should not call conversion directly in request/response paths. Conversion remains a CLI/Python ingestion step.

## Implementation Requirements

- Preserve relative source tree.
- Skip unchanged files unless `force=true`.
- Copy or normalize existing `.md` files.
- Convert PDF text using the SIBS PyMuPDF-based cleanup where useful.
- Convert Excel sheets to Markdown tables using the SIBS approach.
- Fall back to `markitdown` for supported office formats.
- Return detailed failure records with source path and error.
- Do not require LanceDB, embeddings, or chat model config.

## Error Handling

- Unsupported file types are ignored or counted as skipped.
- Failed conversions are reported but do not stop the run unless `--fail-fast` is set.
- Empty extraction should be reported as warning/failed depending on file type.

## Testing Strategy

### Deterministic Tests

- Convert fixture Markdown and verify output path.
- Convert fixture text and verify title/body.
- Convert fixture CSV and verify Markdown table.
- Convert fixture JSON and verify fenced JSON block or readable Markdown.
- Convert a small text-based PDF fixture and verify extracted expected terms.
- Verify unchanged file is skipped on second run.
- Verify `--force` reconverts.

### LLM-Assisted Evaluation

Optional. Give the evaluator source text and converted Markdown for a manual section. Expected result: conversion preserves error codes, warnings, headings, and table content; evaluator should flag missing or garbled critical text.

## Expected Scenario Results

### Scenario C1 - Convert Device Profile Markdown

Input:

```text
source_docs/devices/dishwasher-bosch-sms6zcw00g/profile.md
```

Expected:

- Output exists at matching path under `markdown_docs`.
- Content still includes brand, model, room, and aliases.
- Conversion report increments copied or converted by one.

### Scenario C2 - Convert Manual PDF

Input:

```text
source_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/user-manual.pdf
```

Expected:

- Output `user-manual.pdf.md` exists.
- Markdown includes a title and extracted body text.
- If fixture contains `E15`, output includes `E15`.
- No LanceDB/model config is needed.

### Scenario C3 - Failed Legacy Doc

Input: unsupported or corrupt `.doc`.

Expected:

- Conversion report includes one failure.
- Other files continue converting unless `--fail-fast`.
- Failure includes source path and useful error text.

## Acceptance Criteria

- Conversion produces inspectable Markdown for fixture files.
- Folder structure is preserved.
- Conversion can run independently.
