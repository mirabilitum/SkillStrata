"""T0.2 — SQLite schema（经 Codex M0 审核回灌）。

设计要点：
- candidates 用显式 `stage_rank`（整数）+ CHECK，断点续接绝不用字符串字典序比较。
- `contract_signatures` = candidate/branch 级契约签名索引（M4 判同 / M6 warm-start 检索靠它）。
- `branch_versions` = 显式迭代/版本轴，含 scope(branch/shared/skill) + snapshot_refs。
- `usage_events` 与迭代轴分开（别拿每次调用污染年轮）。
- 团队预留字段（created_by/visibility/dedup_key/requires_host_capability）入 schema 不驱动行为。
- `r_miss` 作用域收紧：全 scope 复合索引，调用侧只允许全命中。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .contracts import LIFECYCLE, STAGE_RANK

SCHEMA_VERSION = 2

_STAGE_LIST = ", ".join(f"'{s}'" for s in STAGE_RANK)
_LIFECYCLE_LIST = ", ".join(f"'{s}'" for s in LIFECYCLE)

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS candidates (
    id                       TEXT PRIMARY KEY,
    purpose_guess            TEXT,
    stage                    TEXT NOT NULL DEFAULT 'discovered' CHECK(stage IN ({_STAGE_LIST})),
    stage_rank               INTEGER NOT NULL DEFAULT 10,
    lifecycle                TEXT NOT NULL DEFAULT 'raw' CHECK(lifecycle IN ({_LIFECYCLE_LIST})),
    determinism              TEXT NOT NULL DEFAULT 'deterministic',
    input_profile            TEXT,
    branch_identity          TEXT,    -- json
    source_trace_ids         TEXT,    -- json
    pipeline_status          TEXT NOT NULL DEFAULT 'active',  -- active|deferred|rejected
    deferred_reason          TEXT,    -- dependency|nondeterministic|chain|incomplete_association
    result_status            TEXT,
    exit_code                INTEGER,
    context                  TEXT,    -- json {{task_id,cwd,session_id,source_ref}}
    replay_pass              INTEGER,
    output_pass              INTEGER,
    requires_host_capability TEXT,    -- json（Q6 系统依赖搁置）
    dedup_key                TEXT,    -- 团队预留：跨人去重
    created_by               TEXT,    -- 团队预留
    visibility               TEXT DEFAULT 'hidden',
    created_at               TEXT,
    updated_at               TEXT
);

CREATE TABLE IF NOT EXISTS contract_signatures (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type           TEXT NOT NULL,   -- candidate | branch | skill
    entity_id             TEXT NOT NULL,
    skill_name            TEXT,
    branch_key            TEXT,
    signature_hash        TEXT,
    contract_json         TEXT,
    behavior_signature_json TEXT,
    branch_identity_json  TEXT,
    purpose_embedding_ref TEXT,
    code_evidence_ref     TEXT,
    schema_version        INTEGER,
    created_at            TEXT
);

CREATE TABLE IF NOT EXISTS skills (
    name        TEXT PRIMARY KEY,
    purpose     TEXT,
    when_to_use TEXT,
    contract    TEXT,    -- json
    tags        TEXT,    -- json
    determinism TEXT DEFAULT 'deterministic',
    status      TEXT DEFAULT 'promoted',
    host_native TEXT,    -- json
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
    active_impl_ref          TEXT,    -- best-of-N 只切 active
    active_version           INTEGER DEFAULT 1,
    retained_impls           TEXT,    -- json：全保留，不删兄弟
    is_thin_wrapper          INTEGER DEFAULT 0,
    fixtures_ref             TEXT,
    requires_host_capability TEXT,    -- json
    UNIQUE(skill_name, key)
);

CREATE TABLE IF NOT EXISTS branch_versions (   -- 显式迭代/版本轴（含 shared scope）
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name      TEXT NOT NULL,
    scope           TEXT NOT NULL DEFAULT 'branch',  -- branch|shared|skill
    branch_key      TEXT,
    version         INTEGER NOT NULL,
    change          TEXT,
    regression      TEXT,    -- pass|fail
    regression_detail TEXT,
    snapshot_refs   TEXT,    -- json 数组
    ts              TEXT,
    UNIQUE(skill_name, scope, branch_key, version)
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
CREATE INDEX IF NOT EXISTS idx_candidates_dedup ON candidates(dedup_key);
CREATE INDEX IF NOT EXISTS idx_contract_sig_hash ON contract_signatures(signature_hash);
CREATE INDEX IF NOT EXISTS idx_contract_sig_entity ON contract_signatures(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_contract_sig_skill ON contract_signatures(skill_name, branch_key);
CREATE INDEX IF NOT EXISTS idx_branches_skill   ON branches(skill_name);
CREATE INDEX IF NOT EXISTS idx_usage_skill      ON usage_events(skill_name);
CREATE INDEX IF NOT EXISTS idx_rmiss_scope
    ON r_miss(skill_name, branch_key, contract_slice, version, env_fingerprint, failure_class);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def set_processing_stage(conn: sqlite3.Connection, candidate_id: str, stage: str) -> None:
    """唯一更新入口：同步写 stage 与 stage_rank，杜绝二者漂移（Codex P2.5）。"""
    if stage not in STAGE_RANK:
        raise ValueError(f"unknown stage: {stage}")
    conn.execute(
        "UPDATE candidates SET stage=?, stage_rank=?, updated_at=? WHERE id=?",
        (stage, STAGE_RANK[stage], _now(), candidate_id),
    )
    conn.commit()
