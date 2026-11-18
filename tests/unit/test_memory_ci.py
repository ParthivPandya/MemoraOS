"""Memory CI: contracts, regression diff and CLI exit codes (spec 16). Inputs are small controlled contracts."""

from __future__ import annotations

import json

import pytest

from memoraos import contracts
from memoraos.cli import main
from memoraos.config import Settings

CONTRACT = {
    "suite": "plans",
    "sources": [
        {"text": "The plan of Acme is Professional.", "user_id": "c1", "effective_at": "2024-03-01T00:00:00Z"},
        {"text": "The plan of Acme is Enterprise.", "user_id": "c1", "effective_at": "2025-06-01T00:00:00Z"},
        {"text": "The invoice currency is euro.", "user_id": "c1", "source_type": "document"},
    ],
    "assertions": [
        {"id": "now", "question": "What is the current plan of Acme?", "user_id": "c1", "expected_answer": "Enterprise", "require_evidence": True},
        {"id": "before", "question": "What was the plan of Acme in 2024?", "user_id": "c1", "expected_answer": "Professional"},
        {"id": "refuse", "question": "What is the tax identifier of Acme?", "user_id": "c1", "status": "insufficient_evidence"},
        {"id": "isolation", "question": "What is the current plan of Acme?", "user_id": "c2", "status": "insufficient_evidence"},
    ],
}


def _doc(**over):
    d = json.loads(json.dumps(CONTRACT))
    d.update(over)
    return contracts.validate_contract(d)


def test_a_passing_contract_reports_every_assertion():
    res = contracts.run_contract(_doc()).to_dict()
    assert res["passed"], [r for r in res["results"] if not r["passed"]]
    assert res["assertions"] == 4 and res["failed"] == 0


def test_a_failing_expectation_names_the_reason():
    doc = _doc()
    doc["assertions"][0]["expected_answer"] = "Starter"
    res = contracts.run_contract(doc).to_dict()
    bad = next(r for r in res["results"] if r["id"] == "now")
    assert not res["passed"] and not bad["passed"] and any("Starter" in f for f in bad["failures"])


def test_injected_regression_is_detected():
    """Disabling a pipeline stage (evidence fusion) must surface as a regression, not pass silently."""
    doc = contracts.validate_contract({
        "suite": "multi-hop",
        "sources": [
            {"text": "Alice manages Project Atlas.", "user_id": "u"},
            {"text": "Project Atlas uses Azure Functions.", "user_id": "u"},
            {"text": "Azure Functions is deployed in West Europe.", "user_id": "u"},
        ],
        "assertions": [{"id": "region", "question": "Which Azure region is used by the project Alice manages?", "user_id": "u", "expected_answer": "West Europe", "require_evidence": True}],
    })
    good = contracts.run_contract(doc).to_dict()
    bad = contracts.run_contract(doc, settings=Settings(evidence_fusion=False)).to_dict()
    assert good["passed"] and not bad["passed"]
    diff = contracts.compare(good, bad)
    assert diff["ok"] is False and [r["id"] for r in diff["regressions"]] == ["region"] and diff["abstention_worse"] == ["region"]

def test_compare_flags_regressions_fixes_new_unsupported_answers_and_cost():
    def res(rows, tokens):
        return {"suite": "s", "passed": all(r["passed"] for r in rows), "mean_context_tokens": tokens, "mean_latency_ms": 1.0, "config": {}, "assertions": len(rows), "failed": 0, "results": rows}

    def row(i, passed, status, answerable=True, answer="x"):
        return {"id": i, "question": i, "passed": passed, "failures": [] if passed else ["f"], "status": status, "answer": answer, "answerable": answerable}

    base = res([row("a", True, "answered"), row("b", False, "answered"), row("c", True, "insufficient_evidence", False, ""), row("d", True, "answered", answer="old")], 100)
    cur = res([row("a", False, "insufficient_evidence"), row("b", True, "answered"), row("c", False, "answered", False, "invented"), row("d", True, "answered", answer="new"), row("e", True, "answered")], 160)
    d = contracts.compare(base, cur)
    assert [r["id"] for r in d["regressions"]] == ["a", "c"] and d["fixed"] == ["b"]
    assert d["abstention_worse"] == ["a"] and d["new_unsupported_answers"] == ["c"]
    assert d["answer_changed"] == [{"id": "d", "from": "old", "to": "new"}] and d["assertions_added"] == ["e"]
    assert d["mean_context_tokens_delta"] == 60 and d["ok"] is False


