# Demo Readiness Specification

This document defines how the home wiki demo should work while the system is still being built. The demo must remain small, repeatable, and useful as features are added. It should show the product direction without depending on live web access, paid model calls, or unfinished integrations.

Live model provider modes for Codex CLI and LM Studio are specified separately in [Agent Provider Modes Specification](agent-provider-modes-spec.md).

## Purpose

The demo is a first-class project artifact. It is not a final presentation assembled at the end. It is a continuously maintained path that proves the current system can do something coherent.

The minimal demo should always be able to show:

1. The system knows about a few home devices.
2. The system has local manuals/notes for those devices.
3. A user can ask a troubleshooting question.
4. The system resolves the likely device.
5. The system searches only the correct device space when possible.
6. The system returns evidence and source sections.
7. The system refuses to guess when the device or evidence is ambiguous.

## Design Goals

- Always have an offline fixture-backed demo.
- Keep the demo stable while implementation changes behind it.
- Make retrieval behavior visible, not hidden behind chat.
- Make ambiguity and missing information visible.
- Keep UI separate from model/index internals.
- Allow new features to join the demo through additive scenario files or endpoints.
- Avoid rewriting the demo whenever a backend implementation changes.

## Non-Goals

- The demo is not a marketing landing page.
- The demo is not a full production workflow.
- The demo does not need live web search by default.
- The demo does not need chat generation by default.
- The demo does not need local model availability by default.

## Demo Layers

The demo has three layers. Each layer should keep working as later layers are added.

### Layer 1 - Fixture Demo

This is the always-ready baseline.

Required properties:

- No network.
- No LanceDB requirement if the search/index layer is not ready.
- No LLM requirement.
- Uses checked-in fixtures and mocked API responses.
- Demonstrates expected UX states.

Primary use:

- UI development.
- Contract validation.
- Early project demos.
- Regression checks when backend work is in progress.

### Layer 2 - Local Retrieval Demo

This proves the real local indexing/search path.

Required properties:

- Uses fixture source docs.
- Converts/indexes local documents.
- Uses LanceDB.
- Uses fake or local deterministic embeddings by default.
- Does not require chat generation.
- Demonstrates scoped retrieval.

Primary use:

- Validate B/C/D/E/F/G integration.
- Show that the answer evidence comes from indexed local files.

### Layer 3 - Full Assistant Demo

This proves retrieval-before-generation.

Required properties:

- Uses the real Search API.
- Uses configurable chat provider only when configured.
- Falls back to evidence-only mode when chat is disabled.
- Generated answers must cite local evidence.

Primary use:

- Validate H Ask API.
- Demonstrate chat value without hiding retrieval behavior.

## Separation Of Concerns

The demo must separate interface, runtime behavior, and reasoning expectations.

### Interface

Interface means stable inputs/outputs the demo can call or render:

- CLI commands.
- API endpoints.
- JSON fixture responses.
- UI routes/views.
- Scenario definitions.

Interface should change rarely. When it changes, update the demo spec and fixtures in the same change.

### Runtime Behavior

Runtime behavior means what implementation currently does behind the interface:

- Device registry implementation.
- Conversion implementation.
- LanceDB table implementation.
- Embedding provider.
- Resolver algorithm.
- Chat provider.

Runtime behavior can change as long as it preserves the interface and expected scenario results.

### Reasoning Expectations

Reasoning expectations define what the assistant or evaluator should conclude from evidence:

- Which device should be selected.
- Which chunks should be considered relevant.
- What answer is supported by evidence.
- What should be treated as missing.
- What should not be invented.

Reasoning expectations belong in scenario files and tests. They should not be hidden only in prompts.

## Stable Demo Interface

The current demo harness is runnable through a small set of stable commands.
Future convenience wrappers can be added, but these commands are the contract
for now.

### Reset Demo State

```bash
python scripts/demo_reset.py
```

Expected behavior:

- Clears generated demo runtime data.
- Does not delete checked-in fixtures.
- Does not delete user real data unless explicitly pointed at a demo workspace.

### Seed Demo State

```bash
python scripts/demo_seed.py
```

