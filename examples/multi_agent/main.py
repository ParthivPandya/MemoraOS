"""Multi-agent / multi-tenant memory with REAL documents: private, project, agent and org scopes with isolation.

Run:  python examples/multi_agent/main.py
"""

import sys
from pathlib import Path

from memoraos import MemoryOS

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

DOCS = Path(__file__).resolve().parents[2] / "docs"


def text(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


memory = MemoryOS.in_memory()
memory.remember(text("SECURITY.md"), user_id="maintainer", source_type="document")                            # private to the maintainer
memory.remember(text("ROADMAP.md"), user_id="maintainer", level="org", source_type="document")               # whole tenant
memory.remember(text("ADR/0005-configurable-rank-fusion.md"), user_id="maintainer", level="agent", agent_id="planner", source_type="document")
memory.remember(text("PERFORMANCE.md"), user_id="maintainer", level="project", project_id="benchmarks", source_type="document")
memory.remember(text("LATENT_MEMORY.md"), user_id="visitor", tenant_id="other-org", source_type="document")  # another tenant


def ask(label: str, q: str, **who) -> None:
    r = memory.recall(q, **who)
    print(f"{label:<34} {q:<48} -> {r.answer[:58].replace(chr(10), ' ') if r.supported else '(insufficient evidence)'}")


ask("maintainer (owner)", "Which address does the REST API bind to by default?", user_id="maintainer")
ask("colleague (same tenant)", "Which address does the REST API bind to by default?", user_id="colleague")
ask("colleague sees org memory", "Which standard benchmarks are planned as adapters?", user_id="colleague")
ask("colleague with agent_id=planner", "What weight do expanded query lists get by default?", user_id="colleague", agent_id="planner")
ask("colleague without agent_id", "What weight do expanded query lists get by default?", user_id="colleague")
ask("colleague in project benchmarks", "How much RAM did the benchmark machine have?", user_id="colleague", project_id="benchmarks")
ask("colleague outside the project", "How much RAM did the benchmark machine have?", user_id="colleague")
ask("visitor from another tenant", "Which standard benchmarks are planned as adapters?", user_id="visitor", tenant_id="other-org")
memory.close()
