"""CLI 读命令端到端测试（复审 P1-a / P3-b）。

此前只有 init 有测试，README 宣称的 ls/show/usage/pending 既无实现也无测试。
这里通过 cli.main([...]) 驱动全部公开命令，覆盖空库与有数据两种情形。
"""
from distiller import cli, db, paths, warmstart


def _init(tmp_path) -> str:
    data_dir = str(tmp_path / "d")
    assert cli.main(["init", "--data-dir", data_dir]) == 0
    return data_dir


def _seed_skill(data_dir: str, name: str = "doc-to-markdown") -> None:
    """直接落一个 promoted skill + 一次调用，供读命令有内容可显示。"""
    conn = db.connect(paths.db_path(paths.ensure_layout(data_dir)))
    try:
        conn.execute(
            """INSERT INTO skills (name, purpose, status, visibility, created_at)
               VALUES (?, 'doc to markdown', 'promoted', 'searchable', '2026-07-04')""",
            (name,),
        )
        conn.execute(
            "INSERT INTO branches (skill_name, key, active_impl_ref) VALUES (?, 'pdf', './b.py')",
            (name,),
        )
        conn.commit()
        warmstart.record_usage(conn, name, "pdf", "success")
    finally:
        conn.close()


def test_ls_empty(tmp_path, capsys):
    data_dir = _init(tmp_path)
    assert cli.main(["ls", "--data-dir", data_dir]) == 0
    assert "(空)" in capsys.readouterr().out


def test_ls_lists_skill(tmp_path, capsys):
    data_dir = _init(tmp_path)
    _seed_skill(data_dir)
    assert cli.main(["ls", "--data-dir", data_dir]) == 0
    assert "doc-to-markdown" in capsys.readouterr().out


def test_show_found_and_not_found(tmp_path, capsys):
    data_dir = _init(tmp_path)
    _seed_skill(data_dir)
    assert cli.main(["show", "doc-to-markdown", "--data-dir", data_dir]) == 0
    out = capsys.readouterr().out
    assert "doc-to-markdown" in out

    rc = cli.main(["show", "nope", "--data-dir", data_dir])
    assert rc == 1
    assert "未找到" in capsys.readouterr().out


def test_usage_shows_history(tmp_path, capsys):
    data_dir = _init(tmp_path)
    _seed_skill(data_dir)
    assert cli.main(["usage", "doc-to-markdown", "--data-dir", data_dir]) == 0
    assert "success" in capsys.readouterr().out


def test_pending_empty(tmp_path, capsys):
    data_dir = _init(tmp_path)
    assert cli.main(["pending", "--data-dir", data_dir]) == 0
    assert "(空)" in capsys.readouterr().out


def test_json_output(tmp_path, capsys):
    data_dir = _init(tmp_path)
    _seed_skill(data_dir)
    capsys.readouterr()  # 清掉 init 的输出，只断言 ls --json
    assert cli.main(["ls", "--data-dir", data_dir, "--json"]) == 0
    out = capsys.readouterr().out
    assert out.strip().startswith("[")
    assert "doc-to-markdown" in out


# --------------------------------------------------------------------------- #
# 未初始化数据目录：只读命令干净失败，不隐式建库、不抛 traceback（复审 P2）
# --------------------------------------------------------------------------- #

import pytest


@pytest.mark.parametrize("cmd", [
    ["ls"],
    ["show", "x"],
    ["usage", "x"],
    ["pending"],
])
def test_read_cmd_uninitialized_fails_cleanly(tmp_path, capsys, cmd):
    missing = str(tmp_path / "never-inited")
    rc = cli.main(cmd + ["--data-dir", missing])
    assert rc != 0
    assert "init" in capsys.readouterr().out.lower()
    # 严格只读：不应隐式创建数据目录或空库
    from pathlib import Path
    assert not Path(missing).exists()


# --------------------------------------------------------------------------- #
# 已存在但损坏/未初始化的 DB 文件：仍友好失败，不 traceback（复审三次 P2-1）
# --------------------------------------------------------------------------- #

import sqlite3
from pathlib import Path


@pytest.mark.parametrize("cmd", [["ls"], ["show", "x"], ["usage", "x"], ["pending"]])
def test_read_cmd_empty_db_file_fails_cleanly(tmp_path, capsys, cmd):
    """meta.sqlite 存在但是空文件（无 meta 表）→ 友好失败，不抛 sqlite OperationalError。"""
    data_dir = tmp_path / "bad"
    data_dir.mkdir()
    sqlite3.connect(str(data_dir / paths.DB_FILENAME)).close()  # 空库，无 schema

    rc = cli.main(cmd + ["--data-dir", str(data_dir)])
    assert rc != 0
    out = capsys.readouterr().out.lower()
    assert "init" in out or "无效" in out or "损坏" in out


def test_read_cmd_meta_without_schema_version_fails_cleanly(tmp_path, capsys):
    """meta 表存在但没有 schema_version 行 → schema_version()==0 → 友好失败。"""
    data_dir = tmp_path / "half"
    data_dir.mkdir()
    conn = sqlite3.connect(str(data_dir / paths.DB_FILENAME))
    conn.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    conn.close()

    rc = cli.main(["ls", "--data-dir", str(data_dir)])
    assert rc != 0
    out = capsys.readouterr().out.lower()
    assert "init" in out or "无效" in out or "损坏" in out
