"""T0.2 — SQLite schema（元数据 / 索引 / R_miss / lineage / 迭代轴）。

设计要点：
- candidates 用显式 `stage_rank`（整数），断点续接查询绝不用字符串字典序比较。
- `branch_versions` = 显式迭代/版本轴（不隐含在 lineage 里，见 Codex 审核）。
- `usage_events` 与迭代轴分开（别拿每次调用污染年轮）。
- 团队预留字段（created_by/visibility/dedup_key/requires_host_capability）入 schema 不驱动行为。
- `r_miss` 作用域收紧：skill+branch+contract_slice+version+env+failure_class。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS candidates (
    id                       TEXT PRIMARY KEY,
    purpose_guess            TEXT,
    stage                    TEXT NOT NULL DEFAULT 'discovered',
    stage_rank               INTEGER NOT NULL DEFAULT 10,   -- 显式编号，禁字符串比较
    lifecycle                TEXT NOT NULL DEFAULT 'raw',
    determinism              TEXT NOT NULL DEFAULT 'deterministic',
    branch_identity          TEXT,    -- json
    source_trace_ids         TEXT,    -- json
    replay_pass              INTEGER, -- 0/1/null
    output_pass              INTEGER,
    requires_host_capability TEXT,    -- json（Q6 系统依赖搁置）
    created_by               TEXT,    -- 团队预留
    visibility               TEXT DEFAULT 'hidden',  -- 团队预留
    created_at               TEXT,
    updated_at               TEXT
);

CREATE TABLE IF NOT EXISTS skills (
    name        TEXT PRIMARY KEY,
    purpose     TEXT,
    when_to_use TEXT,
    contract    TEXT,    -- json
    determinism TEXT DEFAULT 'deterministic',
    status      TEXT DEFAULT 'promoted',
    visibility  TEXT DEFAULT 'hidden',  -- 团队预留
    created_by  TEXT,                   -- 团队预留
    dedup_key   TEXT,                   -- 团队预留：跨人去重
    quality     TEXT,    -- json
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS branches (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name               TEXT NOT NULL,
    key                      TEXT NOT NULL,
    impl_ref                 TEXT,
    is_thin_wrapper          INTEGER DEFAULT 0,
    active                   INTEGER DEFAULT 1,   -- stable_active；ambiguous 时新实现进 provisional
    fixtures_ref             TEXT,
    requires_host_capability TEXT,  -- json
    UNIQUE(skill_name, key)
);

CREATE TABLE IF NOT EXISTS branch_versions (   -- 显式迭代/版本轴
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name   TEXT NOT NULL,
    branch_key   TEXT,
    version      INTEGER NOT NULL,
    change       TEXT,
    regression   TEXT,    -- pass|fail
    snapshot_ref TEXT,
    ts           TEXT
);

CREATE TABLE IF NOT EXISTS lineage (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    kind    TEXT,    -- merge|split|promote|deprecate|iterate|unmerge
    subject TEXT,
    detail  TEXT,    -- json
    ts      TEXT
);

CREATE TABLE IF NOT EXISTS usage_events (   -- 与迭代轴分开，别污染年轮
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name    TEXT,
    branch_key    TEXT,
    host_agent    TEXT,
    status        TEXT,    -- success|error
    input_summary TEXT,
    warmstart_hit INTEGER DEFAULT 0,
    ts            TEXT
);

CREATE TABLE IF NOT EXISTS quality_rollup (
    skill_name   TEXT PRIMARY KEY,
    reuse_count  INTEGER DEFAULT 0,
    success_rate REAL DEFAULT 0.0,
    last_used    TEXT
);

CREATE TABLE IF NOT EXISTS judge_cache (
    key            TEXT PRIMARY KEY,  -- hash(contract pair + behavior + 版本 + model)
    result         TEXT,
    model          TEXT,
    prompt_version TEXT,
    schema_version TEXT,
    ts             TEXT
);

CREATE TABLE IF NOT EXISTS r_miss (   -- 收紧作用域，非目的级黑名单
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name      TEXT,
    branch_key      TEXT,
    contract_slice  TEXT,
    version         INTEGER,
    env_fingerprint TEXT,
    failure_class   TEXT,  -- missing_dependency|output_not_pass|timeout|crash
    ts              TEXT
);

CREATE INDEX IF NOT EXISTS idx_candidates_stage ON candidates(stage_rank, lifecycle);
CREATE INDEX IF NOT EXISTS idx_branches_skill   ON branches(skill_name);
CREATE INDEX IF NOT EXISTS idx_usage_skill      ON usage_events(skill_name);
CREATE INDEX IF NOT EXISTS idx_rmiss_scope      ON r_miss(skill_name, branch_key);
"""


def connect(db_file: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()


def schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    return int(row[0]) if row else 0
