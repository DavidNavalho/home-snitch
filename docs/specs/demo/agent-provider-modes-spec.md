# Agent Provider Modes Specification

This document defines the planned live-model paths for Home Wiki answer generation and demo evaluation. It covers two preferred non-API-key-first paths:

1. Codex CLI using the user's ChatGPT/Codex login.
2. LM Studio using a local OpenAI-compatible server.

The goal is to make model-backed `/ask` and demo runs useful without making paid API usage mandatory.

## Current Position

Search and retrieval remain local and deterministic:

- device resolution;
- LanceDB retrieval;
- metadata filtering;
- evidence selection.

The model-backed layer should only run after retrieval has produced evidence. The provider should not decide which device to search, which chunks to retrieve, or whether ambiguity is acceptable. Those decisions stay in Home Wiki code.

## Product Requirement

The demo should support a real model-backed answer path, but default test/demo behavior must continue to work without any live model.

Provider priority for live demos:

1. `codex_cli` using the user's logged-in Codex CLI.
2. `lmstudio_openai` using LM Studio on localhost.
3. `openai_compatible` API provider later if explicitly configured.
4. `disabled` evidence-only mode as the default.

## Terminology

### Agent

In this project, "agent" means a model-backed answer or evaluation component operating over retrieved evidence. It does not mean the model is allowed to browse files, run arbitrary tools, choose a device, or query LanceDB directly.

### Retrieval

Retrieval means deterministic Home Wiki code:

- resolves device;
- applies filters;
- queries LanceDB;
- returns evidence chunks and sources.

### Generation

Generation means converting retrieved evidence into a user-facing answer. Generation must be evidence-constrained.

### Evaluation

Evaluation means judging whether a produced answer matches a written scenario expectation. Evaluation can use Codex during development, but deterministic checks should remain the first gate.

## Non-Goals

- Do not require OpenAI API billing for the minimal live demo.
- Do not make Codex CLI the only model path.
- Do not allow the model to repair, mutate, or inspect the repo during question answering.
- Do not let a model answer ambiguous device questions without user disambiguation.
- Do not use live web search for local Home Wiki answers.

## Provider Modes

### `disabled`

Default mode.

Behavior:

- `/ask` calls search.
- If evidence exists, returns evidence-only response.
- If evidence is missing, returns missing-information response.
- No model process or HTTP model endpoint is called.

Use for:

- CI.
- offline demo.
- debugging retrieval.
- deterministic tests.

### `codex_cli`

Uses the local `codex` command authenticated through the user's ChatGPT/Codex login.

Behavior:

- Home Wiki builds a strict prompt containing question, resolution, evidence, and answer schema.
- Home Wiki shells out to `codex exec`.
- Codex returns a structured JSON answer.
- Home Wiki validates the JSON and forbidden terms.

Use for:

- primary live demo model path;
- development evaluator;
- answer quality iteration without paid API endpoint setup.

Important constraint:

Codex CLI is a local development tool, not a stable production inference API. This provider should be marked demo/dev only.

### `lmstudio_openai`

Uses LM Studio's local OpenAI-compatible server, normally at:

```text
http://localhost:1234/v1
```

Behavior:

- Home Wiki uses an OpenAI-compatible chat client.
- Model is selected from the locally loaded LM Studio model list.
- `/ask` sends a strict evidence-only prompt.
- Response is validated the same way as Codex output.

Use for:

- local model experiments;
- privacy-sensitive demo mode;
- future local-only operation.

### `openai_compatible`

Generic OpenAI-compatible API mode.

Behavior:

- Same calling pattern as LM Studio.
- Requires explicit base URL, model, and credentials.

Use for:

- later API-backed operation if we choose to pay for or host a provider.

## Configuration Contract

The current config has `CHAT_PROVIDER=disabled | openai_compatible`. The planned extension should add:

```text
CHAT_PROVIDER=disabled | codex_cli | lmstudio_openai | openai_compatible
```

### Shared Generation Settings

```text
CHAT_TIMEOUT_SECONDS=90
CHAT_TEMPERATURE=0
CHAT_MAX_OUTPUT_TOKENS=1200
CHAT_REQUIRE_JSON=1
```

