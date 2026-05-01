# K - Fixtures And Smoke Tests

## Summary

Create deterministic fixtures and smoke tests that define expected behavior for every work package. These tests should guide implementation and prevent regressions.

## Priority

P0. Start immediately.

## Status

Started.

Implemented fixture/test files:

- `fixtures/source_docs/` for three deterministic device fixtures.
- `fixtures/markdown_docs/` for conversion/chunking/indexing contracts.
- `fixtures/web/` for manual-search and PDF-looking download fixtures.
- `fixtures/api/` for mocked API/UI/search/ask contracts.
- `fixtures/expected/scenarios.json` for expected results by work package.
- `scripts/run_smoke_tests.py` for offline smoke checks.
- `tests/test_fixtures_and_smoke.py` for a pytest wrapper around the smoke suite.

Now that A is available, the smoke runner validates fixture payloads against `homewiki.schemas` and `homewiki.config` when project dependencies are installed. Before dependencies are installed, that one shared-schema check is skipped and the bootstrap fixture checks still run.

## Dependencies

A - Project Contracts And Config for shared schemas and default settings.

## Can Run In Parallel With

A - Project Contracts And Config, and all Phase 1 work after contracts stabilize.

## Goals

- Provide fixture devices and documents.
- Define expected outcomes for resolver, conversion, chunking, indexing, search, ask, manual acquisition, and UI/API behavior.
- Keep default tests offline and deterministic.
- Add optional model/web tests behind explicit environment flags.

## Non-Goals

- No production implementation.
- No required live web calls.
- No required LLM calls.

## Fixture Layout

```text
fixtures/
  api/
    ask-evidence-only-bosch-e15.json
    devices-list.json
    search-ambiguous-dishwasher.json
    search-scoped-bosch-e15.json
  expected/
    scenarios.json
  markdown_docs/
    devices/
      ...
  source_docs/
    devices/
      dishwasher-bosch-sms6zcw00g/
        profile.yaml
        profile.md
        manuals/
          quick-manual.md
      dishwasher-siemens-sn23ec14cg/
        profile.yaml
        profile.md
        manuals/
          quick-manual.md
      router-asus-rt-ax88u/
        profile.yaml
        profile.md
        notes/
          admin-notes.md
  web/
    duckduckgo-manual-search.html
    manual.pdf
```

## Required Fixture Content

### Bosch Dishwasher

Profile:

- `asset_id`: `dishwasher-bosch-sms6zcw00g`
- `device_type`: `dishwasher`
- `brand`: `Bosch`
- `model`: `SMS6ZCW00G`
- `aliases`: `kitchen dishwasher`, `dishwasher`
- `room`: `kitchen`

Manual-like content must include:

- Section `Troubleshooting > Error Codes`
- Error `E15`
- Expected meaning: water protection system activated or water detected in base area.
- Expected safe guidance: turn off water supply/check manual/contact service; do not invent disassembly steps.

### Siemens Dishwasher

Profile:

- Different `asset_id`
- Same device type and alias pressure to test ambiguity.
- Manual-like content should include a different error code.

### ASUS Router

Profile:

- `asset_id`: `router-asus-rt-ax88u`
- Notes include admin URL and reset caution.

## Smoke Test Command

The eventual command should be one of:

```bash
pytest
python3 -m pytest
python3 scripts/run_smoke_tests.py
```

If model-dependent or web-dependent scenarios are included:

```bash
RUN_MODEL_TESTS=1 pytest
RUN_WEB_TESTS=1 pytest
RUN_NETWORK_TESTS=1 pytest
```

## Testing Strategy

### Deterministic Tests

- Device profile schema validation.
- Fixture/API payload validation against A shared schemas.
- Device resolver exact/ambiguous/none.
- Conversion from Markdown source to Markdown output.
- Chunking preserves heading breadcrumbs.
- LanceDB indexing with fake embeddings.
- Search filter by `asset_id`.
- API contract serialization.
- Ask endpoint evidence-only behavior with chat disabled.
- Manual finder parsing against stored HTML fixture.
- UI contract tests against mocked API responses.

### LLM-Assisted Evaluation

Optional evaluator workflow:

1. Run a completed script or API endpoint against fixture data.
2. Capture the output.
3. Ask Codex/LLM to compare output to the expected result written in this spec.
4. The evaluator must return `pass`, `fail`, or `needs-human-review`, with reasons.

LLM evaluation must not decide hidden requirements. It only checks whether implementation behavior matches the written expected results.

## Expected Scenario Results

### Scenario K1 - Exact Device Resolution

Input query: `What does E15 mean on SMS6ZCW00G?`

Expected:

- Resolver status: `exact`.
- Asset: `dishwasher-bosch-sms6zcw00g`.
- Matched on: includes `model`.
- Confidence: high, at least `0.9`.

### Scenario K2 - Ambiguous Device Resolution

Input query: `dishwasher error code`

Expected:

- Resolver status: `ambiguous`.
- Candidates include Bosch and Siemens dishwashers.
- No generated answer should be produced by ask flow until a device is selected, unless global fallback is explicitly requested.

### Scenario K3 - Scoped Search

Input query: `E15`, selected asset `dishwasher-bosch-sms6zcw00g`.

Expected:

- Results only include Bosch dishwasher chunks.
- Top result section includes `Troubleshooting` or `Error Codes`.
- Text mentions `E15`.

### Scenario K4 - Ask Evidence Only

Input question: `What does E15 mean on the dishwasher?`, selected Bosch dishwasher, chat disabled.

Expected:

- Response `generated=false`.
- Response includes retrieved evidence.
- Sources include the Bosch manual fixture.
- Answer does not claim unsupported repair steps.

### Scenario K5 - Manual Parser Fixture

Input: stored DuckDuckGo-like HTML fixture.

Expected:

- Candidate list includes a direct PDF URL.
- Candidate title includes brand/model/manual terms.
- No live web access required.

## Acceptance Criteria

- Fixture files exist.
- Offline tests can run on a clean machine after installing project test dependencies.
- Every work package has at least one fixture-backed expected result.
- Model/web tests are opt-in.
