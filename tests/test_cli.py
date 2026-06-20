"""distiller init 端到端测试。"""
from distiller import cli, db, paths


def test_init_creates_layout_and_db(tmp_path, capsys):
    rc = cli.main(["init", "--data-dir", str(tmp_path / "d")])
    assert rc == 0
    root = tmp_path / "d"
    for d in paths.DATA_DIRS:
        assert (root / d).is_dir()
    assert paths.db_path(root).exists()
    conn = db.connect(paths.db_path(root))
    try:
        assert db.schema_version(conn) == db.SCHEMA_VERSION
    finally:
        conn.close()
    assert "initialized" in capsys.readouterr().out
