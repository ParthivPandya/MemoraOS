"""Multi-agent / multi-tenant memory: private, agent-shared, project and org scopes with isolation.

Run:  python examples/multi_agent/main.py
"""

import sys

from memoraos import MemoryOS

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

memory = MemoryOS.in_memory()
memory.remember("Alice's salary is ₹50 LPA.", user_id="alice")                                  # private to alice
memory.remember("The release process uses trunk based development.", user_id="alice", level="org")   # whole tenant
memory.remember("The planner agent prefers concise answers.", user_id="alice", level="agent", agent_id="planner")
memory.remember("Project Zeta uses Rust.", user_id="alice", level="project", project_id="zeta")
memory.remember("Other tenant secret quokka.", user_id="mallory", tenant_id="other-corp")


def ask(label: str, q: str, **who) -> None:
    r = memory.recall(q, **who)
    print(f"{label:<34} {q:<42} -> {r.answer[:60] if r.supported else '(insufficient evidence)'}")


ask("alice (self)", "What is Alice's salary?", user_id="alice")
ask("bob (same tenant)", "What is Alice's salary?", user_id="bob")
ask("bob sees org memory", "What release process is used?", user_id="bob")
ask("bob with agent_id=planner", "What does the planner agent prefer?", user_id="bob", agent_id="planner")
ask("bob without agent_id", "What does the planner agent prefer?", user_id="bob")
ask("carol in project zeta", "What does Zeta use?", user_id="carol", project_id="zeta")
ask("carol outside the project", "What does Zeta use?", user_id="carol")
ask("alice from another tenant", "What release process is used?", user_id="alice", tenant_id="other-corp")
memory.close()
