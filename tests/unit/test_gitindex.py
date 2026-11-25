"""Git indexing against temporary repositories built with the real git binary."""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from memoraos.gitindex import Commit, GitError, commit_links, index_git, read_commits

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
U = "user_001"


class Repo:
    def __init__(self, path):
        self.path = path
        path.mkdir(parents=True)
        self.n = 0
        self.git("init", "-q")

    def git(self, *args, date=None):
        env = {**os.environ, "GIT_AUTHOR_NAME": "Dev", "GIT_AUTHOR_EMAIL": "d@example.com", "GIT_COMMITTER_NAME": "Dev", "GIT_COMMITTER_EMAIL": "d@example.com"}
        if date:
            env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
        out = subprocess.run(["git", "-C", str(self.path), "-c", "commit.gpgsign=false", *args], capture_output=True, text=True, env=env, check=True)
        return out.stdout.strip()

    def commit(self, message, files, date):
        for name, text in files.items():
            f = self.path / name
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text, encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message, date=date)
        return self.git("rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    return Repo(tmp_path / "r")


def test_commits_become_dated_memories_with_the_sha_and_files(mem, repo):
    sha = repo.commit("Replace Redis cache with SQLite\n\nRedis was too heavy for a single-node deploy.", {"cache.py": "x = 1\n"}, "2026-10-01T10:00:00+00:00")
    rep = index_git(mem, repo.path, user_id=U)
    assert rep["commits_new"] == 1 and rep["links"] == 0
    row = mem.db.one("SELECT original_content AS c, effective_at AS e, metadata AS m FROM memories")
    assert sha[:12] in row["c"] and "Redis was too heavy" in row["c"] and "cache.py" in row["c"] and row["e"].startswith("2026-10-01")
    res = mem.recall("Why did we replace Redis with SQLite?", user_id=U)
    assert res.status != "insufficient_evidence" and sha[:12] in res.evidence[0].excerpt


def test_reindexing_is_idempotent(mem, repo):
    repo.commit("first", {"a.txt": "1"}, "2026-10-01T10:00:00+00:00")
    repo.commit("second", {"a.txt": "2"}, "2026-10-02T10:00:00+00:00")
    index_git(mem, repo.path, user_id=U)
    n = mem.db.one("SELECT COUNT(*) AS n FROM memories")["n"]
    again = index_git(mem, repo.path, user_id=U)
    assert again["commits_already_indexed"] == 2 and again["commits_new"] == 0
    assert mem.db.one("SELECT COUNT(*) AS n FROM memories")["n"] == n


def test_revert_and_fixes_trailers_create_links_and_nothing_else_does(mem, repo):
    bad = repo.commit("Switch queue to Kafka", {"q.py": "kafka"}, "2026-10-01T10:00:00+00:00")
    repo.commit("Add logging", {"l.py": "log"}, "2026-10-02T10:00:00+00:00")
    revert = repo.commit(f'Revert "Switch queue to Kafka"\n\nThis reverts commit {bad}.', {"q.py": "old"}, "2026-10-03T10:00:00+00:00")
    fix = repo.commit(f"Fix queue timeouts\n\nFixes: {bad[:10]}", {"q.py": "fix"}, "2026-10-04T10:00:00+00:00")
    repo.commit("Mention fixes #12 and the earlier work", {"n.txt": "n"}, "2026-10-05T10:00:00+00:00")
    rep = index_git(mem, repo.path, user_id=U)
    assert rep["links"] == 2 and rep["unresolved_refs"] == 0
    ids = {r["sha"]: r["id"] for r in (dict(id=x["id"], sha=x["origin"][4:]) for x in mem.db.query("SELECT m.id, s.origin FROM memories m JOIN sources s ON s.id=m.source_id"))}
    edges = {(e["src"], e["dst"], e["kind"]) for e in mem.lineage(ids[bad], user_id=U)["edges"]}
    assert edges == {(ids[revert], ids[bad], "supersedes"), (ids[fix], ids[bad], "solves")}


def test_reference_to_a_commit_outside_the_range_is_counted_not_guessed(mem, repo):
    repo.commit("old", {"a": "1"}, "2026-10-01T10:00:00+00:00")
    repo.commit("Revert old\n\nThis reverts commit " + "ab" * 20 + ".", {"a": "2"}, "2026-10-02T10:00:00+00:00")
    rep = index_git(mem, repo.path, user_id=U)
    assert rep["links"] == 0 and rep["unresolved_refs"] == 1


def test_max_commits_since_and_bad_repo(mem, repo, tmp_path):
    for i, d in enumerate(("2026-01-01", "2026-06-01", "2026-10-01")):
        repo.commit(f"change {i}", {"f": str(i)}, f"{d}T10:00:00+00:00")
    assert [c.subject for c in read_commits(repo.path, max_commits=2)] == ["change 1", "change 2"]
    assert [c.subject for c in read_commits(repo.path, since="2026-05-01")] == ["change 1", "change 2"]
    with pytest.raises(GitError):
        index_git(mem, tmp_path, user_id=U)


def test_adrs_are_indexed_with_supersedes_links_and_updated_in_place(mem, repo):
    repo.commit("adr 1", {"docs/adr/0001-use-redis.md": "# ADR-0001: Use Redis\n\n**Status:** Superseded by ADR-0002\n\nWe use Redis for caching."}, "2026-03-01T10:00:00+00:00")
    repo.commit("adr 2", {"docs/adr/0002-use-sqlite.md": "# ADR-0002: Use SQLite\n\n**Status:** Accepted. Supersedes ADR-0001\n\nWe use SQLite for caching."}, "2026-10-01T10:00:00+00:00")
    rep = index_git(mem, repo.path, user_id=U)
    assert rep["adrs_new"] == 2 and rep["links"] == 1 and rep["unresolved_refs"] == 0
    rows = mem.db.query("SELECT src_id, dst_id, type FROM memory_links WHERE type LIKE 'causal:%'")
    assert len(rows) == 1 and rows[0]["type"] == "causal:supersedes"
    assert index_git(mem, repo.path, user_id=U)["adrs_unchanged"] == 2
    repo.commit("edit adr", {"docs/adr/0002-use-sqlite.md": "# ADR-0002: Use SQLite\n\n**Status:** Accepted. Supersedes ADR-0001\n\nWe use SQLite, with WAL mode."}, "2026-10-02T10:00:00+00:00")
    rep = index_git(mem, repo.path, user_id=U)
    assert rep["adrs_updated"] == 1
    adr_texts = [r["original_content"] for r in mem.db.query("SELECT original_content FROM memories WHERE original_content LIKE 'ADR file%'")]
    assert len(adr_texts) == 2 and any("WAL mode" in t for t in adr_texts) and not any("SQLite for caching" in t for t in adr_texts)


def test_commit_links_ignore_issue_numbers():
    c = Commit("a" * 40, "2026-01-01T00:00:00+00:00", "d", "Fixes #123", "Fix 4567\nfixes: deadbeef12", [])
    assert commit_links(c) == [("solves", "deadbeef12")]
