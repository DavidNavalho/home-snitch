# B - Device Profile Store

## Summary

Create, update, read, and list home device profiles. Store each profile both as editable files under `source_docs/` and as records in a fast local registry for lookup and resolver use.

## Priority

P0. Start after Phase 0 schema acceptance.

## Status

Implemented in branch/worktree:

- Branch: `device-profile-store`
- Worktree: `/Users/jinx/gits/home-snitch-device-profile-store`

Implemented files:

- `homewiki/devices.py`
- `scripts/device_add.py`
- `scripts/device_list.py`
- `tests/test_devices.py`

Validation commands run:

```bash
PYTHONPATH=/private/tmp/home-snitch-device-profile-store-deps python3 -m pytest -q
PYTHONPATH=/private/tmp/home-snitch-device-profile-store-deps python3 -m unittest discover -s tests
PYTHONPATH=/private/tmp/home-snitch-device-profile-store-deps python3 -m compileall -q homewiki scripts tests
```

The active Python environment did not have `pydantic` or `pytest`, so dev
dependencies were installed outside the repo at
`/private/tmp/home-snitch-device-profile-store-deps`.

## Dependencies

- A - Project Contracts And Config.
- K fixtures are useful but not required.

## Can Run In Parallel With

C, D, F, I, and J. F may use fixture profiles while B is in progress.

## Goals

- Provide a stable source of device metadata.
- Generate a human-readable `profile.md` for indexing.
- Maintain a queryable registry for fast listing and resolution.
- Preserve user-entered metadata during updates.

## Non-Goals

- No LanceDB indexing.
- No manual web search.
- No chat or answer generation.

## Files And Modules

- `homewiki/devices.py`
- `scripts/device_add.py`
- `scripts/device_list.py`
- `source_docs/devices/<asset_id>/profile.yaml`
- `source_docs/devices/<asset_id>/profile.md`
- `data/devices.sqlite` or `data/devices.json`

SQLite is preferred for the registry because it supports simple uniqueness constraints and future API filtering. YAML remains the human-editable source of truth.

## Handoff Notes For Dependent Work

- Do not redefine device payloads locally. Import `DeviceProfile`,
  `RegistrySyncResult`, `ErrorResponse`, and related payload types from
  `homewiki.schemas`.
- Do not hard-code repo-relative paths. Use `load_settings()` from
  `homewiki.config`; device files live under
  `settings.paths.source_docs / "devices"` and the registry lives at
  `settings.paths.device_registry`.
- YAML remains the editable source of truth. The SQLite registry is a fast local
  lookup copy maintained by `upsert_device()` and `sync_registry_from_files()`.
- `device_list.py` calls `sync_registry_from_files()` before listing, so newly
  added `source_docs/devices/*/profile.yaml` files become visible without a
  separate sync command.
- `profile.md` is generated beside `profile.yaml` in `source_docs`; later
  conversion/indexing work can copy or transform it into `markdown_docs`.
- Duplicate `asset_id` updates the existing registry row. Duplicate
  `normalized_model` values across different asset IDs are allowed and reported
  as `ErrorResponse(code="duplicate_normalized_model")` in
  `RegistrySyncResult.errors`.

## Data Rules

### Asset ID

Format:

```text
<device_type>-<brand>-<model>
```

Normalized to lowercase slug form:

```text
dishwasher-bosch-sms6zcw00g
```

Rules:

- Use only lowercase letters, numbers, and hyphens.
- Collapse repeated hyphens.
- Keep stable after creation unless the user explicitly renames the asset.

### Normalized Model

Input examples:

- `SMS6ZCW00G`
- `SMS 6ZCW 00G`
- `SMS-6ZCW-00G`

All normalize to:

```text
sms6zcw00g
```

Rules:

- Lowercase.
- Remove spaces, hyphens, underscores, slashes, and punctuation.
- Preserve letters and digits.

## CLI Contract

Create or update:

```bash
python scripts/device_add.py \
  --device-type dishwasher \
  --brand Bosch \
  --model SMS6ZCW00G \
  --room kitchen \
  --alias "kitchen dishwasher" \
  --tag appliance
```

List:

```bash
python scripts/device_list.py
python scripts/device_list.py --json
```

## Python Contract

```python
upsert_device(profile: DeviceProfile) -> DeviceProfile
get_device(asset_id: str) -> DeviceProfile | None
list_devices() -> list[DeviceProfile]
load_profile(profile_path: Path) -> DeviceProfile
render_profile_markdown(profile: DeviceProfile) -> str
sync_registry_from_files() -> RegistrySyncResult
```

