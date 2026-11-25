# Markdown vault sync

`memoraos sync <vault> --user <id>` keeps a folder of Markdown notes (an Obsidian vault, a `notes/` directory) and a MemoraOS store in step, in both directions.

```bash
memoraos sync ./vault --user me --dry-run     # show what would happen, change nothing
memoraos sync ./vault --user me               # import notes, export memories, push edits
memoraos sync ./vault --user me --prune       # also propagate deletions (see below)
```

Python: `from memoraos.vault import sync_vault; sync_vault(mem, "./vault", user_id="me")`.

## What it does

| Situation | Result |
|---|---|
| New `.md` file in the vault | Stored as a `document` memory (`origin="vault:<path>"`); the original text is kept and facts are extracted as usual. |
| Note edited, memory untouched | Single-chunk notes become a **new version** of the same memory through `correct()`, so the old text stays in the history. Notes longer than one chunk (`chunk_chars`, 800 by default) are re-ingested and the memories that no longer match are **hard-deleted**, so their old text is *not* kept; the report says `history_kept: false`. |
| Memory changed (for example by `correct`), note untouched | The note is rewritten from the memory, for single-memory notes only. Multi-chunk notes are listed under `memory_changed_not_pushed`. |
| Both changed since the last sync | Reported under `conflicts` and **left alone** on both sides. The command exits with status 1. Resolve by hand (edit the note or `correct` the memory) and sync again. |
| Memory with no note | Written to `_memoraos/<memory id>.md` with a small front-matter block (id, category, source, verification, recorded). Editing the body and syncing corrects the memory. |
| Note deleted | Reported as `missing_files`; the memory is kept. With `--prune` its memories are forgotten (hard delete). |
| Memory forgotten | Reported as `missing_memories`; the exported note is kept. With `--prune` the exported note is removed. Imported notes are never deleted from disk, and a forgotten memory is never re-imported silently. |

Hidden folders (for example `.obsidian`) and the `_memoraos/` export folder are not imported. A vault is bound to the user and tenant that first synced it.

## How changes are detected

The state file `.memoraos-sync.json` in the vault records, for each file, the SHA-256 of the file and a hash of the memory text (ids, versions and contents) at the last sync. A side counts as changed when its hash differs. Nothing is merged: a one-sided change is applied, a two-sided change is a conflict. Keep the state file with the vault; without it every note would be imported again (identical text is deduplicated by content hash, but it would still be a fresh import).

## Limits

- **Tested only on synthetic notes** in temporary directories (`tests/unit/test_vault_sync.py`); not tried on a real Obsidian vault, and not benchmarked. Wiki-links, tags, attachments and front matter are treated as plain text.
- Matching is by content hash and file path. A **renamed** note is seen as a deleted note plus a new note.
- Secret redaction (on by default) applies on import, so a note containing a secret is stored redacted. If that memory is later changed, the push rewrites the note from the stored, redacted text.
- Two sync runs at the same time on one vault are not safe.
- Notes that exceed one chunk cannot keep their pre-edit text; if that matters, keep the vault under version control.
