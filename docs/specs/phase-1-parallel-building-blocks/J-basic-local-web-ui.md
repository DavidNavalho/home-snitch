# J - Basic Local Web UI

## Summary

Build a simple local web UI that talks only to the API. It must not import or call model, LanceDB, resolver, or ingestion modules directly.

## Priority

P1. Can start with mocked API responses after Phase 0 contracts.

## Dependencies

- A - Project Contracts And Config for API payload shapes.
- G/H API implementations later for real integration.

## Can Run In Parallel With

B, C, D, F, and I.

## Goals

- Provide a basic browser interface for devices, manuals, search, ask, and ingest.
- Keep UI separate from agents/models.
- Make search scope and ambiguity visible.
- Support mocked API development before backend is complete.

## Non-Goals

- No direct LanceDB access.
- No direct model API access.
- No complex frontend state framework requirement for MVP.
- No polished production design requirement.

## Files And Modules

- `ui/`
- optional frontend app package if using React/Vite
- optional static UI if keeping MVP simpler

## Views

### Devices

Capabilities:

- List devices.
- Add minimal device.
- Show brand/model/room/aliases.

API calls:

- `GET /devices`
- `POST /devices`

### Manuals

Capabilities:

- Select or enter a device.
- Find manual candidates.
- Download selected candidate.

API calls:

- `POST /manuals/find`
- `POST /manuals/download`

### Search

Capabilities:

- Enter query.
- Optional device selector.
- Show resolution status.
- Show snippets, sections, sources, and scope.

API calls:

- `POST /search`

### Ask

Capabilities:

- Enter question.
- Optional device selector.
- Show answer.
- Show citations/evidence.
- Show ambiguity instead of answer when returned by API.

API calls:

- `POST /ask`

### Ingest

Capabilities:

- Trigger ingest.
- Show counts and failures.

API calls:

- `POST /ingest`
- `GET /status`

## Implementation Requirements

- API base URL should be configurable.
- UI must be runnable separately from API where practical.
- UI must degrade gracefully when API is unavailable.
- Show whether a result is device-scoped or global.
- If response is ambiguous, show candidates and allow choosing one.
- Evidence must be visible for ask responses.
- Keep layout compact and utilitarian.

## Testing Strategy

### Deterministic Tests

- Render device list from mocked `GET /devices`.
- Submit device create form and verify request payload.
- Render ambiguous search response with candidate choices.
- Render scoped search response and snippets.
- Render ask response with evidence.
- Render API error state.

### Browser/Visual Tests

Optional once UI exists:

- Open local UI.
- Verify no text overlap at desktop and mobile widths.
- Verify forms are usable.

### LLM-Assisted Evaluation

Optional. Provide screenshots or DOM text to evaluator. Expected result: evaluator confirms UI exposes device scope, source evidence, and ambiguity clearly, and does not imply model/backend work happens in the UI.

## Expected Scenario Results

### Scenario J1 - API Offline

Input: open UI while API is not running.

Expected:

- UI loads.
- Status shows API unavailable.
- No blank page or uncaught exception.

### Scenario J2 - Ambiguous Ask

Mock API response: `resolution.status=ambiguous`, candidates Bosch and Siemens dishwashers.

Expected:

- UI does not show a generated answer.
- UI displays both candidate devices.
- User can choose a device for retry.

### Scenario J3 - Scoped Search Results

Mock API response: scoped Bosch dishwasher results.

Expected:

- UI shows scope as device-scoped.
- UI shows source path and section.
- UI shows snippet containing `E15`.

### Scenario J4 - Evidence Answer

Mock ask response with answer, sources, and evidence.

Expected:

- UI shows answer text.
- UI shows sources/evidence below answer.
- UI does not hide retrieval details.

## Acceptance Criteria

- UI only talks to API.
- UI can be developed/tested with mocked API.
- UI handles exact, ambiguous, none, and error states.

