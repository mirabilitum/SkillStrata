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
