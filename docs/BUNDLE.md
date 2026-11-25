# Portable bundles (`.mem` files)

Export one user's memories to a single JSON file and import them into another MemoraOS store. This is **MemoraOS's own format** (`memoraos-bundle` v1). It is not the PAM or OpenMemory format and makes no compatibility claim with them.

```bash
memoraos --data-dir ~/.memoraos export-bundle me.mem --user me
memoraos --data-dir /other/store import-bundle me.mem --user me --dry-run
memoraos --data-dir /other/store import-bundle me.mem --user me
```

## What is in a bundle

For each memory: content, `effective_at`, `created_at`, source type, origin, verification, metadata, its active facts, and a read-only history. Plus the causal links between the exported memories.

## Integrity and signing

- A canonical SHA-256 over the content is stored in the file. Import recomputes it and refuses a bundle that was damaged or edited. **This detects damage; it does not authenticate**, because anyone can recompute a hash.
- Set `MEMORAOS_BUNDLE_KEY` before exporting to add an HMAC-SHA256 signature. Import with the same variable set verifies it; `--require-signature` fails unless it verifies. The key is read from the environment, never from a command-line argument. This authenticates only among people who share the key.
- **Verified is downgraded.** A `verified` memory is imported as `unverified` unless the signature verifies.

## Import behaviour

- New memory ids are assigned. Memories whose content already exists are skipped, so importing twice is safe.
- Facts are imported explicitly (no extraction is re-run), and causal links are re-created between the imported memories.
- `--dry-run` reports what would happen and writes nothing.

## Not preserved

Memory ids, retracted facts, version history (kept read-only inside the file but not re-created), recall logs and the audit chain. The original `created_at` is kept in metadata, not as the new row's `created_at`.

## Status

Covered by `tests/unit/test_bundle.py` (round trip, tamper detection, signature, downgrade, idempotence, dry run). Not tried between versions or with another tool's files. There is no REST endpoint or SDK wrapper for bundles yet; use the CLI or `memoraos.bundle`.
