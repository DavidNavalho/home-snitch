# C - Document Conversion Lift

## Summary

Adapt the document conversion approach from the SIBS project so home wiki source files become inspectable Markdown while preserving folder structure and device metadata.

## Priority

P0. Start after Phase 0 contracts.

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
- optional conversion report module/type from shared schemas

## CLI Contract

```bash
python scripts/docs_convert.py
python scripts/docs_convert.py --source source_docs --output markdown_docs
python scripts/docs_convert.py --force
python scripts/docs_convert.py --fail-fast
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
---
```

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

