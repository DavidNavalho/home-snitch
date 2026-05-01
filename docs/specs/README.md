# Home Wiki Specifications

This folder splits the home wiki build plan into phase-based implementation specifications. Each work package has its own document with scope, interfaces, dependencies, testing strategy, and expected scenario results.

## Phase Map

| Phase | Folder | Purpose | Parallel Work |
| --- | --- | --- | --- |
| Phase 0 | `phase-0-foundation/` | Lock contracts, schemas, config, fixtures, and test harness expectations. | A and K can run together. |
| Phase 1 | `phase-1-parallel-building-blocks/` | Build independent components behind stable contracts. | B, C, D, F, I, and J can run in parallel after Phase 0. |
| Phase 2 | `phase-2-integration-spine/` | Connect conversion, metadata, LanceDB, resolver, search, and ask paths. | E and G can overlap; H follows the search contract. |
| Phase 3 | `phase-3-orchestration-and-expansion/` | Add workflows and non-RAG home agents after the core blocks work. | L and M are independent from each other. |

## Specs

### Phase 0 Foundation

- [A - Project Contracts And Config](phase-0-foundation/A-project-contracts-and-config.md)
- [K - Fixtures And Smoke Tests](phase-0-foundation/K-fixtures-and-smoke-tests.md)

### Phase 1 Parallel Building Blocks

- [B - Device Profile Store](phase-1-parallel-building-blocks/B-device-profile-store.md)
- [C - Document Conversion Lift](phase-1-parallel-building-blocks/C-document-conversion-lift.md)
- [D - LanceDB Embedding/Search Foundation](phase-1-parallel-building-blocks/D-lancedb-embedding-search-foundation.md)
- [F - Device Resolver](phase-1-parallel-building-blocks/F-device-resolver.md)
- [I - Manual Find/Download](phase-1-parallel-building-blocks/I-manual-find-download.md)
- [J - Basic Local Web UI](phase-1-parallel-building-blocks/J-basic-local-web-ui.md)

### Phase 2 Integration Spine

- [E - Markdown Chunking And Index Build](phase-2-integration-spine/E-markdown-chunking-and-index-build.md)
- [G - Search API](phase-2-integration-spine/G-search-api.md)
- [H - Ask API](phase-2-integration-spine/H-ask-api.md)

### Phase 3 Orchestration And Expansion

- [L - Orchestration Layer](phase-3-orchestration-and-expansion/L-orchestration-layer.md)
- [M - WiFi Diagnostics Block](phase-3-orchestration-and-expansion/M-wifi-diagnostics-block.md)

## Testing Model

Every spec includes deterministic tests and scenario tests.

Deterministic tests should run without network access, without external LLM calls, and without requiring a local model server. These tests use fixtures, fake embedding providers, mocked web responses, and fixed API responses.

LLM-assisted evaluation is optional and should be used as an extra check, not as the only correctness signal. The expected result for every LLM-assisted scenario must be written down first, then Codex or another evaluator can run the implemented agent/script and compare the result against that expectation.

Model-dependent tests should be skipped unless explicit environment variables are present, for example:

```text
RUN_MODEL_TESTS=1
RUN_WEB_TESTS=1
RUN_LM_STUDIO_TESTS=1
```

