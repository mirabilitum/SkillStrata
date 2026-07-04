"""distiller CLI — init + 只读观测子命令（ls / show / usage / pending）。

复审 P1-a：此前只注册 init，README 宣称的 ls/show/usage/pending 全部缺失。
这里把它们接到已有的 observe / cli_pending 查询函数（底层能力早已存在，只差接线）。
所有子命令共享 --data-dir，只读命令不改任何状态。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from typing import Optional

from . import cli_pending, config, db, observe, paths


class _NotInitialized(Exception):
    """数据目录未初始化——只读命令不应隐式建库（复审 P2）。"""


class _InvalidDataDir(Exception):
    """数据目录里有 DB 文件但无效/损坏（空文件、截断、非 distiller schema）。"""


def _open_conn(args):
    """按 --data-dir 打开**已初始化**的数据仓库连接（严格只读，不创建任何东西）。

    - DB 文件不存在 → _NotInitialized
    - DB 文件在但没有 schema（空文件 / init 中途失败 / 截断 / 非 distiller 库）
      → 读 schema_version 会抛 sqlite3.Error（如 `no such table: meta`），
        统一转成 _InvalidDataDir，由命令层友好报错，不 traceback（复审三次 P2-1）。
    """
    overrides = {"data_dir": args.data_dir} if args.data_dir else {}
    cfg = config.load(overrides=overrides)
    dbfile = paths.db_path(cfg.data_dir)
    if not dbfile.exists():
        raise _NotInitialized(str(cfg.data_dir))
    conn = db.connect(dbfile)
    try:
        ver = db.schema_version(conn)
    except sqlite3.Error as exc:
        conn.close()
        raise _InvalidDataDir(f"{cfg.data_dir}: {exc}") from exc
    if ver == 0:
        conn.close()
        raise _NotInitialized(str(cfg.data_dir))
    return conn


def _run_read(args, fn) -> int:
    """只读命令统一入口：处理未初始化 / 损坏错误。fn(conn) 返回要 _emit 的对象。"""
    try:
        conn = _open_conn(args)
    except _NotInitialized as e:
        print(f"数据目录未初始化：{e}. 先运行 distiller init")
        return 2
    except _InvalidDataDir as e:
        print(f"数据目录无效或损坏：{e}. 请重新运行 distiller init 或更换 --data-dir")
        return 2
    try:
        return fn(conn)
    finally:
        conn.close()


def _emit(args, obj) -> None:
    """按 --json / 默认人读格式输出。"""
    if getattr(args, "json", False):
        print(json.dumps(obj, ensure_ascii=False, indent=2))
        return
    if isinstance(obj, list):
        if not obj:
            print("(空)")
            return
        for item in obj:
            print(_fmt_row(item))
    else:
        for k, v in obj.items():
            print(f"{k}: {v}")


def _fmt_row(item: dict) -> str:
    if not isinstance(item, dict):
        return str(item)
    # 紧凑单行：key=value 用 · 连接
    return "  ".join(f"{k}={v}" for k, v in item.items())


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


def cmd_ls(args) -> int:
    def _do(conn) -> int:
        _emit(args, observe.list_skills(conn))
        return 0
    return _run_read(args, _do)


def cmd_show(args) -> int:
    def _do(conn) -> int:
        detail = observe.show_skill(conn, args.name)
        if not detail:
            print(f"未找到 skill: {args.name}")
            return 1
        _emit(args, detail)
        return 0
    return _run_read(args, _do)


def cmd_usage(args) -> int:
    def _do(conn) -> int:
        _emit(args, observe.usage(conn, args.name))
        return 0
    return _run_read(args, _do)


def cmd_pending(args) -> int:
    def _do(conn) -> int:
        _emit(args, cli_pending.list_pending(conn))
        return 0
    return _run_read(args, _do)


def _add_data_dir(p: argparse.ArgumentParser) -> None:
    p.add_argument("--data-dir", default=None, help="数据目录（默认 .distiller-data）")


def _add_json(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", action="store_true", help="以 JSON 输出")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="distiller", description="员工蒸馏器 MVP")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init", help="初始化数据目录与 SQLite schema")
    _add_data_dir(pi)
    pi.set_defaults(func=cmd_init)

    pls = sub.add_parser("ls", help="列出库里的 skill")
    _add_data_dir(pls)
    _add_json(pls)
    pls.set_defaults(func=cmd_ls)

    psh = sub.add_parser("show", help="看单个 skill 详情（分支/质量/契约）")
    psh.add_argument("name", help="skill 名")
    _add_data_dir(psh)
    _add_json(psh)
    psh.set_defaults(func=cmd_show)

    pu = sub.add_parser("usage", help="看某 skill 的调用历史")
    pu.add_argument("name", help="skill 名")
    _add_data_dir(pu)
    _add_json(pu)
    pu.set_defaults(func=cmd_usage)

    pp = sub.add_parser("pending", help="列出待审的候选")
    _add_data_dir(pp)
    _add_json(pp)
    pp.set_defaults(func=cmd_pending)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