@pytest.mark.parametrize(
    "doc, message",
    [
        ({"sources": [], "assertions": [{"question": "q", "status": "answered"}]}, "suite"),
        ({"suite": "s", "assertions": []}, "non-empty"),
        ({"suite": "s", "sources": [{}], "assertions": [{"question": "q", "status": "answered"}]}, "exactly one"),
        ({"suite": "s", "assertions": [{"question": "q"}]}, "expected_answer or a status"),
        ({"suite": "s", "assertions": [{"question": "q", "status": "maybe"}]}, "status must be"),
        ({"suite": "s", "assertions": [{"question": "q", "status": "answered", "colour": "red"}]}, "unknown keys"),
        ({"suite": "s", "assertions": [{"id": "x", "question": "q", "status": "answered"}, {"id": "x", "question": "q", "status": "answered"}]}, "duplicate"),
    ],
)
def test_malformed_contracts_are_rejected_before_anything_runs(doc, message):
    with pytest.raises(contracts.ContractError, match=message):
        contracts.validate_contract(doc)


def test_a_source_file_outside_the_allowed_directories_is_refused(tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("nope", encoding="utf-8")
    inside = tmp_path / "inside"
    inside.mkdir()
    monkeypatch.chdir(inside)
    doc = contracts.validate_contract({"suite": "s", "sources": [{"file": "../outside/secret.txt"}], "assertions": [{"question": "q", "status": "insufficient_evidence"}]}, base=inside)
    with pytest.raises(contracts.ContractError, match="refused"):
        contracts.run_contract(doc)


def test_cli_exit_codes_and_baseline_workflow(tmp_path, capsys):
    path = tmp_path / "c.json"
    path.write_text(json.dumps(CONTRACT), encoding="utf-8")
    out = tmp_path / "base.json"
    assert main(["ci", "run", str(path), "--out", str(out)]) == 0
    assert "4/4 assertions passed" in capsys.readouterr().out
    assert main(["ci", "run", str(path), "--baseline", str(out)]) == 0
    assert "no regression" in capsys.readouterr().out
    worse = json.loads(json.dumps(CONTRACT))
    worse["assertions"][0]["expected_answer"] = "Starter"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(worse), encoding="utf-8")
    assert main(["ci", "run", str(bad), "--baseline", str(out)]) == 1
    assert "REGRESSION" in capsys.readouterr().out
    assert main(["ci", "run", str(tmp_path / "missing.json")]) == 2
    assert "cannot read contract" in capsys.readouterr().err



def test_cli_set_overrides_settings_and_surfaces_a_regression(tmp_path, capsys):
    multi_hop = {
        "suite": "multi-hop",
        "sources": [
            {"text": "Alice manages Project Atlas.", "user_id": "u"},
            {"text": "Project Atlas uses Azure Functions.", "user_id": "u"},
            {"text": "Azure Functions is deployed in West Europe.", "user_id": "u"},
        ],
        "assertions": [{"id": "region", "question": "Which Azure region is used by the project Alice manages?", "user_id": "u", "expected_answer": "West Europe"}],
    }
    path = tmp_path / "m.json"
    path.write_text(json.dumps(multi_hop), encoding="utf-8")
    base = tmp_path / "base.json"
    assert main(["ci", "run", str(path), "--out", str(base)]) == 0
    assert main(["ci", "run", str(path), "--set", "evidence_fusion=false", "--baseline", str(base)]) == 1
    assert "REGRESSION" in capsys.readouterr().out
    assert main(["ci", "run", str(path), "--set", "answerability=nonsense"]) == 2
    assert main(["ci", "run", str(path), "--set", "no_equals_sign"]) == 2
