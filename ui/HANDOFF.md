# Basic Local Web UI Handoff

This package implements work item J, Basic Local Web UI. It is intentionally
limited to browser/UI concerns and should remain independent from retrieval,
model, ingestion, and vector database implementations.

## Current Status

- Branch/worktree used for this slice: `ui-basic-local-web-ui` at
  `/Users/jinx/gits/home-snitch-ui`.
- Write scope used: `ui/` only.
- The UI is a static browser app served by a small Python server.
- The app can run without the API by using mock mode.
- Live mode talks only to HTTP API endpoints.
- No UI source imports model, LanceDB, resolver, ingestion, search service, or
  ask service modules.

## File Map

- `ui/index.html`: browser entry point.
- `ui/styles.css`: compact utilitarian layout and responsive styling.
- `ui/server.py`: local static server. Imports `homewiki.config.load_settings`
  and exposes `/ui-config.json`.
- `ui/src/app.js`: UI state, event handlers, form submission, tab switching.
- `ui/src/api.js`: API client. Switches between mock fixture responses and live
  HTTP calls.
- `ui/src/fixtures.js`: fixture loader helpers. It maps stable fixture keys to
  canonical files under `/fixtures/api/*.json`; it must not copy those payloads.
- `ui/src/render.js`: HTML render helpers for devices, resolution, ambiguity,
  search results, ask evidence, manuals, ingest, and errors.
- `ui/src/device.js`: small form helpers for client-side device create payloads.
- `ui/test/ui.test.js`: deterministic Node tests for rendering and client
  behavior.
- `ui/test/schema_contracts.py`: Python contract tests. Imports
  `homewiki.schemas` and `homewiki.config`.

## Contract Boundary

Follow the coordination rule for all future UI work:

- Use `homewiki.config` for shared configuration. The UI server already does
  this and serves the configured API base at `/ui-config.json`.
- Use `homewiki.schemas` for payload contracts. The Python contract tests
  validate checked-in API fixtures against the shared Pydantic schemas.
- Do not copy canonical API payloads into JavaScript source. Add or update
  root-level `fixtures/api/*.json` payloads when new scenarios are needed, then
  load them through `ui/src/fixtures.js`.
- Browser code cannot import Python modules directly. Keep schema enforcement in
  Python tests and keep browser code consuming JSON over HTTP or fixture files.
- The UI must call API endpoints over HTTP in live mode. It must not import
  backend implementation modules.

## Mock Mode

Mock mode is the default so the UI remains usable before the API is running.

- Devices load from `fixtures/api/devices-list.json`.
- Scoped search loads from `fixtures/api/search-scoped-bosch-e15.json`.
- Ambiguous search loads from `fixtures/api/search-ambiguous-dishwasher.json`.
- Ask evidence loads from `fixtures/api/ask-evidence-only-bosch-e15.json`.
- API error rendering uses `fixtures/api/api-error.json`.

The mock client also derives a few scenario variants from those canonical
fixtures, for example changing the query text or selected `asset_id`. This is
only for UI interaction coverage. If another package adds canonical fixtures for
manuals, ingest, status, global search, or alternate devices, replace the
derived mock responses with fixture loads and extend `schema_contracts.py`.

## Live Mode

The header has a Mode selector. In `Live` mode, `ui/src/api.js` calls:

- `GET /devices`
- `POST /devices`
- `POST /manuals/find`
- `POST /manuals/download`
- `POST /search`
- `POST /ask`
- `POST /ingest`
- `GET /status`

The API base defaults to `UI_API_BASE` from `homewiki.config`, currently
`http://127.0.0.1:8000`. It can be overridden with the header form or with:

```text
http://127.0.0.1:5173/ui/?mode=live&apiBase=http://127.0.0.1:8000
```

## User Flows Covered

- Devices: list fixture devices, submit a minimal device create payload, show
  the exact JSON request sent.
- Search: submit a query, optionally select a device, show resolution status,
  scope, snippets, source paths, sections, scores, and ambiguity candidates.
- Ask: submit a question, optionally select a device, show answer, generated
  flag, confidence, citations, evidence, and missing information. Ambiguous ask
  shows candidates and does not show an answer.
- Manuals: find candidates and submit a candidate download request.
- Ingest: run ingest and display counts, warnings, errors, and status.

## Test Commands

Run the UI test suite:

```bash
npm test --prefix ui
```

Run the schema/config contract checks with a Python environment that has project
dependencies installed:

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s ui/test -p '*_contracts.py'
```

In this workspace, the existing original checkout virtualenv can run the full
contract check:

```bash
/Users/jinx/gits/home-snitch/.venv/bin/python -m unittest discover -s ui/test -p '*_contracts.py'
```

## Safe Resume Notes

- Keep new UI files under `ui/`.
- Add root `fixtures/api/*.json` scenarios before adding new mock payload
  shapes.
- Extend `ui/test/schema_contracts.py` whenever a new fixture-backed response
  type is introduced.
- If backend routes change, update `ui/src/api.js` endpoint paths and tests
  together.
- If `homewiki.schemas` adds a first-class status contract, update the status
  mock and contract tests to use it.
- If canonical manual or ingest fixtures land, replace the temporary derived
  mock responses in `ui/src/api.js` with fixture loads.

