"""持久化写路径 — 把内存产物（Candidate / SkillManifest / Branch）落进 SQLite。

复审（2026-07-04）发现的 P0 缺口：composer 只在内存产出 SkillManifest，
全仓库无 `INSERT INTO skills/branches/candidates`，读侧（observe/mcp/warmstart）
建立在空表之上。本模块补齐这条写路径，并提供 load_manifest 反向重建，
供 orchestrator 在 new_branch / iteration 时读回已有 skill。

设计边界：
  - composer.py 仍只改内存（其 docstring 契约不变）；落库集中在这里。
  - 幂等：同 id/name 重复写 = UPSERT，不重复插入。
  - 只依赖标准库 + contracts；不引入第三方。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from .contracts import (
    Branch,
    Candidate,
    ImplRef,
    SkillManifest,
    to_dict,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# Candidate → candidates 表
# --------------------------------------------------------------------------- #

def upsert_candidate(conn: sqlite3.Connection, cand: Candidate) -> None:
    """把 Candidate 的元数据 + 流水线状态落库（幂等，按 id UPSERT）。

    注意：artifacts 走 artifact store 引用，不入 candidates 表（schema 无该列）。
    """
    now = _now()
    context_json = _dumps(to_dict(cand.context)) if cand.context else None
    conn.execute(
        """
        INSERT INTO candidates
            (id, purpose_guess, stage, stage_rank, lifecycle, determinism,
             input_profile, branch_identity, source_trace_ids, pipeline_status,
             deferred_reason, result_status, exit_code, context,
             replay_pass, output_pass, requires_host_capability,
             dedup_key, created_by, visibility, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            purpose_guess=excluded.purpose_guess,
            stage=excluded.stage,
            stage_rank=excluded.stage_rank,
            lifecycle=excluded.lifecycle,
            determinism=excluded.determinism,
            input_profile=excluded.input_profile,
            branch_identity=excluded.branch_identity,
            source_trace_ids=excluded.source_trace_ids,
            pipeline_status=excluded.pipeline_status,
            deferred_reason=excluded.deferred_reason,
            result_status=excluded.result_status,
            exit_code=excluded.exit_code,
            context=excluded.context,
            replay_pass=excluded.replay_pass,
            output_pass=excluded.output_pass,
            requires_host_capability=excluded.requires_host_capability,
            updated_at=excluded.updated_at
        """,
        (
            cand.id,
            cand.purpose_guess,
            cand.stage,
            cand.stage_rank,
            cand.lifecycle,
            cand.determinism,
            cand.input_profile,
            _dumps(cand.branch_identity) if cand.branch_identity else None,
            _dumps(cand.source_trace_ids) if cand.source_trace_ids else None,
            cand.pipeline_status,
            cand.deferred_reason or None,
            cand.result_status or None,
            cand.exit_code,
            context_json,
            None if cand.replay_pass is None else int(cand.replay_pass),
            None if cand.output_pass is None else int(cand.output_pass),
            _dumps(cand.requires_host_capability) if cand.requires_host_capability else None,
            cand.dedup_key or None,
            None,
            "hidden",
            now,
            now,
        ),
    )
    conn.commit()


# --------------------------------------------------------------------------- #
# SkillManifest / Branch → skills + branches 表
# --------------------------------------------------------------------------- #

def upsert_skill(
    conn: sqlite3.Connection,
    manifest: SkillManifest,
    *,
    status: str = "promoted",
) -> None:
    """把 SkillManifest 及其 branches 落库（幂等）。

    读侧（warmstart / mcp）以 status='promoted' 为准；通过 gate 的技能
    默认以 promoted 落库，但 visibility 仍为 manifest 值（compose 默认 hidden）——
    可见性升级由 review.auto_upgrade_quality 按复用价值驱动（价值靠复用确认）。
    """
    now = _now()
    conn.execute(
        """
        INSERT INTO skills
            (name, purpose, when_to_use, contract, tags, determinism, status,
             host_native, visibility, created_by, dedup_key, quality, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            purpose=excluded.purpose,
            when_to_use=excluded.when_to_use,
            contract=excluded.contract,
            tags=excluded.tags,
            determinism=excluded.determinism,
            host_native=excluded.host_native
        """,
        (
            manifest.name,
            manifest.purpose,
            manifest.when_to_use,
            _dumps(manifest.contract),
            _dumps(manifest.tags),
            manifest.determinism,
            status,
            _dumps(manifest.host_native),
            manifest.visibility,
            manifest.created_by or None,
            manifest.dedup_key or None,
            _dumps(manifest.quality),
            now,
        ),
    )
    for branch in manifest.branches:
        _upsert_branch(conn, manifest.name, branch)
    conn.commit()


def _upsert_branch(conn: sqlite3.Connection, skill_name: str, branch: Branch) -> None:
    conn.execute(
        """
        INSERT INTO branches
            (skill_name, key, active_impl_ref, active_version, retained_impls,
             is_thin_wrapper, fixtures_ref, requires_host_capability)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(skill_name, key) DO UPDATE SET
            active_impl_ref=excluded.active_impl_ref,
            active_version=excluded.active_version,
            retained_impls=excluded.retained_impls,
            is_thin_wrapper=excluded.is_thin_wrapper,
            fixtures_ref=excluded.fixtures_ref,
            requires_host_capability=excluded.requires_host_capability
        """,
        (
            skill_name,
            branch.key,
            branch.active_impl_ref,
            branch.active_version,
            _dumps([to_dict(i) for i in branch.retained_impls]),
            int(branch.is_thin_wrapper),
            branch.fixtures_ref,
            _dumps(branch.requires_host_capability) if branch.requires_host_capability else None,
        ),
    )


# --------------------------------------------------------------------------- #
# 反向：skills + branches → SkillManifest（供 new_branch / iteration 读回）
# --------------------------------------------------------------------------- #

def load_manifest(conn: sqlite3.Connection, name: str) -> SkillManifest | None:
    """从库里重建 SkillManifest（含 branches），未找到返回 None。"""
    row = conn.execute("SELECT * FROM skills WHERE name = ?", (name,)).fetchone()
    if row is None:
        return None
    d = dict(row)

    branch_rows = conn.execute(
        "SELECT * FROM branches WHERE skill_name = ? ORDER BY id", (name,)
    ).fetchall()
    branches: list[Branch] = []
    for br in branch_rows:
        b = dict(br)
        retained = _loads(b.get("retained_impls")) or []
        branches.append(
            Branch(
                key=b["key"],
                active_impl_ref=b.get("active_impl_ref") or "",
                active_version=b.get("active_version") or 1,
                retained_impls=[ImplRef(**i) for i in retained],
                is_thin_wrapper=bool(b.get("is_thin_wrapper")),
                fixtures_ref=b.get("fixtures_ref") or "",
                requires_host_capability=_loads(b.get("requires_host_capability")) or [],
            )
        )

    return SkillManifest(
        name=d["name"],
        purpose=d.get("purpose") or "",
        when_to_use=d.get("when_to_use") or "",
        contract=_loads(d.get("contract")) or {},
        tags=_loads(d.get("tags")) or [],
        branches=branches,
        determinism=d.get("determinism") or "deterministic",
        quality=_loads(d.get("quality")) or {},
        host_native=_loads(d.get("host_native")) or {},
        created_by=d.get("created_by") or "",
        visibility=d.get("visibility") or "hidden",
        dedup_key=d.get("dedup_key") or "",
    )


def _loads(val):
    if val is None or val == "":
        return None
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return None
