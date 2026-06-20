"""T0.1 目录布局 + T0.2 SQLite schema 测试。"""
from distiller import db, paths


def test_ensure_layout_creates_dirs(tmp_path):
    root = paths.ensure_layout(tmp_path / "d")
    for d in paths.DATA_DIRS:
        assert (root / d).is_dir()
    # 幂等
    paths.ensure_layout(root)


def test_schema_applies_and_versioned(tmp_path):
    root = paths.ensure_layout(tmp_path / "d")
    conn = db.connect(paths.db_path(root))
    try:
        db.apply_schema(conn)
        assert db.schema_version(conn) == db.SCHEMA_VERSION
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for t in ("candidates", "skills", "branches", "branch_versions",
                  "lineage", "usage_events", "quality_rollup", "judge_cache", "r_miss"):
            assert t in names
    finally:
        conn.close()


def test_apply_schema_idempotent(tmp_path):
    root = paths.ensure_layout(tmp_path / "d")
    conn = db.connect(paths.db_path(root))
    try:
        db.apply_schema(conn)
        db.apply_schema(conn)  # 不应报错
        assert db.schema_version(conn) == db.SCHEMA_VERSION
    finally:
        conn.close()


def test_candidate_stage_rank_query_not_string_compare(tmp_path):
    """断点续接查询用 stage_rank 整数，不用字符串。"""
    root = paths.ensure_layout(tmp_path / "d")
    conn = db.connect(paths.db_path(root))
    try:
        db.apply_schema(conn)
        conn.executemany(
            "INSERT INTO candidates(id, stage, stage_rank) VALUES(?,?,?)",
            [("a", "classified", 70), ("b", "composed", 80), ("c", "replayed", 30)],
        )
        conn.commit()
        unfinished = [r["id"] for r in conn.execute(
            "SELECT id FROM candidates WHERE stage_rank < 80 ORDER BY stage_rank")]
        assert unfinished == ["c", "a"]  # replayed(30), classified(70)
    finally:
        conn.close()