Expected behavior:

- Copies fixture source docs into a demo workspace.
- Creates fixture device profiles if needed.
- Leaves the workspace in a known state.

### Build Demo Index

```bash
python scripts/demo_check.py --mode retrieval
```

Expected behavior:

- Requires a seeded demo workspace.
- Converts fixture docs.
- Indexes fixture Markdown into LanceDB.
- Uses fake/local deterministic embeddings unless explicitly configured otherwise.
- Exercises the real search path.
- Exercises the Ask path with chat disabled and evidence-only responses.
- Reports indexed/skipped/failed counts as part of the check report.

There is currently no separate demo ingest command. If one is added later, it
should preserve the behavior above and be called by retrieval-mode checks.

### Check Demo

```bash
python scripts/demo_check.py --mode fixture
python scripts/demo_check.py --mode retrieval
```

Expected behavior:

- Fixture mode validates deterministic contracts and fixture payloads.
- Retrieval mode builds the demo index and runs real Search/Ask checks.
- Exits non-zero if the demo path is broken.

### Serve Demo UI

```bash
npm start --prefix ui
```

Expected behavior:

- Starts the local web UI at the configured UI port.
- Does not require external model configuration.
- Can render fixture responses before the API is running.

### Serve Demo API

```bash
set -a
source .demo/demo.env
set +a
python -m uvicorn homewiki.api:app --host 127.0.0.1 --port 8000
```

Expected behavior:

- Starts the real API against the seeded demo workspace.
- Does not require external model configuration.
- Uses `CHAT_PROVIDER=disabled` unless explicitly overridden.
- Includes CORS so the UI running on `127.0.0.1:5173` can call API endpoints.

A future wrapper may provide `python scripts/serve.py --demo`, but the wrapper
should only compose the UI/API commands above.

### Convenience Wrapper

Optional:

```bash
make demo
make demo-check
```

The wrapper should call the stable commands above. The commands are the contract; `make` is convenience.

## Stable Demo API Interface

The UI should be able to run against real API responses or fixture responses with the same shape.

### Current Real API Endpoints

```text
GET  /status
GET  /devices
POST /search
POST /ask
```

These are implemented by the real API and should remain stable for the UI.

### Planned Demo API Endpoints

```text
POST /devices
POST /ingest
POST /manuals/find
POST /manuals/download
```

For Layer 1, these can be represented by fixture JSON files under:

```text
fixtures/api/
```

For Layers 2 and 3, implemented endpoints should be served by the real API.
Unimplemented endpoints may stay fixture-backed until their work package lands.

### Demo Response Requirements

Every search and ask response must expose:

- resolution status;
- scope: `device`, `filtered`, `global`, or `none`;
- sources;
- evidence;
- ambiguity candidates when relevant;
- whether answer text was generated or evidence-only.

## Stable Demo UI Interface

The UI should have a small number of stable demo views.

### Devices View

Shows:

- Bosch dishwasher.
- Siemens dishwasher.
- ASUS router.
- Brand, model, room, aliases.

Demo requirement:

- User can see the difference between two dishwashers.

### Search View

Shows:

- Query input.
- Optional device selector.
- Resolution status.
- Search scope.
- Source path and section per result.
- Snippet/evidence text.

Demo requirement:

- User can see that `E15` results are scoped to Bosch when the device/model is known.

### Ask View

Shows:

- Question input.
- Optional device selector.
- Answer.
- Sources.
- Evidence.
- Ambiguity state.
- Missing-information state.

Demo requirement:

- User can see whether the answer is generated or evidence-only.

### Manuals View

Shows:

- Manual search fields or selected device.
- Candidate links.
- Download result.

Demo requirement:

- Layer 1 can render fixture candidates without live web.

### Ingest/Status View

Shows:

- Current demo mode.
- Number of devices/documents/chunks.
- Last ingest result.
- Failures or warnings.

Demo requirement:

- User can verify demo state before asking questions.

## Demo Scenarios

Scenarios define expected behavior. They are the heart of demo stability.

Scenario definitions live in a machine-readable file:

```text
fixtures/demo/scenarios.json
```

