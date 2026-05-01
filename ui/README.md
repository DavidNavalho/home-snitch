# Home Wiki UI

Static local web UI for the Home Wiki API contracts.

For implementation details and integration handoff notes, read
[HANDOFF.md](HANDOFF.md).

## Run

```bash
npm start --prefix ui
```

Open `http://127.0.0.1:5173/ui/`.

The UI starts in mock mode and uses fixture-shaped responses for devices,
search, ask, manuals, ingest, and API errors. Switch the header mode to `Live`
to call a running API. The bundled UI server imports `homewiki.config` and
serves `/ui-config.json`, so the API base follows `UI_API_BASE` and defaults to
the shared project config. It can also be set with
`?apiBase=http://127.0.0.1:8000&mode=live`.

## Test

```bash
npm test --prefix ui
```

Tests use Node's built-in test runner and the checked-in `fixtures/api/*.json`
files. The Python contract tests import `homewiki.schemas` and `homewiki.config`
to validate the same fixture payloads and config boundary. No model or LanceDB
package is imported by the UI.

If the default `python3` does not have the project dependencies installed, the
schema contract test is skipped by `npm test`. To force the full contract check,
run it with a project environment that has `requirements-dev.txt` installed:

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s ui/test -p '*_contracts.py'
```
