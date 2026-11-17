"""Examples must keep working: run each as a subprocess and check key output. Every example uses real data
(MemoraOS's own docs, or the dated CPython release history in data/python_releases.json)."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(name: str) -> str:
    p = subprocess.run([sys.executable, str(ROOT / "examples" / name / "main.py")], capture_output=True, text=True, encoding="utf-8", cwd=ROOT, timeout=180, env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")})
    assert p.returncode == 0, p.stderr
    return p.stdout


def test_basic_memory():
    out = run("basic_memory")
    assert "stored 7 real documents" in out and "CI failed intermittently on Windows" in out
    assert "after restart: answered" in out and "EmbeddingModelMismatch" in out and "unsupported: insufficient_evidence" in out


def test_temporal_memory():
    out = run("temporal_memory")
    assert "latest version of Python 3.14?\n  -> 3.14.10" in out
    assert "in March 2026?\n  -> 3.14.3" in out
    assert "previous latest version of Python 3.14?\n  -> 3.14.9" in out
    assert "-> 3.12 (effective 2023-10-02)" in out
    assert "current    3.14.10" in out and "contradictions: none" in out


def test_hybrid_rag():
    out = run("hybrid_rag")
    assert out.count("| Secure by default |") == 4 and out.count("insufficient_evidence") == 4


def test_multi_agent():
    out = run("multi_agent")
    assert out.count("(insufficient evidence)") == 4
    assert "| Secure by default |" in out and "LongMemEval" in out


def test_research_memory():
    out = run("research_memory")
    assert "originals modified = 0" in out and "after rollback, derived memories: 0" in out