Each scenario should include:

- `id`
- `title`
- `layer`
- `request`
- `expected_resolution`
- `expected_scope`
- `expected_sources`
- `expected_evidence_terms`
- `forbidden_terms`
- `expected_ui_state`

## Required Scenarios

### DEMO-01 - Exact Device Troubleshooting

Question:

```text
What does E15 mean on SMS6ZCW00G?
```

Expected:

- Resolution status: `exact`.
- Asset: `dishwasher-bosch-sms6zcw00g`.
- Scope: `device`.
- Evidence source: Bosch dishwasher manual fixture.
- Evidence section includes `Troubleshooting > Error Codes` or equivalent.
- Evidence includes `E15`.
- Answer/evidence says E15 relates to water protection or water detected in base area.

Forbidden:

- Siemens dishwasher.
- Unsupported disassembly steps.
- Invented warranty or phone number.

### DEMO-02 - Alias-Based Device Troubleshooting

Question:

```text
What does E15 mean on the kitchen dishwasher?
```

Expected:

- Resolution status: `exact` if alias/room uniquely identifies Bosch fixture.
- Asset: `dishwasher-bosch-sms6zcw00g`.
- Scope: `device`.
- Evidence includes Bosch E15 manual section.

Fallback allowed:

- If resolver confidence is not high enough, UI may ask user to select the Bosch dishwasher. It must not answer from the wrong device.

### DEMO-03 - Ambiguous Device

Question:

```text
dishwasher error code
```

Expected:

- Resolution status: `ambiguous`.
- Candidates include Bosch and Siemens dishwashers.
- No generated answer.
- UI displays candidate devices.

Forbidden:

- Picking Bosch silently.
- Global answer presented as if device-specific.

### DEMO-04 - Missing Information

Question:

```text
What is the warranty repair phone number for the dishwasher?
```

Expected:

- If warranty phone number is absent from fixture docs, response says it is missing.
- Sources/evidence may show related profile/manual info if retrieved.
- Missing information includes warranty repair phone number.

Forbidden:

- Invented phone number.
- Vendor support guess from general knowledge.

### DEMO-05 - Router Note Retrieval

Question:

```text
Where is the router admin URL documented?
```

Expected:

- Resolution may be exact if query mentions ASUS/router alias, or global if no device is resolved and fallback is allowed.
- Evidence source: ASUS router notes fixture.
- Evidence includes `http://router.asus.com`.
- Answer/evidence includes reset caution if relevant.

### DEMO-06 - Manual Candidate Fixture

Action:

```text
Find manual for Bosch SMS6ZCW00G dishwasher.
```

Expected:

- Candidate list includes a direct PDF-looking fixture candidate.
- Candidate title includes Bosch, model, and manual terms.
- Layer 1 uses fixture HTML.
- No live web required.

## Demo Modes

The demo should expose its mode in status responses and UI.

### Fixture Mode

Mode ID:

```text
fixture
```

Behavior:

- Uses `fixtures/api/*.json`.
- Does not call real backend services.
- Suitable for UI-only demos.

### Retrieval Mode

Mode ID:

```text
retrieval
```

Behavior:

- Uses real device store, conversion, index, resolver, and search.
- Chat disabled.
- Ask returns evidence-only response.

### Assistant Mode

Mode ID:

```text
assistant
```

Behavior:

- Uses real retrieval.
- Uses configured chat provider.
- Ask returns generated answer only after retrieval.

## Adding New Features To The Demo

New features should extend the demo through additive contracts.

Preferred update pattern:

1. Add or update fixture data.
2. Add a scenario entry.
3. Add expected result terms and forbidden terms.
4. Add or update API fixture response if UI can show it before backend exists.
5. Add deterministic test coverage.
6. Wire real implementation later.

Avoid:

- Hardcoding UI behavior for one feature.
- Rewriting core demo commands.
- Replacing fixture mode with live dependencies.
- Making chat/model access mandatory.

## Demo Workspace

The demo should use a dedicated workspace separate from user data.

Suggested layout:

```text
.demo/
  source_docs/
  markdown_docs/
  lancedb_data/
  data/
```

