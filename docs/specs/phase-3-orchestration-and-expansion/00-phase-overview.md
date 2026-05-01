# Phase 3 - Orchestration And Expansion

Phase 3 adds higher-level workflows and separate future agents after the core home wiki ingestion/search/ask spine is working.

## Work Packages

- L - Orchestration Layer
- M - WiFi Diagnostics Block

## Can Start In Parallel

L should wait until the individual blocks it orchestrates are stable. M can be designed independently, but implementation should not distract from the Phase 0-2 home wiki path.

## Exit Criteria

- Repeated user workflows can be run through thin orchestrators.
- WiFi diagnostics exists as an independent block with its own CLI/API contract.
- No orchestration layer hides or duplicates the core behavior of individual blocks.

## Risks

- Adding orchestration too early can make debugging harder.
- WiFi diagnostics may need OS-specific commands and permissions; it should remain isolated from the RAG code path.