All functions accept an optional keyword-only `settings: Settings | None` in the
implementation for tests and controlled callers. Omit it in normal CLI/runtime
usage to load shared environment configuration.

Additional implemented helper:

```python
generate_asset_id(device_type: str, brand: str, model: str) -> str
```

This helper follows the asset ID rules in this spec and uses
`normalize_model_identifier()` from `homewiki.schemas` for the model segment.

## Implementation Notes

### YAML

The implementation uses a deliberately small YAML subset so the project does
not need a new runtime dependency:

- Top-level `key: value` scalar fields.
- Top-level lists using `key:` followed by `  - value` items.
- Blank scalar values load as `None`.
- Empty `aliases:` and `tags:` load as empty lists.
- Unknown top-level YAML fields are preserved when `upsert_device()` rewrites an
  existing profile file.

Unsupported YAML syntax is reported as `invalid_profile` during sync, and sync
continues with other profiles.

### Registry

The registry is SQLite at `settings.paths.device_registry` and is created on
first write or sync. The `devices` table stores one row per `asset_id`, with
JSON-encoded `aliases` and `tags` columns and indexes for
`normalized_model` and `room`.

The registry schema is an implementation detail for this package. Other modules
should call `get_device()`, `list_devices()`, or `sync_registry_from_files()`
instead of querying SQLite directly unless they are explicitly adding a storage
adapter.

### Error Handling

- `DeviceProfile` validation failures come from `homewiki.schemas`.
- `load_profile()` raises `DeviceProfileParseError` for unsupported YAML or
  invalid profile data.
- Registry read/write failures raise `DeviceRegistryError`.
- `sync_registry_from_files()` returns `RegistrySyncResult` and records bad
  profile files in `errors` while continuing with valid files.
- `device_add.py` validates before writing, so invalid dates such as
  `30-99-2026` fail without creating partial profile files.

## Implementation Requirements

- Create the device directory if missing.
- Write `profile.yaml` atomically where practical.
- Generate `profile.md` from the same structured data.
- Keep `profile.md` deterministic so diffs are useful.
- Preserve unknown YAML fields if possible, or document that unsupported fields are dropped.
- Registry updates must be idempotent.
- Duplicate `asset_id` should update the existing profile.
- Duplicate normalized model across different devices should be allowed but flagged for resolver ambiguity.

## Error Handling

- Missing required fields should return validation errors.
- Invalid dates should fail validation.
- A registry write failure should not silently leave files and registry inconsistent; return an error with affected paths.
- If YAML exists but is invalid, list/sync should report the bad file and continue with others when possible.

## Testing Strategy

### Deterministic Tests

- Generate asset IDs from varied brand/model inputs.
- Normalize model strings.
- Create a profile and verify both YAML and Markdown are written.
- Re-run create with updated room/alias and verify update is idempotent.
- Sync registry from existing profile files.
- List devices from registry.
- Validate duplicate normalized model behavior.

### LLM-Assisted Evaluation

Optional. Give the evaluator a generated `profile.md` and ask whether it contains enough human-readable information to be useful in retrieval. Expected result: the evaluator should find brand, model, aliases, room, warranty fields, and notes clearly represented without inventing extra facts.

## Expected Scenario Results

### Scenario B1 - Add Bosch Dishwasher

Input CLI:

```bash
python scripts/device_add.py --device-type dishwasher --brand Bosch --model SMS6ZCW00G --room kitchen --alias "kitchen dishwasher"
```

Expected:

- Creates `source_docs/devices/dishwasher-bosch-sms6zcw00g/profile.yaml`.
- Creates `source_docs/devices/dishwasher-bosch-sms6zcw00g/profile.md`.
- Registry contains one row for `dishwasher-bosch-sms6zcw00g`.
- `normalized_model` is `sms6zcw00g`.

### Scenario B2 - Idempotent Update

Input: same command plus `--warranty-until 2028-04-30`.

Expected:

- Same `asset_id`.
- Existing profile updated.
- No duplicate registry rows.
- `profile.md` includes warranty date.

### Scenario B3 - Invalid Date

Input: `--purchase-date 30-99-2026`.

Expected:

- Command exits non-zero.
- No partial invalid profile is written.
- Error message identifies `purchase_date`.

## Acceptance Criteria

- Device profiles are file-backed and registry-backed.
- Profile Markdown is generated and suitable for indexing.
- All deterministic tests pass offline.
