"""Orchestrator — 把各阶段焊成一条流水线（复审 2026-07-04 P0 缺口修复）。

背景：M1-M7 各模块单测齐全，但从未被组装成一条线；无 daemon/orchestrator；
composer 产物无落库写路径。本模块补上这根主脊：

    events → discovery → gate0 → replay → output_gate
           → contract_extract → classify → composer → persist

设计原则（对照 v0.4 / 契约引擎设计）：
  - 按 STAGE_RANK 显式推进 processing_stage，每步落库（断点可续）。
  - deferred / rejected 显式搁置，不静默丢（Q6）：
      · gate0 判 deferred（系统依赖 / 非确定性）→ 落库 candidate，停在 gate0_done。
      · replay / output_gate 未过 → pipeline_status=rejected，落库，不产 skill。
  - 三选一（classify）驱动 composer：
      new_skill / new_branch / iteration → 落 skills+branches；
      duplicate / ambiguous → 不改库（ambiguous 留待 review pending）。
  - MVP 用规则版 judge（classify.judge_purpose），无 LLM 依赖。

只依赖标准库 + distiller 内部模块。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import (
    classify,
    composer,
    contract_extract,
    db,
    discovery,
    gate0,
    output_gate,
    persist,
    replay,
)
from .contracts import (
    Candidate,
    ContractSignature,
    EnrichedToolEvent,
)


@dataclass
class CandidateOutcome:
    """单个候选走完流水线后的结局（可观测 / 可断言）。"""
    candidate_id: str
    terminal_stage: str
    pipeline_status: str            # active | deferred | rejected
    classification: str = ""        # new_skill | new_branch | iteration | duplicate | ambiguous | ""
    skill_name: str = ""
    branch_key: str = ""
    reason: str = ""                # 搁置 / 拒绝原因，便于诊断


@dataclass
class PipelineResult:
    outcomes: list[CandidateOutcome] = field(default_factory=list)

    @property
    def promoted_skills(self) -> list[str]:
        return sorted({o.skill_name for o in self.outcomes if o.skill_name})

    def by_status(self, status: str) -> list[CandidateOutcome]:
        return [o for o in self.outcomes if o.pipeline_status == status]


# --------------------------------------------------------------------------- #
# 单候选驱动
# --------------------------------------------------------------------------- #

def _read_code(entry_ref: str) -> str:
    """读入口脚本源码供 gate0 静态扫描；读不到就空串（gate0 会宽松放行）。"""
    if not entry_ref:
        return ""
    p = Path(entry_ref)
    try:
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    return ""


def _input_text(cand: Candidate) -> str:
    """取第一个输入文件的文本，供 output_gate 独立测量覆盖率（防循环）。"""
    for a in cand.input_artifacts:
        if not a.path:
            continue
        p = Path(a.path)
        try:
            if p.is_file():
                return p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return ""


def process_candidate(
    conn: sqlite3.Connection,
    cand: Candidate,
    *,
    replay_timeout: int = 30,
) -> CandidateOutcome:
    """把单个候选推过 gate0 → replay → output_gate → 契约 → 三选一 → composer。

    每个阶段转移都 persist，落库即断点。返回结局对象。
    """
    # --- Gate0：确定性 / 系统依赖静态探测 ---
    signals = gate0.probe_determinism(cand, _read_code(cand.entry_ref))
    cand = gate0.apply_gate0(cand, signals)
    cand.stage = "gate0_done"
    persist.upsert_candidate(conn, cand)

    if cand.pipeline_status == "deferred":
        # 显式搁置，不静默丢；候选留库待人审 / 环境补齐后重放。
        return CandidateOutcome(
            candidate_id=cand.id,
            terminal_stage=cand.stage,
            pipeline_status="deferred",
            reason=cand.deferred_reason or "deferred",
        )

    # --- Replay：沙箱重放，拿 stdout markdown ---
    input_path = cand.input_artifacts[0].path if cand.input_artifacts else ""
    rp = replay.replay(cand.entry_ref, input_path, timeout=replay_timeout)
    replay_ok = rp.get("exit_code") == 0 and bool(rp.get("stdout_md", "").strip())
    cand.replay_pass = replay_ok
    cand.stage = "replayed"
    if not replay_ok:
        cand.pipeline_status = "rejected"
        persist.upsert_candidate(conn, cand)
        return CandidateOutcome(
            candidate_id=cand.id,
            terminal_stage=cand.stage,
            pipeline_status="rejected",
            reason=f"replay_failed(exit={rp.get('exit_code')})",
        )
    persist.upsert_candidate(conn, cand)

    # --- Output Gate：属性验证 + behavior_signature ---
    output_md = rp.get("stdout_md", "")
    gate_pass, behavior = output_gate.output_gate(cand, output_md, _input_text(cand))
    cand.output_pass = gate_pass
    cand.stage = "output_gated"
    if not gate_pass:
        cand.pipeline_status = "rejected"
        persist.upsert_candidate(conn, cand)
        return CandidateOutcome(
            candidate_id=cand.id,
            terminal_stage=cand.stage,
            pipeline_status="rejected",
            reason="output_gate_failed",
        )
    persist.upsert_candidate(conn, cand)

    # --- 契约抽取 + 落 contract_signatures（判同检索靠它）---
    sig: ContractSignature = contract_extract.extract_contract(cand, behavior)
    contract_extract.store_contract(conn, "candidate", cand.id, sig)
    cand.stage = "contract_extracted"
    persist.upsert_candidate(conn, cand)

    # --- 三选一：judge_purpose → classify ---
    nearest = contract_extract.find_nearest(conn, sig)
    relation = classify.judge_purpose(cand, sig, nearest)
    target_behavior = _nearest_behavior(nearest, relation)
    decision = classify.classify(cand, sig, relation, target_behavior)
    cand.stage = "classified"
    persist.upsert_candidate(conn, cand)

    outcome = _apply_decision(conn, cand, sig, relation, decision)
    cand.stage = "composed"
    persist.upsert_candidate(conn, cand)
    return outcome


def _nearest_behavior(nearest, relation):
    """same_branch 时取目标分支的 behavior_signature（供支配比较）。"""
    from .contracts import BehaviorSignature
    if relation.get("relation") != "same_branch":
        return None
    target_skill = relation.get("target_skill", "")
    target_branch = relation.get("target_branch", "")
    for entry in nearest:
        if entry.get("skill_name") == target_skill and entry.get("branch_key") == target_branch:
            bj = entry.get("behavior_signature_json")
            if isinstance(bj, str) and bj:
                import json
                try:
                    return BehaviorSignature(**json.loads(bj))
                except (json.JSONDecodeError, TypeError):
                    return None
    return None


def _branch_key_for(cand: Candidate, sig: ContractSignature) -> str:
    """分支 key = 归一化输入族（同目的不同输入类型 → 不同分支）。"""
    bi = sig.branch_identity or cand.branch_identity or {}
    return bi.get("normalized_input_family") or cand.input_profile or "default"


def _apply_decision(
    conn: sqlite3.Connection,
    cand: Candidate,
    sig: ContractSignature,
    relation: dict,
    decision: str,
) -> CandidateOutcome:
    """据三选一结果驱动 composer + persist。"""
    base = CandidateOutcome(
        candidate_id=cand.id,
        terminal_stage="composed",
        pipeline_status="active",
        classification=decision,
    )

    if decision == "new_skill":
        branch_key = _branch_key_for(cand, sig)
        manifest = composer.compose_new_skill(cand, sig, branch_key)
        persist.upsert_skill(conn, manifest)
        _store_skill_contract(conn, manifest.name, branch_key, sig)
        base.skill_name = manifest.name
        base.branch_key = branch_key
        return base

    target_skill = relation.get("target_skill", "")
    manifest = persist.load_manifest(conn, target_skill) if target_skill else None

    if decision == "new_branch" and manifest is not None:
        branch_key = _branch_key_for(cand, sig)
        existing = {b.key for b in manifest.branches}
        if branch_key in existing:
            # key 撞车：降级为该分支的迭代候选，交由 iteration 语义处理。
            decision = "iteration"
        else:
            composer.add_branch(manifest, cand, sig, branch_key)
            persist.upsert_skill(conn, manifest)
            _store_skill_contract(conn, manifest.name, branch_key, sig)
            base.skill_name = manifest.name
            base.branch_key = branch_key
            return base

    if decision == "iteration" and manifest is not None:
        branch_key = relation.get("target_branch", "") or _branch_key_for(cand, sig)
        new_impl = cand.code_snapshot_ref or cand.entry_ref or ""
        composer.apply_iteration(manifest, branch_key, new_impl)
        persist.upsert_skill(conn, manifest)
        _store_skill_contract(conn, manifest.name, branch_key, sig)
        base.skill_name = manifest.name
        base.branch_key = branch_key
        return base

    # duplicate / ambiguous / 目标缺失：不改库。
    base.pipeline_status = "active"
    base.reason = decision if decision in ("duplicate", "ambiguous") else "no_target"
    base.skill_name = ""
    return base


def _store_skill_contract(
    conn: sqlite3.Connection, skill_name: str, branch_key: str, sig: ContractSignature
) -> None:
    """把契约签名以 entity_type='skill' 落库——find_nearest 只认 skill/branch。

    这让下一个候选能检索到已沉淀的 skill，实现判同 / 迭代闭环。
    """
    contract_extract.store_contract(
        conn, "skill", skill_name, sig, skill_name=skill_name, branch_key=branch_key
    )


# --------------------------------------------------------------------------- #
# 批量入口
# --------------------------------------------------------------------------- #

def run_pipeline(
    conn: sqlite3.Connection,
    events: list[EnrichedToolEvent],
    *,
    replay_timeout: int = 30,
) -> PipelineResult:
    """从一批 enriched 事件跑完整条流水线，返回可断言的 PipelineResult。

    discovery 先把事件关联成候选，再逐个 process_candidate。
    候选按发现顺序串行处理——顺序有意义：先沉淀的 skill 是后来者的判同基线。
    """
    candidates = discovery.discover(events)
    result = PipelineResult()
    for cand in candidates:
        try:
            outcome = process_candidate(conn, cand, replay_timeout=replay_timeout)
        except Exception as exc:  # noqa: BLE001 — 单候选失败不拖垮整批
            cand.pipeline_status = "rejected"
            persist.upsert_candidate(conn, cand)
            outcome = CandidateOutcome(
                candidate_id=cand.id,
                terminal_stage=cand.stage,
                pipeline_status="rejected",
                reason=f"pipeline_error: {type(exc).__name__}: {exc}",
            )
        result.outcomes.append(outcome)
    return result


def run_from_db(
    db_path: str | Path,
    events: list[EnrichedToolEvent],
    *,
    replay_timeout: int = 30,
) -> PipelineResult:
    """便捷入口：自开连接、建 schema、跑流水线、关连接。"""
    conn = db.connect(db_path)
    try:
        db.apply_schema(conn)
        return run_pipeline(conn, events, replay_timeout=replay_timeout)
    finally:
        conn.close()
