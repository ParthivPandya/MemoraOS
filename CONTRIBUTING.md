# Contributing

Thanks for helping. The project values **measured claims** over features.

## Setup

```bash
pip install -e ".[dev,api]"
python -m pytest                 # must pass; no network, no API keys needed
ruff check src tests benchmarks
```

Dashboard: `cd apps/dashboard && npm install && npm run typecheck && npm run build`. TypeScript SDK: `cd sdk/typescript && npm install && npm test`.

## Ground rules

1. **Tests with every behaviour change.** Unit tests for logic, scenario tests (`tests/integration/test_scenarios.py`) for user-visible behaviour, `tests/security` for anything touching isolation, input or deletion. Tests must not use the network.
2. **Never fabricate.** No hard-coded benchmark numbers, no dummy competitor results, no marketing claims without a reproducible run. External systems appear in reports only if actually executed.
3. **Preserve evidence.** Originals are never altered by consolidation; lossy/derived state is never the only copy of a fact.
4. **Every query goes through `visibility_clause`.** New tables holding user data need `tenant_id`, `user_id`, scope columns and an isolation test.
5. **Migrations are append-only** (`storage/db.py::MIGRATIONS`). Never edit an applied migration.
6. **Mark experimental work** as experimental in code, docs and the README.
7. Keep abstractions small; match the surrounding style; type-hint public functions.

## Benchmarks

If you change retrieval, routing, extraction or the truth engine, run `python -m benchmarks.run` and include the before/after `REPORT.md` summary in your PR. A change that lowers any scenario must say so. Adding a scenario that exposes a weakness is welcome.

## Pull requests

Describe the behaviour change, link the issue, list tests added, paste benchmark deltas when relevant. Update docs that describe the changed behaviour. By contributing you agree your work is licensed under Apache-2.0.