`.demo/` should be gitignored.

Fixture source remains checked in under:

```text
fixtures/
```

Demo reset/seed commands copy from `fixtures/` into `.demo/`.

## Testing Guidance

### Deterministic Demo Tests

These should run without network, LLM, or local model server.

Current command:

```bash
python scripts/demo_check.py --mode fixture
```

Required checks:

- Fixture mode API payloads validate against shared schemas.
- Required scenarios exist.
- Expected fixture files exist.
- Search/ask fixture responses include required evidence and sources.
- Ambiguous response includes candidates and no answer.
- Missing-info response does not include forbidden invented values.
- UI can render fixture responses without API.

### Retrieval Demo Tests

These run once B/C/D/E/F/G are available.

Current command:

```bash
python scripts/demo_reset.py
python scripts/demo_seed.py
python scripts/demo_check.py --mode retrieval
```

Required checks:

- `demo_seed` creates demo workspace.
- `demo_check --mode retrieval` indexes fixture docs through `ingest_all`.
- Search for `E15 SMS6ZCW00G` returns only Bosch chunks.
- Search for `dishwasher error code` returns ambiguity.
- Search for router admin URL returns router notes.
- Re-running ingest is idempotent.

### Evidence-Only Ask Demo Tests

These run as part of retrieval mode and do not require a live model provider.

Required checks:

- Ask calls Search first.
- Exact E15 question returns Bosch evidence.
- Evidence-only answer avoids forbidden terms.
- Ambiguous device question does not call generation.
- Missing evidence returns missing-information state.

### Live Assistant Demo Tests

These run only when chat provider is configured.

Required checks:

- Ask calls Search first.
- Generated E15 answer cites Bosch manual evidence.
- Generated answer avoids forbidden terms.
- Ambiguous device question does not call generation.
- Missing warranty phone question does not invent phone number.

Use explicit flag:

```text
RUN_MODEL_TESTS=1
```

### Optional Live Web Tests

Manual finder live tests should be opt-in.

Use explicit flag:

```text
RUN_WEB_TESTS=1
```

Required checks:

- Live search returns at least one plausible manual candidate.
- Do not require exact URL because search results change.

## LLM-Assisted Evaluation

LLM-assisted evaluation can be useful for checking generated answers, but it is not the primary source of truth.

Evaluator input should include:

- scenario ID;
- question/action;
- expected terms;
- forbidden terms;
- actual response;
- actual evidence;
- sources.

Evaluator output must be one of:

- `pass`
- `fail`
- `needs-human-review`

The evaluator should fail if:

- answer contains forbidden terms;
- answer uses wrong device evidence;
- answer invents missing information;
- answer lacks required source citation;
- answer contradicts fixture evidence.

The evaluator should not introduce new requirements not present in the scenario.

## Demo Readiness Checklist

A feature is demo-ready when it has:

- fixture input;
- deterministic expected output;
- API or CLI interface;
- UI state or textual output;
- smoke test coverage;
- no mandatory live web access;
- no mandatory model access;
- documented failure/ambiguity behavior.

## Ownership By Work Package

Each work package should preserve the demo contract:

- B Device Store: create/list the fixture devices and support demo workspace paths.
- C Conversion: preserve headings, model numbers, error codes, source metadata.
- D LanceDB: support fake/local embeddings and device-scoped search.
- E Index Build: produce chunks with correct asset/source metadata.
- F Resolver: pass exact, ambiguous, and no-match demo scenarios.
- G Search API: expose resolution, scope, sources, and evidence.
- H Ask API: generate only after retrieval and preserve evidence-only mode.
- I Manual Find/Download: use fixture HTML/PDF without live web.
- J UI: render fixture responses and real API responses with the same components.
- L Orchestration: provide reset/seed/refresh/check workflows.

## Acceptance Criteria

- This spec is linked from the main specs index.
- Demo scenarios are fixture-first.
- Demo layers are additive and do not replace each other.
- The UI can be shown before backend completion through fixture mode.
- Retrieval and assistant demos can be added with minimal changes to UI and scenario contracts.
