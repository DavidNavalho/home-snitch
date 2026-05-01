# B - Device Profile Store

## Summary

Create, update, read, and list home device profiles. Store each profile both as editable files under `source_docs/` and as records in a fast local registry for lookup and resolver use.

## Priority

P0. Start after Phase 0 schema acceptance.

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

