"""Command line interface."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .config import Settings
from .engine import MemoryOS
from .storage.crypto import ENV_KEY, EncryptionError
from .storage.db import convert_database


def _engine(args: argparse.Namespace) -> MemoryOS:
    try:
        return MemoryOS.local(args.data_dir)
    except EncryptionError as exc:
        print(f"memoraos: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str, ensure_ascii=False))


def _ci(args: argparse.Namespace) -> int:
    from . import contracts

    try:
        if args.ci_cmd == "compare":
            base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
            cur = json.loads(Path(args.current).read_text(encoding="utf-8"))
            diff = contracts.compare(base, cur)
            print(contracts.render(cur, diff))
            return 0 if diff["ok"] and cur["passed"] else 1
        doc = contracts.load_contract(args.contract)
        settings = None
        if args.set or args.embedder:
            overrides = {**doc.get("settings", {})}
            for item in args.set or []:
                key, sep, raw = item.partition("=")
                if not sep:
                    raise contracts.ContractError(f"--set expects key=value, got {item!r}")
                try:
                    overrides[key] = json.loads(raw)
                except json.JSONDecodeError:
                    overrides[key] = raw
            settings = Settings(**overrides)
        embedder = None
        if args.embedder:
            from .providers.embeddings import SentenceTransformerEmbedder

            embedder = SentenceTransformerEmbedder(args.embedder)
        result = contracts.run_contract(doc, settings=settings, embedder=embedder).to_dict()
        diff = None
        if args.baseline:
            diff = contracts.compare(json.loads(Path(args.baseline).read_text(encoding="utf-8")), result)
        if args.out:
            Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(contracts.render(result, diff))
        return 0 if result["passed"] and (diff is None or diff["ok"]) else 1
    except (contracts.ContractError, OSError, json.JSONDecodeError, KeyError, ValueError, ImportError) as exc:
        print(f"memoraos ci: {exc}", file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="memoraos", description="MemoraOS adaptive memory engine")
    p.add_argument("--data-dir", default=None, help="data directory (default ./.memoraos)")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("remember", help="store text")
    r.add_argument("text")
    r.add_argument("--user", required=True)
    r.add_argument("--effective-at")
    q = sub.add_parser("recall", help="answer a question")
    q.add_argument("query")
    q.add_argument("--user", required=True)
    q.add_argument("--as-of")
    q.add_argument("--explain", action="store_true")
    c = sub.add_parser("consolidate")
    c.add_argument("--user", required=True)
    c.add_argument("--mode", default="manual", choices=["manual", "incremental"])
    c.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("stats")
    s.add_argument("--tenant", default="default")
    e = sub.add_parser("export")
    e.add_argument("--user", required=True)
    sub.add_parser("backup").add_argument("dest")
    sy = sub.add_parser("sync", help="two-way sync between a Markdown folder and the memory store")
    sy.add_argument("vault")
    sy.add_argument("--user", required=True)
    sy.add_argument("--tenant", default="default")
    sy.add_argument("--direction", default="both", choices=["both", "import", "export"])
    sy.add_argument("--prune", action="store_true", help="propagate deletions (a deleted note forgets its memories; hard delete)")
    sy.add_argument("--dry-run", action="store_true")
    sl = sub.add_parser("sleep", help="maintenance pass: consolidate, check the audit chain, optionally expire stale hypotheses")
    sl.add_argument("--user", required=True)
    sl.add_argument("--expire-hypotheses-days", type=int, default=None)
    sl.add_argument("--no-consolidate", action="store_true")
    sl.add_argument("--dry-run", action="store_true")
    ln = sub.add_parser("link", help="record an explicit causal link: SRC <kind> DST")
    ln.add_argument("src")
    ln.add_argument("kind", choices=["causes", "solves", "supersedes", "blocked_by"])
    ln.add_argument("dst")
    ln.add_argument("--user", required=True)
    lg = sub.add_parser("lineage", help="show the explicit causal chain around a memory")
    lg.add_argument("memory_id")
    lg.add_argument("--user", required=True)
    lg.add_argument("--direction", default="both", choices=["both", "up", "down"])
    lg.add_argument("--max-depth", type=int, default=5)
    rp = sub.add_parser("replay", help="re-run a logged recall with memories removed (on a temporary copy)")
    rp.add_argument("recall_id")
    rp.add_argument("--user", required=True)
    rp.add_argument("--exclude", nargs="*", default=[], help="memory ids to remove")
    rp.add_argument("--leave-one-out", action="store_true", help="remove each cited memory in turn")
    sub.add_parser("encrypt", help=f"encrypt the database file in place (passphrase from {ENV_KEY})")
    sub.add_parser("decrypt", help=f"decrypt the database file in place (passphrase from {ENV_KEY})")

    k = sub.add_parser("keys", help="manage API keys")
    ks = k.add_subparsers(dest="keys_cmd", required=True)
    kc = ks.add_parser("create")
    kc.add_argument("--tenant", required=True)
    kc.add_argument("--role", default="write", choices=["read", "write", "admin"])
    kc.add_argument("--users", nargs="*", help="restrict the key to these user ids")

    sv = sub.add_parser("serve", help="start the REST API")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--insecure-no-auth", action="store_true", help="development only: disable authentication")
    sub.add_parser("mcp", help="start the MCP stdio server (set MEMORAOS_USER_ID)")
    hk = sub.add_parser("hook", help="coding-agent hooks (claude-code, cursor, codex): install/uninstall, or capture a hook payload from stdin")
    hks = hk.add_subparsers(dest="hook_cmd", required=True)
    hi = hks.add_parser("install", help="add the hook to the agent's config (claude-code: settings.json, cursor: hooks.json, codex: hooks.json)")
    hi.add_argument("target", choices=["claude-code", "cursor", "codex"])
    hi.add_argument("--user", required=True)
    hi.add_argument("--project", action="store_true", help="write the project-level config in the current directory instead of the user-level one")
    hu = hks.add_parser("uninstall", help="remove the hook")
    hu.add_argument("target", choices=["claude-code", "cursor", "codex"])
    hu.add_argument("--project", action="store_true")
    hc = hks.add_parser("capture", help="read a hook payload (JSON) on stdin and store the text as hypotheses")
    hc.add_argument("--user", required=True)
    hc.add_argument("--agent", choices=["claude-code", "cursor", "codex"], default="claude-code")

    b = sub.add_parser("bench", help="run the benchmark suite")
    b.add_argument("--seed", type=int, default=7)
    b.add_argument("--out", default="benchmarks/reports")
    b.add_argument("--quick", action="store_true", help="smaller dataset for smoke runs")

    ci = sub.add_parser("ci", help="Memory CI: run memory contracts and diff two runs")
    cis = ci.add_subparsers(dest="ci_cmd", required=True)
    cr = cis.add_parser("run", help="run a contract (JSON, or YAML with PyYAML); exit 1 on a failed assertion or regression")
    cr.add_argument("contract")
    cr.add_argument("--baseline", help="a previous --out file of the same contract; adds a regression report")
    cr.add_argument("--out", help="write this run's result JSON here (use it as the next baseline)")
    cr.add_argument("--set", action="append", metavar="KEY=VALUE", help='override a Settings field for this run, e.g. --set answerability=balanced (value is parsed as JSON when possible)')
    cr.add_argument("--embedder", help="sentence-transformers model name to run the contract with (needs sentence-transformers); default is the offline hashing embedder")
    cc = cis.add_parser("compare", help="regression report between two result files")
    cc.add_argument("baseline")
    cc.add_argument("current")

    args = p.parse_args(argv)

    if args.cmd == "ci":
        return _ci(args)
    if args.cmd in ("encrypt", "decrypt"):
        passphrase = os.environ.get(ENV_KEY)
        if not passphrase:
            print(f"Set {ENV_KEY} (a passphrase is never accepted on the command line).", file=sys.stderr)
            return 2
        db_file = Settings(data_dir=Path(args.data_dir or ".memoraos")).db_path
        try:
            convert_database(db_file, passphrase, to_encrypted=args.cmd == "encrypt")
        except (EncryptionError, OSError) as exc:
            print(f"memoraos {args.cmd}: {exc}", file=sys.stderr)
            return 2
        print(f"{db_file}: {args.cmd}ed. Plain copies under 'sources/' and old backups are not touched; remove them if they are sensitive.")
        return 0
    if args.cmd == "keys":
        data = Path(args.data_dir or ".memoraos")
        from .api.auth import ApiKeyStore

        key = ApiKeyStore.create(data / "api_keys.json", args.tenant, args.role, args.users)
        print(f"API key (shown once, store it securely):\n{key}")
        return 0
    if args.cmd == "serve":
        try:
            import uvicorn

            from .api.app import create_app
            from .api.auth import ApiKeyStore
        except ImportError:
            print("Install the API extra: pip install 'memoraos[api]'", file=sys.stderr)
            return 2
        eng = _engine(args)
        keys = ApiKeyStore.load(eng.settings.data_dir / "api_keys.json")
        try:
            app = create_app(eng, keys, insecure_no_auth=args.insecure_no_auth)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        uvicorn.run(app, host=args.host, port=args.port)
        return 0
    if args.cmd == "hook":
        from . import hooks

        if args.hook_cmd == "install":
            settings = hooks.config_path(args.target, project=args.project)
            data_dir = Path(args.data_dir or ".memoraos").resolve()
            suffix = "" if args.target == "claude-code" else f" --agent {args.target}"
            cmd = f'memoraos --data-dir "{data_dir}" hook capture --user {args.user}{suffix}'
            print(f"installed in {settings}" if hooks.install(args.target, settings, cmd) else f"already installed in {settings}")
            if args.target == "codex":
                print("Codex runs a new hook only after you review and trust it: open /hooks in the Codex CLI.")
            return 0
        if args.hook_cmd == "uninstall":
            settings = hooks.config_path(args.target, project=args.project)
            print(f"removed from {settings}" if hooks.uninstall(args.target, settings) else f"no memoraos hook in {settings}")
            return 0
        try:
            payload = json.loads(sys.stdin.read() or "{}")
        except ValueError:
            return 0
        try:
            eng = _engine(args)
            try:
                hooks.capture(eng, payload, args.user, args.agent)
            finally:
                eng.close()
        except Exception as exc:  # noqa: BLE001 - a hook must never break the agent; the error goes to stderr
            print(f"memoraos hook: {type(exc).__name__}: {exc}", file=sys.stderr)
        out = hooks.reply(args.agent, payload)
        if out:
            print(out)
        return 0
    if args.cmd == "mcp":
        from .mcp.server import main as mcp_main

        mcp_main()
        return 0
    if args.cmd == "bench":
        try:
            from benchmarks.run import main as bench_main  # type: ignore[import-not-found]
        except ImportError:
            print("The benchmark lab lives in the source repository: run `python -m benchmarks.run` from a checkout.", file=sys.stderr)
            return 2
        return bench_main(["--seed", str(args.seed), "--out", args.out] + (["--quick"] if args.quick else []))

    eng = _engine(args)
    try:
        if args.cmd == "remember":
            _print(eng.remember(args.text, user_id=args.user, effective_at=args.effective_at).model_dump())
        elif args.cmd == "recall":
            res = eng.recall(args.query, user_id=args.user, as_of=args.as_of)
            _print(res.model_dump())
            if args.explain:
                _print(eng.explain(res.recall_id, user_id=args.user))
        elif args.cmd == "consolidate":
            _print(eng.consolidate(user_id=args.user, mode=args.mode, dry_run=args.dry_run))
        elif args.cmd == "stats":
            _print(eng.stats(tenant_id=args.tenant))
        elif args.cmd == "export":
            _print(eng.export(user_id=args.user))
        elif args.cmd == "backup":
            print(eng.backup(args.dest))
        elif args.cmd in ("sync", "sleep", "link", "lineage", "replay"):
            try:
                if args.cmd == "sync":
                    from .vault import sync_vault

                    report = sync_vault(eng, args.vault, user_id=args.user, tenant_id=args.tenant, direction=args.direction, prune=args.prune, dry_run=args.dry_run)
                    _print(report)
                    return 1 if report["conflicts"] else 0
                if args.cmd == "sleep":
                    _print(eng.sleep(user_id=args.user, expire_hypotheses_days=args.expire_hypotheses_days, dry_run=args.dry_run, consolidate=not args.no_consolidate))
                elif args.cmd == "link":
                    _print(eng.link(args.src, args.dst, args.kind, user_id=args.user))
                elif args.cmd == "lineage":
                    _print(eng.lineage(args.memory_id, user_id=args.user, direction=args.direction, max_depth=args.max_depth))
                else:
                    _print(eng.replay(args.recall_id, user_id=args.user, exclude=args.exclude, leave_one_out=args.leave_one_out))
            except (ValueError, KeyError, PermissionError) as exc:
                print(f"memoraos {args.cmd}: {exc}", file=sys.stderr)
                return 2
    finally:
        eng.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
