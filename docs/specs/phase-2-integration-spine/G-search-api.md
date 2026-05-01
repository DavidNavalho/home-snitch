# G - Search API

## Summary

Expose device-resolved, metadata-filtered hybrid retrieval through an HTTP API. This is the main contract used by the UI and Ask API.

## Priority

P0. Start once F and D contracts are available. Can begin with mocks.

## Dependencies

- D - LanceDB Embedding/Search Foundation.
- F - Device Resolver.
- K fixtures.

## Can Run In Parallel With

E integration work, as long as mocked search results are available. H can start after the response contract stabilizes.

## Goals

- Resolve target device before retrieval.
- Search LanceDB with exact metadata filters when possible.
- Return ambiguity instead of guessing.
- Support explicit global fallback.
- Return evidence with source/section metadata.

## Non-Goals

- No answer generation.
- No frontend rendering.
- No document conversion/indexing.

## Files And Modules

- `homewiki/api.py`
- `homewiki/search_service.py`

## Endpoint

```text
POST /search
```

## Request

```json
{
  "query": "What does E15 mean on the dishwasher?",
  "asset_id": null,
  "filters": null,
  "limit": 8,
  "allow_global_fallback": true
}
```

## Response

```json
{
  "query": "What does E15 mean on the dishwasher?",
  "resolution": {
    "status": "exact",
    "asset_id": "dishwasher-bosch-sms6zcw00g",
    "confidence": 0.95,
    "matched_on": ["alias"],
    "candidates": [],
    "filters": {
      "asset_id": "dishwasher-bosch-sms6zcw00g"
    }
  },
  "scope": "device",
  "results": [
    {
      "source_path": "source_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/user-manual.pdf",
      "markdown_path": "markdown_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/user-manual.pdf.md",
      "section_title": "Troubleshooting > Error Codes",
      "asset_id": "dishwasher-bosch-sms6zcw00g",
      "source_type": "manual",
      "score": 0.82,
      "text": "..."
    }
  ]
}
```

## Search Flow

1. Validate request.
2. Call resolver with query and optional explicit `asset_id`.
3. If resolver status is `exact`:
   - use resolver filters;
   - search LanceDB;
   - response `scope=device`.
4. If resolver status is `ambiguous`:
   - return candidates and no results unless caller supplied explicit filters that resolve ambiguity.
5. If resolver status is `none`:
   - if `allow_global_fallback=true`, search globally and response `scope=global`;
   - otherwise return no results and `scope=none`.
6. Return results without raw vectors.

## Filter Rules

Precedence:

1. Explicit `asset_id`.
2. Resolver exact `asset_id`.
3. Explicit filters from request.
4. Global fallback if allowed.

Explicit `asset_id` must be validated. Invalid asset should not silently become global search.

## Error Handling

- Missing query returns validation error.
- Invalid limit returns validation error.
- LanceDB unavailable returns structured service error.
- Ambiguous resolution returns HTTP 200 with `resolution.status=ambiguous`, not HTTP error.

## Testing Strategy

### Deterministic Tests

- Exact model query returns device scope.
- Explicit asset ID scopes search.
- Ambiguous query returns candidates and empty/no results.
- No-match query with fallback returns global scope.
- No-match query without fallback returns none scope.
- Invalid asset ID returns validation/service error.
- Response serializes source and section metadata.

### LLM-Assisted Evaluation

Optional. Give evaluator a search request and response. Expected result: evaluator confirms response used the correct scope, did not include wrong-device evidence, and exposed ambiguity where appropriate.

## Expected Scenario Results

### Scenario G1 - Exact Scoped Search

Request:

```json
{
  "query": "E15 SMS6ZCW00G",
  "limit": 5,
  "allow_global_fallback": true
}
```

Expected:

- `resolution.status=exact`.
- `scope=device`.
- All results have `asset_id=dishwasher-bosch-sms6zcw00g`.
- Top result mentions `E15`.

### Scenario G2 - Ambiguous Dishwasher Query

Request:

```json
{
  "query": "dishwasher error code",
  "limit": 5,
  "allow_global_fallback": true
}
```

Expected:

- `resolution.status=ambiguous`.
- Candidates include Bosch and Siemens dishwasher fixtures.
- No generated answer is present because this is search only.
- Results are empty unless the design explicitly allows broad search while marking ambiguity; preferred MVP behavior is empty.

### Scenario G3 - Global Fallback

Request:

```json
{
  "query": "where is the admin URL documented?",
  "limit": 5,
  "allow_global_fallback": true
}
```

Expected:

- Resolver may return `none`.
- `scope=global`.
- Results may include router notes if they match.

### Scenario G4 - Fallback Disabled

Same as G3 with `allow_global_fallback=false`.

Expected:

- `scope=none`.
- Results empty.
- Response explains no device was resolved and fallback was disabled.

## Acceptance Criteria

- Search API always reports resolution and scope.
- Device-scoped results never include another device.
- Ambiguity is visible and machine-readable.

