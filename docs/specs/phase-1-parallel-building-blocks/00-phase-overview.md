# Phase 1 - Parallel Building Blocks

Phase 1 builds independent components behind the Phase 0 contracts. These packages should be runnable on their own and should not depend on the full end-to-end application being complete.

## Work Packages

- B - Device Profile Store: implemented in branch `device-profile-store`; see
  `B-device-profile-store.md` for handoff notes.
- C - Document Conversion Lift
- D - LanceDB Embedding/Search Foundation
- F - Device Resolver
- I - Manual Find/Download
- J - Basic Local Web UI

## Can Start In Parallel

All Phase 1 packages can start after Phase 0 schemas are accepted. F can start with fixture profiles while B is being implemented. J can start against mocked API responses. D can start with synthetic chunks before conversion/indexing exists.

## Exit Criteria

- Device profiles can be created and listed.
- Documents can be converted into Markdown.
- LanceDB can index/search synthetic chunks with filters.
- Resolver can identify exact, ambiguous, and no-match devices.
- Manual finder can return candidates and save approved PDFs.
- UI shell can call or mock API endpoints without direct model/index access.

## Risks

- If B and F diverge on normalization rules, scoped search will be unreliable.
- If D does not support deterministic fake embeddings for tests, CI/local testing will become model-dependent.
- If J reaches into model/index code directly, the UI/model separation will be broken.
