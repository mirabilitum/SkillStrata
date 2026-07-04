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

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import (
    artifact_store,
    classify,
    composer,
    contract_extract,
    db,
    discovery,
    gate0,
    judge,
    output_gate,
    persist,
    replay,
    safety,
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
    judge_result: dict | None = None  # API/Rule judge 结构化输出（阶段 4）


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

def _candidate_base_dir(cand: Candidate) -> Path:
    """候选路径的解析基准 = 原始事件的 cwd（真实 trace 里 argv 多为相对路径）。

    无 context.cwd 时退回当前进程 CWD（尽力而为）。
    """
    if cand.context and getattr(cand.context, "cwd", ""):
        return Path(cand.context.cwd)
    return Path.cwd()


def _resolve_candidate_path(cand: Candidate, raw_path: str) -> Path:
    """把候选里的相对路径按事件 cwd 归一为绝对路径（复审 P1）。

    orchestrator 通常不在原始 cwd 下运行——若不归一，gate0 读不到脚本、
    replay 找不到输入、output_gate 覆盖率恒 0，真实候选被错误 reject。
    """
    p = Path(raw_path)
    if p.is_absolute():
        return p.resolve()
    return (_candidate_base_dir(cand) / p).resolve()


def _read_code(cand: Candidate) -> str:
    """读入口脚本源码供 gate0 静态扫描；读不到就空串（gate0 会宽松放行）。"""
    if not cand.entry_ref:
        return ""
    p = _resolve_candidate_path(cand, cand.entry_ref)
    try:
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    return ""


# 可直接读文本测量覆盖率的输入（复审 P2：二进制文档不能当 UTF-8 文本读）。
_TEXTUAL_MEDIA_PREFIXES = ("text/",)
_TEXTUAL_MEDIA_TYPES = frozenset({
    "text/plain", "text/html", "text/markdown", "application/xhtml+xml",
    "application/json", "application/xml", "text/xml",
})
_TEXTUAL_EXTS = frozenset({".txt", ".html", ".htm", ".md", ".xml", ".json", ".csv"})


def _is_textual(artifact) -> bool:
    mt = (artifact.media_type or "").lower()
    if mt.startswith(_TEXTUAL_MEDIA_PREFIXES) or mt in _TEXTUAL_MEDIA_TYPES:
        return True
    ext = Path(artifact.path).suffix.lower()
    return ext in _TEXTUAL_EXTS


def _input_text(cand: Candidate) -> str:
    """取第一个**文本型**输入的文本，供 output_gate 独立测量覆盖率（防循环）。

    复审 P2：PDF/DOCX/XLSX 等二进制文档不能 read_text——读出来是乱码/replacement
    char，coverage 无意义。这类输入返回空串，由 output_gate 走"输入不可测"分支
    （文本型 profile 输入为空 → deferred，而非无解释 fail）。
    """
    for a in cand.input_artifacts:
        if not a.path or not _is_textual(a):
            continue
        p = _resolve_candidate_path(cand, a.path)
        try:
            if p.is_file():
                return p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return ""


# 靠图片/表格结构判定、不需要文本覆盖率的 profile（这些即使 input_text 空也能判）。
_NON_COVERAGE_PROFILES = frozenset({"pdf_scanned", "xlsx_table"})


def _coverage_unmeasurable(cand: Candidate, input_text: str) -> bool:
    """判断"文本覆盖率不可测"：有输入产物、但没有可读文本、且该 profile 靠覆盖率门禁。

    仅当存在二进制输入产物（无文本型可读）时成立；纯粹没有输入产物不算这里的范畴。
    """
    if input_text:
        return False
    if (cand.input_profile or "") in _NON_COVERAGE_PROFILES:
        return False
    has_binary_input = any(a.path and not _is_textual(a) for a in cand.input_artifacts)
    return has_binary_input


def process_candidate(
    conn: sqlite3.Connection,
    cand: Candidate,
    *,
    replay_timeout: int = 30,
    data_dir: Path | None = None,
    _judge: judge.Judge | None = None,
) -> CandidateOutcome:
    """把单个候选推过 gate0 → replay → output_gate → 契约 → 三选一 → composer。

    每个阶段转移都 persist，落库即断点。返回结局对象。

    data_dir 非 None 时，promoted skill 的实现与 fixture 会被快照到数据目录内
    （阶段 2 Artifact Store），branches.active_impl_ref 指向 data-dir 相对路径，
    不再依赖原工作区。

    _judge 非 None 时，在三选一之后用 Judge 生成结构化元数据（purpose/名称/风险），
    不改变 merge 决策，只补充 outcome 与 context（阶段 4 API Judge）。

    异常自处理（复审三次 P2-2）：阶段中途抛错时，用**推进中**的 cand 落 rejected +
    lineage + r_miss——绝不倒退 DB 里已持久化的更高阶段状态，信号里的 stage 也是真实的。
    内层 `_stages` 用 `nonlocal cand` 让 gate0 的 deepcopy 重绑对 except 可见。
    """
    def _stages() -> CandidateOutcome:
        nonlocal cand
        # --- Gate0：确定性 / 系统依赖静态探测 ---
        code_text = _read_code(cand)
        signals = gate0.probe_determinism(cand, code_text)
        cand = gate0.apply_gate0(cand, signals)  # 返回 deepcopy；nonlocal 使其对外层可见
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

        # --- Safety Gate（阶段 3 同步落地）：扫源码防危险操作 ---
        verdict, risks = safety.scan_and_assess(code_text)
        if verdict == "dangerous":
            cand.pipeline_status = "rejected"
            cand.stage = "safety_gated"
            persist.upsert_candidate(conn, cand)
            return CandidateOutcome(
                candidate_id=cand.id,
                terminal_stage=cand.stage,
                pipeline_status="rejected",
                reason=f"safety_dangerous: {','.join(sorted(risks))}",
            )
        if verdict == "review":
            cand.pipeline_status = "deferred"
            cand.deferred_reason = "safety_review"
            cand.stage = "safety_gated"
            cand.requires_host_capability = sorted(
                set(cand.requires_host_capability) | risks
            )
            persist.upsert_candidate(conn, cand)
            return CandidateOutcome(
                candidate_id=cand.id,
                terminal_stage=cand.stage,
                pipeline_status="deferred",
                reason=f"safety_review: {','.join(sorted(risks))}",
            )

        # --- Replay：沙箱重放，拿 stdout markdown ---
        impl_path = _resolve_candidate_path(cand, cand.entry_ref) if cand.entry_ref else ""
        input_path = (
            _resolve_candidate_path(cand, cand.input_artifacts[0].path)
            if cand.input_artifacts and cand.input_artifacts[0].path
            else ""
        )
        rp = replay.replay(str(impl_path), str(input_path), timeout=replay_timeout)
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
        input_text = _input_text(cand)

        # 复审 P2：文本型 profile 靠覆盖率门禁，但输入是二进制文档（无 extractor）时
        # input_text 为空 → 覆盖率不可测。此时显式 deferred（待接入抽取器），
        # 不做无意义的 coverage==0 → fail 误杀。
        if _coverage_unmeasurable(cand, input_text):
            cand.output_pass = None
            cand.stage = "output_gated"
            cand.pipeline_status = "deferred"
            cand.deferred_reason = "unmeasurable_input"
            persist.upsert_candidate(conn, cand)
            return CandidateOutcome(
                candidate_id=cand.id,
                terminal_stage=cand.stage,
                pipeline_status="deferred",
                reason="input_text_unmeasurable",
            )

        gate_pass, behavior = output_gate.output_gate(cand, output_md, input_text)
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
        # 过 Output Gate = 已验证；lifecycle 推进到 verified，供 pending 审查队列可见
        # （复审 P1-pending：此前恒为 raw，pending 永远空）。
        cand.lifecycle = "verified"
        cand.result_status = "success"
        persist.upsert_candidate(conn, cand)

        # --- 契约抽取 + 落 contract_signatures（判同检索靠它）---
        sig: ContractSignature = contract_extract.extract_contract(cand, behavior)
        # 幂等（复审补充 D）：同一候选重复处理不叠加签名行——先清该候选的旧 candidate 级签名。
        conn.execute(
            "DELETE FROM contract_signatures WHERE entity_type='candidate' AND entity_id=?",
            (cand.id,),
        )
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

        # --- Judge（阶段 4）：改善命名/归类/解释，不改 merge 决策 ---
        jr: dict | None = None
        if _judge is not None:
            jr = _judge.judge(cand, sig)
            # 写入 context.source_ref 供 composer/CLI 读取
            if cand.context and hasattr(cand.context, "source_ref"):
                cand.context.source_ref["judge"] = json.dumps(jr, ensure_ascii=False)

        outcome = _apply_decision(
            conn, cand, sig, relation, decision,
            data_dir=data_dir,
            impl_path=str(impl_path) if impl_path else "",
            input_path=str(input_path) if input_path else "",
            output_md=output_md,
        )
        if jr is not None:
            outcome.judge_result = jr
        cand.stage = "composed"
        persist.upsert_candidate(conn, cand)
        return outcome

    try:
        return _stages()
    except Exception as exc:  # noqa: BLE001 — 单候选失败不拖垮整批；用推进中的 cand 落库
        cand.pipeline_status = "rejected"
        persist.upsert_candidate(conn, cand)  # cand 是推进后的副本，不会倒退 stage/lifecycle
        _record_lineage(conn, "pipeline_error", cand.id, {
            "stage": cand.stage,
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
        })
        _record_r_miss(conn, cand, failure_class="crash")
        return CandidateOutcome(
            candidate_id=cand.id,
            terminal_stage=cand.stage,
            pipeline_status="rejected",
            reason=f"pipeline_error: {type(exc).__name__}: {exc}",
        )


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
    *,
    data_dir: Path | None = None,
    impl_path: str = "",
    input_path: str = "",
    output_md: str = "",
) -> CandidateOutcome:
    """据三选一结果驱动 composer + persist，并推进 candidate 的 lifecycle / 可观测信号。

    data_dir 非 None 时，在 persist 前把实现脚本 + fixture 快照到数据目录
    （阶段 2 Artifact Store），branches.active_impl_ref 指向 data-dir 相对路径，
    不再依赖原工作区。

    lifecycle 语义（复审 P1-pending + 补充 A）：
      - new_skill/new_branch/iteration 成功 persist → lifecycle='promoted'（不进 pending）
      - duplicate → 保持 verified（已有更优兄弟，可在 pending 被复核）
      - ambiguous → verified + deferred(ambiguous)，进 pending 待人工 pin
      - no_target（judge 给了 target 但 load 不到）→ 异常路径：deferred(classify_miss) + 记 lineage
    """
    base = CandidateOutcome(
        candidate_id=cand.id,
        terminal_stage="composed",
        pipeline_status="active",
        classification=decision,
    )

    def _snapshot(manifest, branch):
        """尝试快照；失败不阻断主链（artifact_store 是增强，不是门禁）。"""
        if data_dir is None or not impl_path or not Path(impl_path).is_file():
            return
        try:
            new_impl, new_fix = artifact_store.snapshot_promoted(
                data_dir,
                manifest.name,
                branch.key,
                branch.active_version,
                impl_path=impl_path,
                input_fixture_path=input_path if input_path and Path(input_path).is_file() else None,
                output_text=output_md if output_md else None,
            )
            branch.active_impl_ref = new_impl
            branch.fixtures_ref = new_fix
        except OSError:
            pass  # 快照失败不影响 promote 本身

    if decision == "new_skill":
        branch_key = _branch_key_for(cand, sig)
        manifest = composer.compose_new_skill(cand, sig, branch_key)
        if manifest.branches:
            _snapshot(manifest, manifest.branches[0])
        persist.upsert_skill(conn, manifest)
        _store_skill_contract(conn, manifest.name, branch_key, sig)
        cand.lifecycle = "promoted"
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
            new_b = next((b for b in manifest.branches if b.key == branch_key), None)
            if new_b:
                _snapshot(manifest, new_b)
            persist.upsert_skill(conn, manifest)
            _store_skill_contract(conn, manifest.name, branch_key, sig)
            cand.lifecycle = "promoted"
            base.classification = "new_branch"
            base.skill_name = manifest.name
            base.branch_key = branch_key
            return base

    if decision == "iteration" and manifest is not None:
        branch_key = relation.get("target_branch", "") or _branch_key_for(cand, sig)
        new_impl = cand.code_snapshot_ref or cand.entry_ref or ""
        composer.apply_iteration(manifest, branch_key, new_impl)
        # 迭代后取更新后的版本号
        updated_b = next((b for b in manifest.branches if b.key == branch_key), None)
        if updated_b:
            _snapshot(manifest, updated_b)
        persist.upsert_skill(conn, manifest)
        _store_skill_contract(conn, manifest.name, branch_key, sig)
        cand.lifecycle = "promoted"
        base.classification = "iteration"
        base.skill_name = manifest.name
        base.branch_key = branch_key
        return base

    # --- 未沉淀成 skill 的分类：显式落信号，别静默丢 ---
    if decision == "duplicate":
        # 已有更优/相等兄弟：保持 verified（可在 pending 复核），不改可见状态。
        base.reason = "duplicate"
    elif decision == "ambiguous":
        # 行为不可比：进 pending 待人工 pin。
        cand.pipeline_status = "deferred"
        cand.deferred_reason = "ambiguous"
        base.pipeline_status = "deferred"
        base.reason = "ambiguous"
    else:
        # no_target：judge 给了 target_skill 但 load 不到 manifest（数据不一致）——
        # 异常路径，记 lineage 便于追溯（复审补充 A）。
        cand.pipeline_status = "deferred"
        cand.deferred_reason = "classify_miss"
        base.pipeline_status = "deferred"
        base.reason = "no_target"
        _record_lineage(conn, "classify_miss", cand.id, {
            "relation": relation.get("relation", ""),
            "target_skill": target_skill,
            "decision": decision,
        })
    base.skill_name = ""
    return base


