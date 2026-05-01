# Phase 0 - Foundation

Phase 0 defines the contracts that let implementation proceed in parallel. Nothing in this phase should depend on LanceDB, web search, model clients, or a frontend framework.

## Work Packages

- A - Project Contracts And Config - Done. Shared config and schema modules are available under `homewiki.config` and `homewiki.schemas`.
- K - Fixtures And Smoke Tests

## Status

Phase 0 is partially complete.

| Work Package | Status | Handoff |
| --- | --- | --- |
| A - Project Contracts And Config | Done | Use `homewiki.config.load_settings()` for environment/path settings and `homewiki.schemas` for shared request/response/data models. |
| K - Fixtures And Smoke Tests | In progress / separate acceptance | Fixture and smoke-test files may exist in this tree, but K should be verified against its own spec before marking complete. |

## Can Start In Parallel

A and K can start immediately. K should initially use the schemas and paths described in the spec documents, then switch to the implemented shared schema module once A lands.

## Exit Criteria

- Shared configuration names are defined.
- Shared request/response/data schemas are defined.
- Fixture device profiles and documents exist.
- Smoke test scenarios have expected results written down.
- Later packages can import schemas without importing implementation-specific clients.

## Risks

- If contracts stay vague, parallel workers will invent incompatible request and metadata shapes.
- If fixtures are delayed, integration will rely on manual testing and regressions will be harder to catch.
