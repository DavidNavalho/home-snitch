# H - Ask API

## Summary

Answer user questions from retrieved home wiki evidence. The Ask API must call the search service first and must never generate an answer without evidence.

## Priority

P1. Start after G response contract stabilizes.

## Dependencies

- G - Search API/Search Service.
- A - model provider config.
- K fixtures.

## Can Run In Parallel With

Late E/G work using mocked search responses. It should not be finalized until G behavior is accepted.

## Goals

- Retrieval-before-generation MVP.
- Configurable OpenAI-compatible chat provider.
- Evidence-only fallback when chat is disabled.
- Strict grounded-answer prompt.
- Clear behavior for ambiguity and missing evidence.

## Non-Goals

- No tool-calling agent loop in MVP.
- No direct LanceDB calls from Ask if Search service exists.
- No online repair lookup.
- No warranty inference unless evidence is indexed.

## Files And Modules

- `homewiki/ask_service.py`
- `homewiki/llm.py`
- `homewiki/prompts.py`
- `homewiki/api.py`

## Endpoint

```text
POST /ask
```

## Request

```json
{
  "question": "What does E15 mean on the dishwasher?",
  "asset_id": "dishwasher-bosch-sms6zcw00g",
  "limit": 8,
  "allow_global_fallback": false
}
```

## Response

```json
{
  "answer": "The Bosch dishwasher manual says E15 relates to ...",
  "resolution": {},
  "sources": [
    "markdown_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/user-manual.pdf.md"
  ],
  "evidence": [],
  "confidence": 7,
  "generated": true,
  "missing_information": []
}
```

## Ask Flow

1. Validate request.
2. Call Search service with the same question/asset/fallback settings.
3. If Search returns `ambiguous`:
   - return candidates;
   - do not call chat model.
4. If Search returns no evidence:
   - return missing information response;
   - do not call chat model.
5. If chat provider disabled:
   - return evidence-only response with `generated=false`.
6. If chat provider configured:
   - build prompt with question and evidence;
   - ask model to answer only from evidence;
   - return answer, sources, evidence, confidence.

## Prompt Requirements

System prompt must include:

- Use only provided home wiki evidence.
- Do not invent repair steps.
- Prefer exact model numbers and error codes.
- Cite source paths or filenames and sections.
- If evidence is insufficient, say what is missing.
- For safety-critical appliance issues, tell user to check the source manual before acting.
- Separate local evidence from missing information.

## Model Configuration

Provider:

```text
CHAT_PROVIDER=openai_compatible | disabled
CHAT_API_BASE=
CHAT_API_KEY=
CHAT_MODEL=
```

Generation should work with any compatible API that accepts chat-completions-style requests. Codex/OpenAI-compatible first; local providers can be tested later.

## Error Handling

- Chat model failure should return a structured error or evidence-only fallback depending on policy.
- Ambiguous search must not be converted into a best guess.
- Missing evidence should not call the chat model.
- Model output should be validated for non-empty answer and source references where practical.

## Testing Strategy

### Deterministic Tests

- Search ambiguous -> Ask returns candidates, `generated=false`.
- Search empty -> Ask returns missing information, `generated=false`.
- Chat disabled + evidence -> Ask returns evidence-only response.
- Mock chat model + evidence -> Ask returns generated answer with sources.
- Verify Ask calls Search before generation.
- Verify wrong-device evidence is not present when asset is explicit.

### Optional Model Tests

Run only with `RUN_MODEL_TESTS=1`:

- Use configured chat model against fixture evidence.
- Verify answer mentions expected error-code meaning and source.

### LLM-Assisted Evaluation

Recommended for generated answer quality. Evaluation prompt should compare answer to written expected result:

- Does the answer mention only facts present in evidence?
- Does it cite the expected source?
- Does it avoid unsupported repair steps?
- Does it surface missing information?

Expected evaluator result for fixture E15: pass only if answer says E15 is related to the dishwasher water protection/water in base evidence and does not invent detailed disassembly instructions.

## Expected Scenario Results

### Scenario H1 - Evidence-Only Mode

Input: question `What does E15 mean?`, asset `dishwasher-bosch-sms6zcw00g`, chat disabled.

Expected:

- Ask calls Search.
- Response `generated=false`.
- Evidence includes Bosch manual chunk.
- Answer summarizes or lists retrieved evidence.
- Sources include Bosch manual path.

### Scenario H2 - Generated Grounded Answer

Input: same as H1, chat configured.

Expected:

- Ask calls Search first.
- Response `generated=true`.
- Answer says E15 relates to water protection/water detected according to evidence.
- Answer cites Bosch manual source/section.
- Answer does not mention Siemens dishwasher.
- Answer does not invent warranty or repair phone number.

### Scenario H3 - Ambiguous Query

Input: `dishwasher error code`, no asset.

Expected:

- Search returns ambiguous.
- Ask does not call chat model.
- Response asks for device selection or returns candidates.

### Scenario H4 - Missing Evidence

Input: `What is the warranty phone number?`, selected Bosch dishwasher, no warranty info indexed.

Expected:

- Search may return weak/no evidence.
- Ask says the home wiki does not contain the warranty phone number.
- Does not invent a phone number.

## Acceptance Criteria

- Ask always goes through Search.
- Ask never generates on ambiguous/no-evidence paths.
- Generated answers are grounded and cite evidence.

