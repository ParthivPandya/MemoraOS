"""Command line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .engine import MemoryOS


def _engine(args: argparse.Namespace) -> MemoryOS:
    return MemoryOS.local(args.data_dir)


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str, ensure_ascii=False))


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

    b = sub.add_parser("bench", help="run the benchmark suite")
    b.add_argument("--seed", type=int, default=7)
    b.add_argument("--out", default="benchmarks/reports")
    b.add_argument("--quick", action="store_true", help="smaller dataset for smoke runs")

    args = p.parse_args(argv)

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
    finally:
        eng.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
