"""distiller CLI — M0 仅 `init`（后续里程碑往上加 ls/show/pending 等）。"""
from __future__ import annotations

import argparse
from typing import Optional

from . import config, db, paths


def cmd_init(args) -> int:
    overrides = {"data_dir": args.data_dir} if args.data_dir else {}
    cfg = config.load(overrides=overrides)
    root = paths.ensure_layout(cfg.data_dir)
    conn = db.connect(paths.db_path(root))
    try:
        db.apply_schema(conn)
        ver = db.schema_version(conn)
    finally:
        conn.close()
    print(
        f"distiller initialized at {root} "
        f"(schema v{ver}, judge tier={cfg.judge.tier}, judge mode={cfg.judge.mode})"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="distiller", description="员工蒸馏器 MVP")
    sub = p.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("init", help="初始化数据目录与 SQLite schema")
    pi.add_argument("--data-dir", default=None, help="数据目录（默认 .distiller-data）")
    pi.set_defaults(func=cmd_init)
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
