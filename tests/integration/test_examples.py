"""Examples must keep working: run each as a subprocess and check key output."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(name: str) -> str:
    p = subprocess.run([sys.executable, str(ROOT / "examples" / name / "main.py")], capture_output=True, text=True, encoding="utf-8", cwd=ROOT, timeout=120, env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")})
    assert p.returncode == 0, p.stderr
    return p.stdout


def test_basic_memory():
    out = run("basic_memory")
    assert "orchestration platform" in out and "after restart: ₹32 LPA" in out and "insufficient_evidence" in out


def test_temporal_memory():
    out = run("temporal_memory")
    assert "-> ₹32 LPA" in out and "-> ₹30 LPA" in out and "Angular: Angular 19" in out and "Database: conflict" in out


def test_hybrid_rag():
    assert "15 minutes" in run("hybrid_rag")


def test_multi_agent():
    out = run("multi_agent")
    assert out.count("(insufficient evidence)") == 4 and "₹50 LPA" in out


def test_research_memory():
    out = run("research_memory")
    assert "originals modified = 0" in out and "after rollback, derived memories: 0" in out
