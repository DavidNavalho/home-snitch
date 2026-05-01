# L - Orchestration Layer

## Summary

Add thin workflows that call the independently built blocks in sequence. The orchestrator should coordinate, not own core behavior.

## Priority

P2. Start after Phase 2 blocks are stable.

## Dependencies

- B - Device Profile Store.
- C - Document Conversion Lift.
- E - Markdown Chunking And Index Build.
- G - Search API.
- H - Ask API.
- I - Manual Find/Download, for manual acquisition workflows.

## Can Run In Parallel With

M, once Phase 2 is stable.

## Goals

- Provide convenient end-to-end workflows.
- Reuse public Python/CLI/API contracts from earlier packages.
- Keep each block independently runnable.
- Make workflow status visible.

## Non-Goals

- No new ingestion logic.
- No new search logic.
- No hidden model calls outside Ask API.
- No heavyweight agent framework until simple scripts are insufficient.

## Candidate Workflows

### Add Device And Manual

Steps:

1. Create/update device profile.
2. Find manual candidates.
3. Download selected/first manual.
4. Convert documents.
5. Build index.
6. Run a search smoke test for model number.

### Refresh Home Wiki

Steps:

1. Convert changed source docs.
2. Re-index changed Markdown.
3. Report changed/skipped/failed counts.
4. Report search index status.

### Troubleshooting Question

Steps:

1. Resolve device.
2. Search local wiki.
3. Ask from evidence.
4. If missing info, return missing information rather than online lookup in MVP.

## Files And Modules

- `homewiki/workflows.py`
- `scripts/workflow_add_device_manual.py`
- `scripts/workflow_refresh.py`
- optional `scripts/workflow_troubleshoot.py`

## CLI Contract

```bash
python scripts/workflow_refresh.py

python scripts/workflow_add_device_manual.py \
  --device-type dishwasher \
  --brand Bosch \
  --model SMS6ZCW00G \
  --room kitchen \
  --download-first
```

## Python Contract

```python
refresh_home_wiki() -> WorkflowResult

add_device_with_manual(
    profile: DeviceProfile,
    manual_url: str | None = None,
    download_first: bool = False,
) -> WorkflowResult

troubleshoot(question: str, asset_id: str | None = None) -> AskResponse
```

## Workflow Result

Fields:

- `workflow_name`
- `status: ok | partial | failed`
- `steps: list[WorkflowStepResult]`
- `outputs: dict`
- `errors: list`

Each step should include:

- `name`
- `status`
- `started_at`
- `finished_at`
- `summary`
- `details`

## Implementation Requirements

- Call existing public functions/scripts.
- Stop or continue based on explicit workflow policy.
- Persist enough status to diagnose failures.
- Do not swallow step-level errors.
- Keep workflows idempotent where practical.

## Error Handling

- If manual search fails, profile creation should still be visible as completed.
- If conversion fails for one file, index should either skip that file or stop based on policy.
- If smoke search fails, workflow status should be `partial` or `failed`, not `ok`.

## Testing Strategy

### Deterministic Tests

- Mock each block and verify workflow calls steps in order.
- Simulate manual search failure and verify partial status.
- Simulate conversion failure and verify error reporting.
- Run refresh workflow on fixtures with fake embeddings.

### LLM-Assisted Evaluation

Optional. Give evaluator workflow result JSON. Expected result: evaluator can identify which steps succeeded/failed and what the user should do next. It should fail if errors are hidden or status says `ok` despite a failed required step.

## Expected Scenario Results

### Scenario L1 - Refresh Workflow Success

Input: fixture source docs, fake embeddings.

Expected:

- Workflow status `ok`.
- Steps include convert and index.
- Outputs include indexed document/chunk counts.
- Search smoke test for `E15` passes if included.

### Scenario L2 - Manual Search Failure

Input: add device workflow with web search mocked to timeout.

Expected:

- Device profile step succeeds.
- Manual search step fails.
- Workflow status `partial`.
- No conversion/indexing of nonexistent manual is attempted unless other docs exist.

### Scenario L3 - Troubleshoot Missing Info

Input: question about warranty phone number absent from fixtures.

Expected:

- Workflow calls Ask API/service.
- Response says missing from home wiki.
- No online phone number is invented.

## Acceptance Criteria

- Workflows are thin and inspectable.
- Workflow results are structured.
- Individual blocks remain independently executable.