### Codex CLI Settings

```text
CODEX_CMD=codex
CODEX_MODEL=
CODEX_TIMEOUT_SECONDS=120
CODEX_WORKDIR=.demo/codex-runtime
CODEX_OUTPUT_SCHEMA=docs/schemas/home_wiki_answer.schema.json
CODEX_SANDBOX=read-only
```

`CODEX_MODEL` may be blank to use the user's Codex CLI default. If set, pass it through `codex exec -m`.

### LM Studio Settings

```text
LMSTUDIO_API_BASE=http://localhost:1234/v1
LMSTUDIO_API_KEY=lm-studio
LMSTUDIO_CHAT_MODEL=
LMSTUDIO_TIMEOUT_SECONDS=90
```

`LMSTUDIO_CHAT_MODEL` must match a model loaded or available in LM Studio.

### Generic OpenAI-Compatible Settings

```text
CHAT_API_BASE=
CHAT_API_KEY=
CHAT_MODEL=
```

## Provider Selection Rules

Provider selection should be explicit.

Recommended defaults:

```text
CHAT_PROVIDER=disabled
```

Live Codex demo:

```text
CHAT_PROVIDER=codex_cli
```

Live LM Studio demo:

```text
CHAT_PROVIDER=lmstudio_openai
LMSTUDIO_API_BASE=http://localhost:1234/v1
LMSTUDIO_CHAT_MODEL=<loaded-model-id>
```

Do not silently fall back from one live provider to another. If `codex_cli` fails, report a provider error. The user can then choose `disabled` or `lmstudio_openai`.

## Codex CLI Provider Spec

### Command Shape

The provider should call Codex non-interactively:

```bash
codex exec \
  --sandbox read-only \
  --ephemeral \
  --skip-git-repo-check \
  --json \
  --cd .demo/codex-runtime \
  --output-schema docs/schemas/home_wiki_answer.schema.json \
  -
```

If `CODEX_MODEL` is configured:

```bash
codex exec -m "$CODEX_MODEL" ...
```

### Working Directory

Use a dedicated minimal workdir:

```text
.demo/codex-runtime/
```

This directory should contain no source documents unless explicitly needed. The prompt should include the evidence directly. This reduces the chance that Codex reads repo files instead of answering from supplied evidence.

### Sandbox And Tool Policy

Required:

- `--sandbox read-only`
- `--ephemeral`
- `--json`
- `--skip-git-repo-check`
- no live web search flag;
- no write permissions.

Prompt requirement:

```text
Do not inspect files, run commands, browse the web, or use tools.
Answer only from the evidence in this prompt.
```

Even with that prompt, the CLI is still an agentic tool. The provider must validate output against the answer schema and forbidden terms.

### Authentication Check

Startup checks should verify:

```bash
codex --version
codex exec --json --ephemeral --sandbox read-only "Reply with OK only."
```

If the check fails due to auth, instruct the user to run:

```bash
codex login
```

### Output Contract

Codex must return JSON matching the Home Wiki answer schema:

```json
{
  "answer": "string",
  "sources": ["string"],
  "confidence": 0,
  "missing_information": ["string"],
  "safety_notes": ["string"]
}
```

The provider maps this into `AskResponse`.

### Failure Behavior

Failures should produce structured provider errors:

- command not found;
- not logged in;
- timeout;
- non-zero exit;
- invalid JSON;
- schema validation failure;
- answer contains forbidden terms.

For `/ask`, provider failure should not hide evidence. Preferred response:

- `generated=false`;
- answer explains provider failed;
- evidence and sources are still returned.

## LM Studio Provider Spec

### Server Requirement

LM Studio must be running as a local server. The common default is:

```text
http://localhost:1234/v1
```

LM Studio documents OpenAI-compatible endpoints including:

- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/embeddings`
- `POST /v1/responses`

### Health Check

Provider startup should call:

```bash
curl http://localhost:1234/v1/models
```

Expected:

- HTTP 200;
- at least one model listed;
- configured `LMSTUDIO_CHAT_MODEL` is present, or model is omitted and provider selects the first compatible loaded model only if explicitly allowed.

### Chat Request Shape

Use the OpenAI-compatible chat completions path first:

```text
POST /v1/chat/completions
```

Payload:

```json
{
  "model": "<LMSTUDIO_CHAT_MODEL>",
  "temperature": 0,
  "messages": [
    {"role": "system", "content": "<evidence-only system prompt>"},
    {"role": "user", "content": "<question + evidence + schema instructions>"}
  ]
}
```

The Responses endpoint can be evaluated later, but Chat Completions is simpler for first integration.

### Embeddings

Embeddings are separate from answer generation.

If we use LM Studio embeddings later:

```text
EMBEDDING_PROVIDER=openai_compatible
EMBEDDING_API_BASE=http://localhost:1234/v1
EMBEDDING_API_KEY=lm-studio
EMBEDDING_MODEL=<embedding-model-id>
```

Do not couple chat model success to embedding model success.

### Failure Behavior

Failures should produce structured provider errors:

- server unavailable;
- model not loaded;
- request timeout;
- invalid response shape;
- non-JSON answer when JSON required;
- schema validation failure.

For `/ask`, provider failure should return evidence-only fallback.

## Prompt Contract

Both live providers should use the same prompt semantics.

### System Prompt Requirements

The system prompt must say:

- You are a Home Wiki assistant.
- Answer only from provided evidence.
- Do not use general knowledge.
- Do not invent repair steps, warranty status, phone numbers, or support contacts.
- Prefer exact model numbers and error codes.
- Cite source paths and section titles.
- If evidence is insufficient, say what is missing.
- Return only JSON matching the schema.

### User Prompt Requirements

The user prompt should include:

- original question;
- device resolution result;
- search scope;
- evidence chunks with source path, section title, source type, and text;
- required answer schema;
- forbidden terms from scenario, when running a demo/test.

### Evidence Format

```text
Question:
What does E15 mean on SMS6ZCW00G?

Resolution:
status: exact
asset_id: dishwasher-bosch-sms6zcw00g
scope: device

