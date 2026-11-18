# Memory CI

Memory CI makes memory behaviour testable the way application code is: you write down what memory must answer, what it must refuse and what it must never leak, run that after every change, and get a regression report.

```bash
memoraos ci run contracts/python_releases_and_security.json --out baseline.json   # first run; becomes the baseline
# ... change extraction, embeddings, routing, a provider, the schema ...
memoraos ci run contracts/python_releases_and_security.json --baseline baseline.json
```

Exit codes: `0` all assertions pass and no regression, `1` an assertion failed or memory regressed, `2` the contract or a file is unreadable or malformed (the message says what to fix).

## What a contract contains

JSON (or YAML if PyYAML is installed). Every run happens in a fresh in-memory engine, so runs cannot see each other's state.

```json
{
  "suite": "name",
  "settings": {"answerability": "balanced"},
  "sources": [
    {"text": "The plan of Acme is Enterprise.", "user_id": "c1", "effective_at": "2025-06-01T00:00:00Z"},
    {"file": "docs/SECURITY.md", "user_id": "c1", "source_type": "document"},
    {"records_file": "data/python_releases.json", "user_id": "c1"},
    {"json": {"subject": "Acme", "predicate": "plan", "object": "Enterprise", "valid_from": "2025-06-01"}, "user_id": "c1"}
  ],
  "assertions": [
    {"id": "now", "question": "What is the current plan of Acme?", "user_id": "c1", "expected_answer": "Enterprise", "require_evidence": true},
    {"id": "refuse", "question": "What is the tax identifier of Acme?", "user_id": "c1", "status": "insufficient_evidence"},
    {"id": "isolation", "question": "What is the current plan of Acme?", "user_id": "c2", "status": "insufficient_evidence"}
  ]
}
```

| Assertion field | Meaning |
|---|---|
| `question` | Required. |
| `expected_answer` | Case-insensitive substring of the answer. Implies `status: answered`. |
| `status` | `answered`, `insufficient_evidence` or `conflict`. At least one of `status` / `expected_answer` is required. |
| `forbidden_answer` | Must not appear in the answer (for example the stale value after an update). |
| `require_evidence` | At least one evidence item, every item has a source id, and one excerpt contains the expected answer. |
| `require_temporal_evidence` | Evidence carries an effective date, or validity is `current` / `historical`. |
| `user_id`, `tenant_id` | Who asks. Asking as someone who owns no memory is how tenant and user isolation is tested. |
| `max_context_tokens` | Budget for the evidence returned. |
| `as_of` | **System time**: what MemoraOS had *recorded* by then. Valid time ("in 2024", "before October 2024") belongs in the question text. |

Source files must live under the contract's directory or the current directory; other paths are refused. Do not put real credentials in a contract: write refusal tests as questions whose answer must be absent.

## The regression report

`--baseline` compares with a previous `--out` file of the same contract and reports:

- expectations that passed before and fail now;
- answerable questions that are now refused (abstention got worse);
- questions that must be refused but are now answered (new unsupported answers);
- status changes, answer-text changes, assertions added or removed;
- the change in mean evidence tokens and latency.

Real output of the shipped contract (`contracts/python_releases_and_security.json`: the CPython release history from PEP 693, 719 and 745 plus this repository's security document):

```text
Memory CI: suite 'python-releases-and-security-docs' (strict, hashing-v1)
  7/7 assertions passed; mean 51 context tokens, 7.2 ms
  PASS  latest-now: What is the latest version of Python 3.14?
  PASS  latest-in-march-2026: What was the latest version of Python 3.14 in March 2026?
  PASS  previous-stable: What was the latest stable version of Python before October 2024?
  PASS  encryption-at-rest: Is encryption at rest implemented in code?
  PASS  refuses-unknown-version: What is the latest version of Python 3.15?
  PASS  refuses-absent-topic: Which Kubernetes version does MemoraOS require?
  PASS  other-user-sees-nothing: What is the latest version of Python 3.14?
```

## Does it catch regressions?

Yes, for the cases tested: `tests/unit/test_memory_ci.py` disables evidence fusion on a three-hop contract and checks that the run is reported as a regression and as worsened abstention, and that a contract with a failing expectation exits `1`. This verifies the mechanism, not that any particular contract covers your application: Memory CI finds only the behaviour you wrote down.

## Limits

- Matching is by substring, so a contract can pass on an answer that contains the expected text incidentally. Use `forbidden_answer` for the stale value.
- Each run uses the deterministic defaults unless the contract's `settings` or the CLI say otherwise: `--set KEY=VALUE` (repeatable, JSON-parsed) overrides a setting and `--embedder <sentence-transformers model>` selects a neural embedder (needs the optional package). LLM extraction is not selectable from the CLI; call `memoraos.contracts.run_contract(doc, ...)` from Python.
- Hooks that trigger the run automatically when a schema, provider or skill changes are not implemented; run the command in your CI.
