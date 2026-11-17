"""Tenant / scope visibility. Every query that touches user data must use this clause."""

from __future__ import annotations

from ..models import Scope, ScopeLevel


def visibility_clause(scope: Scope, alias: str = "") -> tuple[str, list]:
    """SQL fragment (and params) selecting rows the requester may see.

    - ``user``    : same tenant and same user
    - ``session`` : same user and the requester's current session
    - ``agent``   : the requester's agent id
    - ``project`` : the requester's project id (caller must authorise project membership)
    - ``org``     : everyone in the tenant
    """
    a = f"{alias}." if alias else ""
    parts = [f"({a}scope_level='user' AND {a}user_id=?)", f"({a}scope_level='org')"]
    params: list = [scope.user_id]
    if scope.session_id:
        parts.append(f"({a}scope_level='session' AND {a}scope_id=? AND {a}user_id=?)")
        params += [scope.session_id, scope.user_id]
    if scope.agent_id:
        parts.append(f"({a}scope_level='agent' AND {a}scope_id=?)")
        params.append(scope.agent_id)
    if scope.project_id:
        parts.append(f"({a}scope_level='project' AND {a}scope_id=?)")
        params.append(scope.project_id)
    return f"{a}tenant_id=? AND ({' OR '.join(parts)})", [scope.tenant_id, *params]


def write_scope_id(scope: Scope, level: ScopeLevel) -> str:
    """The scope_id a memory written at ``level`` is stored under."""
    if level == "user":
        return scope.user_id
    if level == "org":
        return scope.tenant_id
    value = {"agent": scope.agent_id, "session": scope.session_id, "project": scope.project_id}[level]
    if not value:
        raise ValueError(f"level='{level}' requires {level}_id on the scope")
    return value
