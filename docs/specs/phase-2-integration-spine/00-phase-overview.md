# Phase 2 - Integration Spine

Phase 2 connects the independent Phase 1 pieces into the first end-to-end home wiki path: convert documents, index chunks into LanceDB, search with device scoping, and answer from retrieved evidence.

## Work Packages

- E - Markdown Chunking And Index Build
- G - Search API
- H - Ask API

## Can Start In Parallel

E can start once B, C, and D contracts are stable. G can start against mocked resolver/search services, then wire to F and D. H can start against mocked G responses, but should not generate answers until search behavior is settled.

## Exit Criteria

- Converted Markdown becomes LanceDB chunks with device metadata.
- Search API resolves device scope before retrieval.
- Ask API never answers without retrieval.
- Ambiguous device resolution is returned to UI instead of guessed.
- Evidence and sources are visible in API responses.

## Risks

- If chunk metadata is incomplete, scoped search cannot work reliably.
- If Ask bypasses Search, answers may be ungrounded.
- If ambiguous resolution is ignored, questions may be answered from the wrong device manual.

