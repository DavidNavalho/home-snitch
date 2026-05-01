# Fixtures

Deterministic offline fixtures for the home wiki build specs.

The fixture root mirrors the future runtime roots so tests can copy these files into a temporary workspace:

```text
fixtures/source_docs/
fixtures/markdown_docs/
fixtures/web/
fixtures/api/
fixtures/expected/
```

These files are intentionally small and human-readable. They define expected behavior for device resolution, conversion, chunking, indexing, search, ask, manual acquisition, and UI/API contracts without requiring live web access, model calls, or LanceDB.

Run the fixture smoke suite with:

```bash
python3 scripts/run_smoke_tests.py
```

After installing test dependencies from `requirements-dev.txt`, the same checks are available through:

```bash
python3 -m pytest
```
