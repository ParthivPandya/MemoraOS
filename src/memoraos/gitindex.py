"""Index a Git repository's history (commits and ADRs) as memories, with causal links taken from explicit text.

Every commit becomes one memory (``effective_at`` is the author date, the commit SHA is in the text, the metadata
and the origin), so answers about *why* something changed cite a commit. Links are created only from explicit
statements, never inferred:

* ``This reverts commit <sha>`` (the text ``git revert`` writes): the revert ``supersedes`` the reverted commit;
* ``Fixes: <sha>`` or ``Fixes <sha>`` (a commit hash, not an issue number): the fix ``solves`` that commit;
* ``Supersedes ADR-N`` / ``Superseded by ADR-N`` on a Status-style line of an ADR: ``supersedes`` between the ADRs.

References to commits outside the indexed range are counted as unresolved, not guessed. Issue and pull-request
text is not fetched: only what is in the commit messages is indexed.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .engine import MemoryOS

MAX_FILES_LISTED = 25
MAX_ADR_CHARS = 20000
_ADR_PATH = re.compile(r"(^|/)(adrs?|decisions)/[^/]+\.md$", re.I)
_REVERT = re.compile(r"(?i)this reverts commit ([0-9a-f]{7,40})")
_FIXES = re.compile(r"(?im)^\s*fix(?:es)?:?\s+(?:commit\s+)?([0-9a-f]{7,40})\b")
_STATUS_LINE = re.compile(r"(?i)^[\s>*_#-]*(status|supersedes|superseded by)\b")
_SUPERSEDES = re.compile(r"(?i)\bsupersedes\s*:?\s*\[?ADR[- ]?0*(\d+)")
_SUPERSEDED_BY = re.compile(r"(?i)\bsuperseded by\s*:?\s*\[?ADR[- ]?0*(\d+)")
_ISSUE_REF = re.compile(r"(?i)\b(?:fix(?:es|ed)?|close[sd]?|resolve[sd]?)\s+#(\d+)")


class GitError(RuntimeError):
    pass


@dataclass
class Commit:
    sha: str
    date: str
    author: str
    subject: str
    body: str
    files: list[str] = field(default_factory=list)

    def text(self) -> str:
        shown = self.files[:MAX_FILES_LISTED]
        extra = f" (+{len(self.files) - len(shown)} more)" if len(self.files) > len(shown) else ""
        lines = [f"Commit {self.sha[:12]} on {self.date[:10]} by {self.author}: {self.subject}"]
        if self.body.strip():
            lines += ["", self.body.strip()]
        if shown:
            lines += ["", "Files changed: " + ", ".join(shown) + extra]
        return "\n".join(lines)


def _git(repo: Path, *args: str) -> str:
    try:
        out = subprocess.run(
            ["git", "-c", "core.quotepath=off", "-C", str(repo), *args], capture_output=True, check=False, timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitError(f"could not run git: {exc}") from exc
    if out.returncode != 0:
        raise GitError(out.stderr.decode("utf-8", "replace").strip() or f"git {args[0]} failed")
    return out.stdout.decode("utf-8", "replace")


def read_commits(repo: Path, *, rev: str = "HEAD", since: str | None = None, max_commits: int = 500) -> list[Commit]:
    """Newest ``max_commits`` commits reachable from ``rev``, oldest first."""
    args = ["log", f"-n{max_commits}", "--no-color", "--name-only", "--format=%x1e%H%x1f%aI%x1f%an%x1f%s%x1f%b%x1f"]
    if since:
        args.append(f"--since={since}")
    args.append(rev)
    commits = []
    for rec in _git(repo, *args).split("\x1e")[1:]:
        sha, date, author, subject, body, files = (rec.split("\x1f") + [""] * 6)[:6]
        commits.append(Commit(sha, date, author, subject, body, [f for f in files.splitlines() if f.strip()]))
    commits.reverse()
    return commits


def _resolve(ref: str, by_sha: dict[str, str]) -> str | None:
    """Memory id for a full or abbreviated SHA, or None when it is not indexed or the prefix is ambiguous."""
    ref = ref.lower()
    hits = {mid for sha, mid in by_sha.items() if sha.startswith(ref)}
    return hits.pop() if len(hits) == 1 else None


def commit_links(commit: Commit) -> list[tuple[str, str]]:
    """(kind, referenced sha) pairs stated in the commit message."""
    text = f"{commit.subject}\n{commit.body}"
    return [("supersedes", m) for m in _REVERT.findall(text)] + [("solves", m) for m in _FIXES.findall(text)]


def _adr_links(text: str) -> list[tuple[str, int]]:
    """(``supersedes`` | ``superseded_by``, ADR number) pairs from Status-style lines."""
    found = []
    for line in text.splitlines():
        if not _STATUS_LINE.match(line):
            continue
        found += [("supersedes", int(n)) for n in _SUPERSEDES.findall(line)]
        found += [("superseded_by", int(n)) for n in _SUPERSEDED_BY.findall(line)]
    return found


def _adr_number(path: str) -> int | None:
    m = re.match(r"(?i)(?:adr[-_ ]?)?0*(\d+)", Path(path).name)
    return int(m.group(1)) if m else None


def index_git(
    engine: MemoryOS, repo: str | Path, *, user_id: str, tenant_id: str = "default", rev: str = "HEAD", since: str | None = None,
    max_commits: int = 500, adrs: bool = True,
) -> dict:
    """Index commits (and, by default, ADR markdown files) into memories and record the explicit links.

    Re-running is safe: an unchanged commit or ADR is recognised by its content, and links are idempotent. A changed
    ADR replaces its earlier memory (the old one is deleted; git keeps the history).
    """
    repo = Path(repo).resolve()
    if not (repo / ".git").exists() and _git(repo, "rev-parse", "--is-inside-work-tree").strip() != "true":
        raise GitError(f"{repo} is not a git repository")
    commits = read_commits(repo, rev=rev, since=since, max_commits=max_commits)
    report = {"repo": str(repo), "rev": rev, "commits_seen": len(commits), "commits_new": 0, "commits_already_indexed": 0,
              "adrs_new": 0, "adrs_updated": 0, "adrs_unchanged": 0, "links": 0, "unresolved_refs": 0}
    by_sha: dict[str, str] = {}
    for c in commits:
        meta = {
            "kind": "git_commit", "sha": c.sha, "repo": repo.name, "author": c.author, "date": c.date,
            "files": c.files[:200], "issue_refs": sorted(set(_ISSUE_REF.findall(f"{c.subject}\n{c.body}")), key=int),
        }
        res = engine.remember(
            c.text(), user_id=user_id, tenant_id=tenant_id, source_type="document", origin=f"git:{c.sha}", effective_at=c.date,
            metadata=meta, extract=False,
        )
        by_sha[c.sha] = res.memory_ids[0]
        report["commits_already_indexed" if res.duplicate_of else "commits_new"] += 1
    for c in commits:
        for kind, ref in commit_links(c):
            dst = _resolve(ref, by_sha)
            if dst is None or dst == by_sha[c.sha]:
                report["unresolved_refs"] += 1
                continue
            engine.link(by_sha[c.sha], dst, kind, user_id=user_id, tenant_id=tenant_id)
            report["links"] += 1
    if adrs:
        _index_adrs(engine, repo, rev, user_id, tenant_id, report)
    return report


def _index_adrs(engine: MemoryOS, repo: Path, rev: str, user_id: str, tenant_id: str, report: dict) -> None:
    paths = [p for p in _git(repo, "ls-tree", "-r", "--name-only", rev).splitlines() if _ADR_PATH.search(p)]
    by_number: dict[int, str] = {}
    pending: list[tuple[str, str, int]] = []
    for path in sorted(paths):
        try:
            text = _git(repo, "show", f"{rev}:{path}")[:MAX_ADR_CHARS]
        except GitError:
            continue
        date = _git(repo, "log", "-1", "--format=%aI", rev, "--", path).strip() or None
        content = f"ADR file {path}\n\n{text}"
        meta = {"kind": "adr", "path": path, "number": _adr_number(path), "repo": repo.name}
        existing = {
            r["id"] for r in engine.db.query(
                "SELECT m.id FROM memories m JOIN sources s ON s.id = m.source_id WHERE m.tenant_id=? AND m.user_id=? AND m.status='active' AND s.origin=?",
                (tenant_id, user_id, f"adr:{path}"),
            )
        }
        res = engine.remember(
            content, user_id=user_id, tenant_id=tenant_id, source_type="document", origin=f"adr:{path}", effective_at=date, metadata=meta,
            extract=False,
        )
        mid = res.memory_ids[0]
        if not existing:
            report["adrs_new"] += 1
        elif existing == set(res.memory_ids):
            report["adrs_unchanged"] += 1
        else:
            report["adrs_updated"] += 1
            for old in existing - set(res.memory_ids):
                engine.forget(old, user_id=user_id, tenant_id=tenant_id)
        number = meta["number"]
        if number is not None:
            by_number[number] = mid
        pending += [(mid, kind, n) for kind, n in _adr_links(text)]
    edges: set[tuple[str, str]] = set()
    for mid, kind, n in pending:
        other = by_number.get(n)
        if other is None or other == mid:
            report["unresolved_refs"] += 1
            continue
        edges.add((mid, other) if kind == "supersedes" else (other, mid))
    for src, dst in sorted(edges):
        engine.link(src, dst, "supersedes", user_id=user_id, tenant_id=tenant_id)
        report["links"] += 1
