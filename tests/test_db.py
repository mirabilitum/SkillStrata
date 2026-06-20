"""T0.1 目录布局 + T0.2 SQLite schema 测试。"""
from distiller import contracts as c
from distiller import db, paths


def test_ensure_layout_creates_dirs(tmp_path):
    root = paths.ensure_layout(tmp_path / "d")
    for d in paths.DATA_DIRS:
        assert (root / d).is_dir()
    paths.ensure_layout(root)  # 幂等


def _fresh_db(tmp_path):
    root = paths.ensure_layout(tmp_path / "d")
    conn = db.connect(paths.db_path(root))
    db.apply_schema(conn)
    return conn


def test_schema_applies_and_has_all_tables(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        assert db.schema_version(conn) == db.SCHEMA_VERSION
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for t in ("candidates", "contract_signatures", "skills", "branches",
                  "branch_versions", "lineage", "usage_events", "quality_rollup",
                  "judge_cache", "r_miss"):
            assert t in names
    finally:
        conn.close()


def test_key_columns_present(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        def cols(table):
            return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        assert {"stage_rank", "pipeline_status", "deferred_reason", "input_profile",
                "dedup_key", "context"} <= cols("candidates")
        assert {"scope", "snapshot_refs", "regression_detail"} <= cols("branch_versions")
        assert {"active_impl_ref", "retained_impls"} <= cols("branches")
        assert {"behavior_signature_json", "signature_hash"} <= cols("contract_signatures")
    finally:
        conn.close()


def test_apply_schema_idempotent(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        db.apply_schema(conn)  # 二次不报错
        assert db.schema_version(conn) == db.SCHEMA_VERSION
    finally:
        conn.close()


def test_set_processing_stage_syncs_rank(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        conn.execute("INSERT INTO candidates(id) VALUES('a')")
        conn.commit()
        db.set_processing_stage(conn, "a", "contract_extracted")
        row = conn.execute("SELECT stage, stage_rank FROM candidates WHERE id='a'").fetchone()
        assert row["stage"] == "contract_extracted"
        assert row["stage_rank"] == c.STAGE_RANK["contract_extracted"] == 50
    finally:
        conn.close()


def test_stage_check_rejects_bad_value(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        import sqlite3
        try:
            conn.execute("INSERT INTO candidates(id, stage) VALUES('x','bogus')")
            conn.commit()
            assert False, "CHECK 应拒绝非法 stage"
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.close()


def test_unfinished_query_uses_rank_not_string(tmp_path):
    conn = _fresh_db(tmp_path)
    try:
        for cid, stage in [("a", "classified"), ("b", "composed"), ("c", "replayed")]:
            conn.execute("INSERT INTO candidates(id) VALUES(?)", (cid,))
            db.set_processing_stage(conn, cid, stage)
        unfinished = [r["id"] for r in conn.execute(
            "SELECT id FROM candidates WHERE stage_rank < 80 ORDER BY stage_rank")]
        assert unfinished == ["c", "a"]  # replayed(30), classified(70)
    finally:
        conn.close()
