# F - Device Resolver

## Summary

Identify the intended home device from a user query or explicit UI selection before search. This enables scoped semantic/keyword retrieval inside the correct device space.

## Priority

P0. Start after Phase 0 contracts. Can start before B is finished using fixture profiles.

## Dependencies

- A - Project Contracts And Config.
- B - Device Profile Store for production registry.
- K fixtures for early tests.

## Can Run In Parallel With

B, C, D, I, and J.

## Goals

- Resolve exact model references.
- Resolve unique aliases.
- Detect ambiguity instead of guessing.
- Return search filters for LanceDB.
- Prefer explicit `asset_id` from UI/API over inference.

## Non-Goals

- No LanceDB search.
- No answer generation.
- No device creation.

## Files And Modules

- `homewiki/resolver.py`
- `scripts/device_resolve.py`

## CLI Contract

```bash
python scripts/device_resolve.py "What does E15 mean on SMS6ZCW00G?"
python scripts/device_resolve.py "dishwasher error code"
python scripts/device_resolve.py --asset-id dishwasher-bosch-sms6zcw00g "E15"
```

## Python Contract

```python
resolve_device(
    query: str,
    asset_id: str | None = None,
    devices: list[DeviceProfile] | None = None,
) -> DeviceResolution
```

## Resolution Algorithm

1. If explicit `asset_id` is provided:
   - Validate it exists.
   - Return `exact` with confidence `1.0`.
2. Extract model-like tokens from query:
   - Alphanumeric strings containing digits.
   - Tokens with hyphens, underscores, slashes, or periods.
   - Normalize the same way as `normalized_model`.
3. Compare tokens against device `normalized_model`.
4. Score alias, brand, device type, and room matches.
5. Return:
   - `exact` if one candidate is clearly above threshold.
   - `ambiguous` if multiple candidates are close.
   - `none` if no candidate clears minimum threshold.

## Suggested Scoring

- Explicit asset ID: `1.0`.
- Exact normalized model: `0.95`.
- Model token plus brand: `0.98`.
- Unique alias plus device type: `0.85`.
- Unique alias only: `0.75`.
- Device type plus room: `0.65`.
- Brand only: below exact threshold.

Exact threshold: `>= 0.85` and top candidate gap at least `0.15`.

## Output Filters

Exact result:

```json
{
  "asset_id": "dishwasher-bosch-sms6zcw00g"
}
```

No result:

```json
{}
```

Ambiguous:

```json
{}
```

The search service decides whether to globally fallback.

## Error Handling

- Unknown explicit `asset_id` should return `none` or a validation error depending on caller context.
- Empty query with no asset should return `none`.
- Bad registry entries should be reported and skipped if possible.

## Testing Strategy

### Deterministic Tests

- Exact model match.
- Model match with punctuation/spacing variation.
- Explicit asset ID.
- Unique alias match.
- Ambiguous alias match across two dishwashers.
- No-match query.
- Brand-only query should not over-resolve.

### LLM-Assisted Evaluation

Optional. Provide resolver output for natural user phrases and ask whether the resolution is reasonable. Expected result: evaluator agrees exact model and explicit asset are exact; ambiguous general phrases remain ambiguous.

## Expected Scenario Results

### Scenario F1 - Exact Model

Query: `What does E15 mean on SMS 6ZCW-00G?`

Expected:

- Status: `exact`.
- Asset: `dishwasher-bosch-sms6zcw00g`.
- Matched on includes `model`.
- Confidence at least `0.9`.
- Filters include `asset_id`.

### Scenario F2 - Explicit Asset

Query: `E15`, asset ID: `dishwasher-bosch-sms6zcw00g`.

Expected:

- Status: `exact`.
- Confidence `1.0`.
- Query content does not need to mention brand/model.

### Scenario F3 - Ambiguous Dishwasher

Query: `dishwasher error code`.

Expected:

- Status: `ambiguous`.
- Candidates include Bosch and Siemens dishwasher fixtures.
- No `asset_id` filter returned.

### Scenario F4 - No Device

Query: `where is the stopcock?`

Expected:

- Status: `none`.
- Candidates empty or low-confidence only.
- Search service may choose global fallback if allowed.

## Acceptance Criteria

- Resolver is deterministic.
- Resolver can run without LanceDB or model clients.
- Ambiguity is surfaced cleanly.

## Implementation Handoff Notes

Current implementation lives in `homewiki/resolver.py` and `scripts/device_resolve.py`.

### Shared Contracts

- Resolver imports payload models from `homewiki.schemas`: `DeviceProfile`, `DeviceCandidate`, `DeviceResolution`, `ResolutionStatus`, and `SearchFilters`.
- Resolver imports path/settings helpers from `homewiki.config`.
- Do not redefine resolver payload shapes locally in callers. API, search, ask, and UI layers should pass/return the shared schema models or their `to_json_dict()` output.

### Runtime Entry Points

Python callers should prefer dependency injection:

```python
resolution = resolve_device(
    query="What does E15 mean on SMS 6ZCW-00G?",
    asset_id=None,
    devices=list_devices(),
)
```

The `devices=` argument is the handoff point for B - Device Profile Store. Once B has a registry-backed `list_devices()`, pass that list into `resolve_device` instead of relying on the temporary file loader.

If `devices` is omitted, `resolve_device` calls `load_device_profiles()`:

- First uses `HOME_WIKI_SOURCE_DOCS` from `homewiki.config` when it contains `devices/*/profile.yaml`.
- Falls back to `fixtures/source_docs` for offline fixture-driven development.
- Skips invalid profile files with a `RuntimeWarning` and continues resolving against valid profiles.

### CLI Behavior

The CLI outputs a serialized `DeviceResolution` JSON payload:

```bash
python scripts/device_resolve.py --source-docs fixtures/source_docs "dishwasher error code"
python scripts/device_resolve.py --source-docs fixtures/source_docs --asset-id dishwasher-bosch-sms6zcw00g "E15"
```

Use `--source-docs` in tests or fixture runs. Omit it in normal local runs once `HOME_WIKI_SOURCE_DOCS` points at the real source document tree.

### Resolution Semantics

- Explicit known `asset_id` returns `exact`, confidence `1.0`, matched on `asset_id`, and `filters.asset_id`.
- Unknown explicit `asset_id` returns `none`.
- Model references are normalized with `normalize_model_identifier` from `homewiki.schemas`; spaced/punctuated model variants such as `SMS 6ZCW-00G` match `sms6zcw00g`.
- Exact inferred resolution requires confidence `>= 0.85` and a top-candidate gap of at least `0.15`.
- Ambiguous and none results intentionally return empty search filters, so the search layer can decide whether and how to fall back globally.
- Brand-only matches stay below the candidate threshold and return `none`.

### Verification

Focused tests are in `tests/test_resolver.py` and cover exact model, punctuation variation, explicit asset ID, unique alias, ambiguous dishwasher, no match, brand-only, invalid profile skipping, and CLI JSON output.

Run:

```bash
python -m pytest tests/test_resolver.py
python -m pytest
```
