# Git history as memory (`memoraos index-git`)

Index a repository's commits, and its architecture decision records, into MemoraOS so an agent can ask *when* and *why* something changed and get an answer that cites a commit.

```bash
memoraos --data-dir ~/.memoraos index-git . --user me
memoraos index-git . --user me --since "3 months ago" --max-commits 500 --rev main
memoraos index-git . --user me --no-adrs
```

## What is stored

- **One memory per commit**: source type `document`, origin `git:<sha>`, `effective_at` = the commit's author date, text = subject, body and the changed file names. Re-running is idempotent (already-indexed commits are skipped).
- **ADRs** found under `adr/`, `adrs/` or `decisions/` (Markdown), origin `adr:<path>`. If an ADR changes, its old memories are replaced; MemoraOS keeps no history of earlier ADR text.
- No fact extraction is run on commits (`extract=False`), so the answer is a cited passage, not a derived statement.

## Causal links

Links are created **only from explicit text**, never inferred:

| Text | Link |
|---|---|
| `This reverts commit <sha>` | the revert `supersedes` the original |
| a `Fixes: <sha>` trailer | the fix `solves` that commit |
| an ADR Status line saying "Supersedes ADR-N" / "Superseded by ADR-N" | `supersedes` between the ADRs |

A reference to a commit outside the indexed range is counted in `unresolved_refs`. PR descriptions and issues are **not** fetched; a commit message that mentions a PR is just text.

## Verified on this repository (informal, not a benchmark)

`index-git` on this repo indexed 17 commits and 9 ADRs; a second run indexed nothing new. It created 0 links, because this history contains no revert, `Fixes:` trailer or supersede text. Four hand-picked questions:

| Question | Result |
|---|---|
| What changed about silent-e verb forms? | cited the right commit |
| When did we add verifiable citations? | cited the right commit |
| Which commit added encryption at rest? | **cited a different commit** than the one that introduced it |
| Who is the CEO of Google? | correctly refused |

A fifth, "Why was the stemmer fixed?", also missed because the commit says "stem" and retrieval is lexical by default. Four to five queries on one repository say nothing about general accuracy.

## Limits

- Retrieval is the normal MemoraOS retrieval, so wording matters.
- "Why" answers are only as good as the commit message; MemoraOS does not read diffs.
- The history of a rewritten branch is not tracked.