Evidence:
--- Result 1 ---
Source: markdown_docs/devices/...
Section: Troubleshooting > Error Codes
Content:
...
```

## Ask Flow With Live Providers

1. Receive `AskRequest`.
2. Call `SearchService`.
3. If resolution is ambiguous:
   - do not call provider;
   - return candidates.
4. If evidence is empty:
   - do not call provider;
   - return missing-information response.
5. If `CHAT_PROVIDER=disabled`:
   - return evidence-only response.
6. If live provider is configured:
   - build prompt;
   - call provider;
   - validate structured output;
   - map to `AskResponse`.
7. If provider fails:
   - return evidence-only fallback with provider error noted.

## Demo Harness Modes

The implemented demo harness currently supports:

```bash
python scripts/demo_check.py --mode fixture
python scripts/demo_check.py --mode retrieval
```

Retrieval mode builds the fixture LanceDB index and exercises `/ask` through
`AskService` with `CHAT_PROVIDER=disabled`. The live provider modes below are
planned extensions for generated answers and optional model evaluation.

### Deterministic Mode

```text
DEMO_AGENT_MODE=disabled
```

No live model. Must always pass offline.

### Codex Mode

```text
DEMO_AGENT_MODE=codex_cli
CHAT_PROVIDER=codex_cli
```

Uses Codex CLI for generated answers or evaluator runs.

### LM Studio Mode

```text
DEMO_AGENT_MODE=lmstudio_openai
CHAT_PROVIDER=lmstudio_openai
```

Uses LM Studio local server.

## Testing Strategy

### Deterministic Tests

No live provider required.

Required:

- prompt builder includes question, resolution, evidence, sources, and schema;
- ambiguous resolution does not call provider;
- no evidence does not call provider;
- provider failure returns evidence-only fallback;
- malformed provider JSON is rejected;
- forbidden terms are detected.

### Codex CLI Optional Tests

Run only when explicitly enabled:

```text
RUN_CODEX_TESTS=1
CHAT_PROVIDER=codex_cli
```

Tests:

- `codex --version` succeeds;
- Codex smoke prompt returns schema-valid JSON;
- E15 fixture answer mentions water protection/base area;
- answer cites Bosch manual source;
- answer does not mention Siemens;
- answer does not invent phone numbers or disassembly steps.

### LM Studio Optional Tests

Run only when explicitly enabled:

```text
RUN_LMSTUDIO_TESTS=1
CHAT_PROVIDER=lmstudio_openai
LMSTUDIO_CHAT_MODEL=<loaded-model-id>
```

Tests:

- `GET /v1/models` succeeds;
- configured model is present;
- simple JSON response smoke test succeeds;
- E15 fixture answer matches expected terms;
- missing warranty phone scenario refuses to invent a phone number.

### Provider Comparison Test

Optional manual/demo check:

Run the same retrieved evidence through both providers and compare:

- required terms;
- forbidden terms;
- source citations;
- confidence;
- missing information.

The expected output does not need identical wording.

## Demo Scenarios For Live Providers

### LIVE-01 - Codex E15 Answer

Provider:

```text
codex_cli
```

Question:

```text
What does E15 mean on SMS6ZCW00G?
```

Expected:

- search resolves Bosch dishwasher exactly;
- provider is called;
- generated answer mentions water protection or water in base area;
- sources include Bosch manual;
- forbidden terms absent.

### LIVE-02 - Codex Ambiguous Query

Question:

```text
dishwasher error code
```

Expected:

- search returns ambiguous;
- provider is not called;
- response asks for device selection or returns candidates.

### LIVE-03 - LM Studio E15 Answer

Same as LIVE-01, but provider is `lmstudio_openai`.

Expected:

- output may be less polished than Codex;
- schema must still validate;
- required/forbidden terms still apply.

### LIVE-04 - Missing Warranty Phone

Question:

```text
What is the warranty repair phone number for the dishwasher?
```

Expected:

- if evidence does not contain phone number, answer says missing;
- no invented phone number;
- `missing_information` includes warranty repair phone number.

## Security And Safety

### Codex CLI

- Run with read-only sandbox.
- Use a minimal workdir.
- Do not pass live web search.
- Do not pass secrets in prompts.
- Do not allow command approvals.
- Treat output as untrusted until schema validation passes.

### LM Studio

- Assume local server can see prompts.
- Do not expose LM Studio server on the network for demo unless explicitly needed.
- Do not send secrets in prompts.
- Validate output.

## Documentation References

- OpenAI Help: [Using Codex with your ChatGPT plan](https://help.openai.com/en/articles/11369540)
- OpenAI Help: [Codex CLI and Sign in with ChatGPT](https://help.openai.com/en/articles/11381614-codex-cli-and-sign-in-withgpt)
- OpenAI Help: [Billing settings in ChatGPT vs Platform](https://help.openai.com/en/articles/9039756)
- LM Studio Docs: [Local LLM API Server](https://lmstudio.ai/docs/developer/core/server)
- LM Studio Docs: [OpenAI Compatibility Endpoints](https://lmstudio.ai/docs/developer/openai-compat/)
- LM Studio Docs: [Chat Completions](https://lmstudio.ai/docs/developer/openai-compat/chat-completions)
- LM Studio Docs: [Embeddings](https://lmstudio.ai/docs/developer/openai-compat/embeddings)

## Implementation Notes For Future Work

Likely files:

- `homewiki/agent_providers.py`
- `homewiki/prompts.py`
- `homewiki/ask_service.py`
- `tests/test_agent_providers.py`
- `tests/test_ask_service.py`

Potential schema/config updates:

- add `codex_cli` and `lmstudio_openai` to `ChatProvider`;
- add provider-specific settings to `config.py`;
- add an answer output schema file for Codex CLI `--output-schema`;
- add optional provider tests behind explicit environment flags.

## Acceptance Criteria

- The plan supports Codex CLI first without OpenAI API billing.
- The plan supports LM Studio as a second live model path.
- Default mode remains deterministic and offline.
- Both live providers are evidence-constrained.
- Ambiguous/no-evidence paths do not call live providers.
- Live-provider failures degrade to evidence-only responses.
