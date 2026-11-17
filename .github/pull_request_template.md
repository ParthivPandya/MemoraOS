## What and why

## Tests added / changed

## Benchmark impact
<!-- Required for changes to retrieval, routing, extraction or the truth engine. Paste before/after from `python -m benchmarks.run`, and state any scenario that got worse. -->

## Checklist
- [ ] `python -m pytest` passes locally
- [ ] `ruff check src tests benchmarks` passes
- [ ] No network or API key needed by tests
- [ ] Docs updated where behaviour changed
- [ ] No fabricated numbers; experimental features are labelled experimental
- [ ] New user-data queries use `visibility_clause` and have an isolation test