def _record_lineage(conn: sqlite3.Connection, kind: str, subject: str, detail: dict) -> None:
    """写一条 lineage，用于异常/降级路径的可观测性（复审补充 A/B）。"""
    conn.execute(
        "INSERT INTO lineage(kind, subject, detail, ts) VALUES (?, ?, ?, ?)",
        (kind, subject, json.dumps(detail, ensure_ascii=False),
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def _store_skill_contract(
    conn: sqlite3.Connection, skill_name: str, branch_key: str, sig: ContractSignature
) -> None:
    """把契约签名以 entity_type='skill' 落库——find_nearest 只认 skill/branch。

    这让下一个候选能检索到已沉淀的 skill，实现判同 / 迭代闭环。
    幂等（复审补充 D）：同 (skill, branch, signature_hash) 只留一条，避免重复处理叠加。
    """
    conn.execute(
        """DELETE FROM contract_signatures
           WHERE entity_type='skill' AND entity_id=? AND branch_key=? AND signature_hash=?""",
        (skill_name, branch_key, sig.signature_hash),
    )
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
    data_dir: Path | None = None,
    _judge: judge.Judge | None = None,
) -> PipelineResult:
    """从一批 enriched 事件跑完整条流水线，返回可断言的 PipelineResult。

    discovery 先把事件关联成候选，再逐个 process_candidate。
    候选按发现顺序串行处理——顺序有意义：先沉淀的 skill 是后来者的判同基线。

    data_dir 非 None 时启用 Artifact Store（阶段 2）。
    _judge 非 None 时启用 API/Rule Judge（阶段 4）。
    """
    candidates = discovery.discover(events)
    result = PipelineResult()
    for cand in candidates:
        try:
            outcome = process_candidate(
                conn, cand, replay_timeout=replay_timeout,
                data_dir=data_dir, _judge=_judge,
            )
        except Exception as exc:  # noqa: BLE001 — 兜底：process_candidate 已自处理内部异常，
            # 这里只接极端情况（如它本身构造失败）。绝不用调用方的旧 cand 覆盖已推进状态
            # （复审三次 P2-2）：仅当 DB 无该候选时才 insert，有则只翻 pipeline_status。
            _mark_rejected_no_rewind(conn, cand)
            _record_lineage(conn, "pipeline_error", cand.id, {
                "stage": cand.stage,
                "error_type": type(exc).__name__,
                "error": str(exc)[:500],
            })
            _record_r_miss(conn, cand, failure_class="crash")
            outcome = CandidateOutcome(
                candidate_id=cand.id,
                terminal_stage=cand.stage,
                pipeline_status="rejected",
                reason=f"pipeline_error: {type(exc).__name__}: {exc}",
            )
        result.outcomes.append(outcome)
    return result


def _mark_rejected_no_rewind(conn: sqlite3.Connection, cand: Candidate) -> None:
    """把候选标 rejected，但**绝不倒退**已持久化的更高阶段（复审三次 P2-2）。

    DB 无该候选 → insert（首阶段就崩）；已有 → 只 UPDATE pipeline_status，不动 stage/lifecycle。
    """
    row = conn.execute("SELECT id FROM candidates WHERE id=?", (cand.id,)).fetchone()
    if row is None:
        cand.pipeline_status = "rejected"
        persist.upsert_candidate(conn, cand)
    else:
        conn.execute(
            "UPDATE candidates SET pipeline_status='rejected', updated_at=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), cand.id),
        )
        conn.commit()


def _record_r_miss(conn: sqlite3.Connection, cand: Candidate, *, failure_class: str) -> None:
    """记一条 r_miss（失败不复用黑名单，作用域收紧到 candidate 上下文）。"""
    conn.execute(
        """INSERT INTO r_miss
           (skill_name, branch_key, contract_slice, version, env_fingerprint, failure_class, ts)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (cand.purpose_guess or cand.id, "", cand.input_profile or "", None, "",
         failure_class, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def run_from_db(
    db_path: str | Path,
    events: list[EnrichedToolEvent],
    *,
    replay_timeout: int = 30,
) -> PipelineResult:
    """便捷入口：自开连接、建 schema、跑流水线、关连接。

    从 db_path 父目录推导 data_dir，启用 Artifact Store（阶段 2）。
    """
    dbp = Path(db_path)
    conn = db.connect(dbp)
    try:
        db.apply_schema(conn)
        return run_pipeline(
            conn, events, replay_timeout=replay_timeout,
            data_dir=dbp.parent,
        )
    finally:
        conn.close()
