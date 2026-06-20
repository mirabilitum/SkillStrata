"""T0.4 — 冻结的模块间接口契约（经 Codex M0 审核回灌）。

这是 M1-M7 能并行 build 的地基：每个模块只对着这里的数据结构编程，不依赖别人的实现。
**改这里 = 影响所有人，需谨慎并交 Codex 审。**

约定：所有契约都可 JSON 序列化（`to_dict` / `from_dict`），用于落 SQLite / traces / 跨模块传递。
对照设计：技术栈 trace schema、契约引擎 §3、属性OutputGate §3、v0.4 §9 manifest、候选发现规则 §1。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional

CONTRACTS_SCHEMA_VERSION = 1

# --- 处理阶段：显式编号，绝不用字符串字典序比较（见运维层 stage_rank 修正）---
STAGE_RANK: dict[str, int] = {
    "discovered": 10,
    "gate0_done": 20,
    "replayed": 30,
    "output_gated": 40,
    "contract_extracted": 50,
    "judged": 60,
    "classified": 70,
    "composed": 80,
}
LIFECYCLE = ("raw", "candidate", "verified", "promoted", "deprecated", "archived")
VISIBILITY = ("hidden", "searchable", "invokable_by_id", "mcp_exposed", "team_published")
PIPELINE_STATUS = ("active", "deferred", "rejected")
DEFERRED_REASON = ("dependency", "nondeterministic", "chain", "incomplete_association")
Determinism = Literal["deterministic", "nondeterministic", "mixed"]
RelationLabel = Literal["same_branch", "same_purpose_new_branch", "different_purpose"]
Classification = Literal["new_skill", "new_branch", "iteration", "duplicate", "ambiguous"]


def to_dict(obj: Any) -> dict:
    """统一序列化（递归处理嵌套 dataclass）。"""
    return asdict(obj)


# --------------------------------------------------------------------------- #
# 采集层（M1）
# --------------------------------------------------------------------------- #

@dataclass
class Artifact:
    path: str
    media_type: str = ""
    hash: str = ""  # hook 不算 hash；daemon enrichment 补


@dataclass
class RawToolEvent:
    """M1 hook 产出：极轻、只原始信息、不解析/不 hash。"""
    event_id: str
    session_id: str
    project_id: str
    task_id: str
    host_agent: str  # claude-code | codex | hermes
    timestamp: str
    event_type: str  # tool_call | generated_code | command_exec | file_edit | prompt
    name: str
    cwd: str
    argv: list[str] = field(default_factory=list)
    exit_code: Optional[int] = None
    source_ref: dict[str, str] = field(default_factory=dict)
    raw_payload_ref: str = ""     # 原始工具输入/输出落盘引用（不解析）
    transcript_ref: str = ""      # M1.4：transcript/session metadata 只读归档引用
    redaction_version: str = ""   # 采集即脱敏（运维层）
    redacted_fields: list[str] = field(default_factory=list)


@dataclass
class DeterminismSignals:
    network_access: bool = False
    external_model_call: bool = False
    uses_time_or_random: bool = False
    calls_system_binary: bool = False          # Q6：soffice/win32com 等 → 系统依赖
    system_binaries: list[str] = field(default_factory=list)
    replay_byte_identical: Optional[bool] = None  # 实测重放回填（None=未测）


@dataclass
class EnrichedToolEvent:
    """M1 daemon enrichment 产出：补 hash/media_type/file_changes/determinism。"""
    raw: RawToolEvent
    input_artifacts: list[Artifact] = field(default_factory=list)
    output_artifacts: list[Artifact] = field(default_factory=list)
    file_changes: list[dict] = field(default_factory=list)
    stdout_ref: str = ""
    stderr_ref: str = ""
    env_fingerprint: dict = field(default_factory=dict)
    determinism_signals: DeterminismSignals = field(default_factory=DeterminismSignals)
    transcript_ref: str = ""
    redaction_version: str = ""
    redacted_fields: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "EnrichedToolEvent":
        return cls(
            raw=RawToolEvent(**d["raw"]),
            input_artifacts=[Artifact(**a) for a in d.get("input_artifacts", [])],
            output_artifacts=[Artifact(**a) for a in d.get("output_artifacts", [])],
            file_changes=d.get("file_changes", []),
            stdout_ref=d.get("stdout_ref", ""),
            stderr_ref=d.get("stderr_ref", ""),
            env_fingerprint=d.get("env_fingerprint", {}),
            determinism_signals=DeterminismSignals(**d.get("determinism_signals", {})),
            transcript_ref=d.get("transcript_ref", ""),
            redaction_version=d.get("redaction_version", ""),
            redacted_fields=d.get("redacted_fields", []),
        )


# --------------------------------------------------------------------------- #
# 候选发现（M2）
# --------------------------------------------------------------------------- #

@dataclass
class ExecContext:
    task_id: str = ""
    cwd: str = ""
    session_id: str = ""
    source_ref: dict[str, str] = field(default_factory=dict)


@dataclass
class Candidate:
    id: str
    purpose_guess: str
    entry_kind: str = "script"  # script | command
    entry_ref: str = ""
    argv: list[str] = field(default_factory=list)
    code_snapshot_ref: str = ""
    input_artifacts: list[Artifact] = field(default_factory=list)
    output_artifacts: list[Artifact] = field(default_factory=list)
    determinism: Determinism = "deterministic"
    branch_identity: dict = field(default_factory=dict)
    input_profile: str = ""     # pdf_text|pdf_scanned|office_docx|xlsx_table|...（门禁分支化用）
    stage: str = "discovered"   # processing_stage（与 lifecycle 区分）
    lifecycle: str = "raw"
    # 显式搁置机制（Q6 / Gate0），不静默丢
    pipeline_status: str = "active"   # active | deferred | rejected
    deferred_reason: str = ""         # dependency | nondeterministic | chain | incomplete_association
    requires_host_capability: list[str] = field(default_factory=list)
    # 原始执行结果与上下文（候选发现规则 §1）
    result_status: str = ""           # success | error
    exit_code: Optional[int] = None
    context: ExecContext = field(default_factory=ExecContext)
    source_trace_ids: list[str] = field(default_factory=list)
    # 验证结果
    replay_pass: Optional[bool] = None
    output_pass: Optional[bool] = None
    # 团队预留
    dedup_key: str = ""

    @property
    def stage_rank(self) -> int:
        return STAGE_RANK[self.stage]

    @classmethod
    def from_dict(cls, d: dict) -> "Candidate":
        d = dict(d)
        d["input_artifacts"] = [Artifact(**a) for a in d.get("input_artifacts", [])]
        d["output_artifacts"] = [Artifact(**a) for a in d.get("output_artifacts", [])]
        if isinstance(d.get("context"), dict):
            d["context"] = ExecContext(**d["context"])
        return cls(**d)


# --------------------------------------------------------------------------- #
# 验证 + 指纹（M3）
# --------------------------------------------------------------------------- #

BEHAVIOR_SCHEMA_VERSION = 1

# 字段级比较契约（Codex P1）：M1-M7 共用这一套，别各写一套比较语义。
#   kind: boolean | numeric | ordinal | categorical
#   better: bool（boolean 字段 True/False 谁更优）
#   direction: "higher"（numeric）
#   tolerance: float（numeric，差值 < tol 视为相等）
#   order: list（ordinal 从劣到优）
#   comparable: 是否参与支配判定（categorical=False，只能相等/不同）
#   unknown_policy: skip | treat_false
BEHAVIOR_FIELD_RULES: dict[str, dict] = {
    "markdown_valid":        {"kind": "boolean", "better": True,  "comparable": True,  "unknown_policy": "treat_false"},
    "assets_emitted":        {"kind": "boolean", "better": True,  "comparable": True,  "unknown_policy": "treat_false"},
    "image_ref_coverage":    {"kind": "numeric", "direction": "higher", "tolerance": 0.02, "comparable": True, "unknown_policy": "skip"},
    "heading_preservation":  {"kind": "numeric", "direction": "higher", "tolerance": 0.02, "comparable": True, "unknown_policy": "skip"},
    "content_coverage_grade": {"kind": "ordinal", "order": ["D", "C", "B", "A"], "comparable": True, "unknown_policy": "skip"},
    "table_render_mode":     {"kind": "categorical", "comparable": False, "unknown_policy": "skip"},  # 无全局优劣
    "key_value_rendering":   {"kind": "boolean", "better": True,  "comparable": True,  "unknown_policy": "skip"},
    "is_thin_wrapper":       {"kind": "boolean", "better": False, "comparable": True,  "unknown_policy": "treat_false"},  # False 更宜作主实现
}
GRADE_ORDER = ("D", "C", "B", "A")


@dataclass
class BehaviorSignature:
    markdown_valid: bool = False
    assets_emitted: bool = False
    image_ref_coverage: float = 0.0
    heading_preservation: float = 0.0
    content_coverage_grade: str = "D"            # D|C|B|A（ordinal）
    table_render_mode: str = "unknown"           # pipe_table|kv_list|row_list|unknown
    key_value_rendering: bool = False
    is_thin_wrapper: bool = False
    schema_version: int = BEHAVIOR_SCHEMA_VERSION


def _cmp_field(rule: dict, av, bv) -> Optional[int]:
    """单字段比较：+1=a 更优, -1=b 更优, 0=相等, None=不可比/跳过。"""
    if not rule.get("comparable", True):
        return None
    kind = rule["kind"]
    if kind == "boolean":
        better = rule.get("better", True)
        a = bool(av) if av is not None else False
        b = bool(bv) if bv is not None else False
        if a == b:
            return 0
        # better=True：True>False；better=False：False>True
        a_better = (a and better) or ((not a) and (not better))
        return 1 if a_better else -1
    if kind == "numeric":
        if av is None or bv is None:
            return None
        if abs(float(av) - float(bv)) < rule.get("tolerance", 0.0):
            return 0
        return 1 if float(av) > float(bv) else -1
    if kind == "ordinal":
        order = rule["order"]
        if av not in order or bv not in order:
            return None
        ia, ib = order.index(av), order.index(bv)
        return 0 if ia == ib else (1 if ia > ib else -1)
    return None


def compare_behavior(a: "BehaviorSignature", b: "BehaviorSignature") -> str:
    """冻结的支配语义（M5 三选一用，别各自实现）。
    返回 "a_dominates" | "b_dominates" | "equal" | "incomparable"。
    """
    a_better = a_worse = 0
    for fld, rule in BEHAVIOR_FIELD_RULES.items():
        r = _cmp_field(rule, getattr(a, fld, None), getattr(b, fld, None))
        if r is None:
            continue
        if r > 0:
            a_better += 1
        elif r < 0:
            a_worse += 1
    if a_better and a_worse:
        return "incomparable"
    if a_better and not a_worse:
        return "a_dominates"
    if a_worse and not a_better:
        return "b_dominates"
    return "equal"


# --------------------------------------------------------------------------- #
# 契约抽取（M4）
# --------------------------------------------------------------------------- #

@dataclass
class ContractSignature:
    input_media_types: list[str] = field(default_factory=list)
    input_arity: str = "single_file"  # single_file | directory
    output_types: list[str] = field(default_factory=list)
    output_side_artifacts: list[str] = field(default_factory=list)
    purpose_summary: str = ""
    purpose_embedding_ref: str = ""
    branch_identity: dict = field(default_factory=dict)
    # 价值指纹（同目的判定要忽略它，但不从契约对象里删，M5 要用）
    behavior_signature: Optional[BehaviorSignature] = None
    # 代码佐证（副轴：薄壳/结构判等）
    code_evidence_ref: str = ""
    structural_fingerprint: str = ""
    signature_hash: str = ""
    schema_version: int = CONTRACTS_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, d: dict) -> "ContractSignature":
        d = dict(d)
        bs = d.get("behavior_signature")
        if isinstance(bs, dict):
            d["behavior_signature"] = BehaviorSignature(**bs)
        return cls(**d)


# --------------------------------------------------------------------------- #
# 沉淀（M5 / Composer）
# --------------------------------------------------------------------------- #

@dataclass
class ImplRef:
    impl_ref: str
    version: int = 1
    fixtures_ref: str = ""
    quality: dict = field(default_factory=dict)


@dataclass
class Branch:
    key: str
    # best-of-N 只切 active_impl，retained_impls 全保留（不删兄弟）
    active_impl_ref: str = ""
    active_version: int = 1
    retained_impls: list[ImplRef] = field(default_factory=list)
    is_thin_wrapper: bool = False
    fixtures_ref: str = ""
    requires_host_capability: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "Branch":
        d = dict(d)
        d["retained_impls"] = [ImplRef(**i) for i in d.get("retained_impls", [])]
        return cls(**d)


@dataclass
class SkillManifest:
    name: str
    purpose: str
    when_to_use: str = ""
    contract: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    branches: list[Branch] = field(default_factory=list)
    shared_post_processing: list[str] = field(default_factory=list)
    determinism: Determinism = "deterministic"
    quality: dict = field(default_factory=dict)
    host_native: dict = field(default_factory=dict)     # {mcp_tool: ...}
    # L3/L4 refs（不内联大块，存引用）
    shared_fixtures_ref: str = ""
    iteration_log_ref: str = ""
    lineage_ref: str = ""
    source: dict = field(default_factory=dict)          # {author, origin_host}
    # 团队预留字段（入 schema 不驱动行为）
    created_by: str = ""
    visibility: str = "hidden"
    dedup_key: str = ""
    schema_version: int = CONTRACTS_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, d: dict) -> "SkillManifest":
        d = dict(d)
        d["branches"] = [Branch.from_dict(b) for b in d.get("branches", [])]
        return cls(**d)


# --------------------------------------------------------------------------- #
# 示例实例（fixtures）—— 供并行 subagent 对接口编程
# --------------------------------------------------------------------------- #

def example_raw_event() -> RawToolEvent:
    return RawToolEvent(
        event_id="evt-1", session_id="s-1", project_id="proj-A", task_id="t-1",
        host_agent="claude-code", timestamp="2026-06-20T16:00:00Z",
        event_type="command_exec", name="python conv.py a.pdf", cwd="/proj/A",
        argv=["python", "conv.py", "a.pdf"], exit_code=0,
        source_ref={"message_id": "m-1"}, transcript_ref="traces/s-1/transcript.jsonl",
    )


def example_enriched_event() -> EnrichedToolEvent:
    return EnrichedToolEvent(
        raw=example_raw_event(),
        input_artifacts=[Artifact(path="a.pdf", media_type="application/pdf", hash="blake3:aa")],
        output_artifacts=[Artifact(path="a.md", media_type="text/markdown", hash="blake3:bb")],
        determinism_signals=DeterminismSignals(replay_byte_identical=True),
    )


def example_candidate() -> Candidate:
    return Candidate(
        id="cand-1", purpose_guess="document-to-markdown", entry_ref="conv.py",
        argv=["python", "conv.py", "a.pdf"],
        input_artifacts=[Artifact(path="a.pdf", media_type="application/pdf")],
        output_artifacts=[Artifact(path="a.md", media_type="text/markdown")],
        branch_identity={"normalized_input_family": "pdf_text", "input_mode": "single_file"},
        input_profile="pdf_text", result_status="success", exit_code=0,
        context=ExecContext(task_id="t-1", cwd="/proj/A", session_id="s-1"),
        source_trace_ids=["evt-1"],
    )


def example_deferred_candidate() -> Candidate:
    """系统依赖分支：显式搁置，不静默丢（Q6）。"""
    c = example_candidate()
    c.id = "cand-legacy-doc"
    c.input_profile = "office_legacy"
    c.pipeline_status = "deferred"
    c.deferred_reason = "dependency"
    c.requires_host_capability = ["libreoffice"]
    return c


def example_behavior_signature() -> BehaviorSignature:
    return BehaviorSignature(
        markdown_valid=True, assets_emitted=True, image_ref_coverage=1.0,
        heading_preservation=1.0, content_coverage_grade="A",
        table_render_mode="kv_list", key_value_rendering=True, is_thin_wrapper=False,
    )


def example_contract_signature() -> ContractSignature:
    return ContractSignature(
        input_media_types=["application/pdf"], input_arity="single_file",
        output_types=["text/markdown"], output_side_artifacts=["assets/"],
        purpose_summary="document-to-markdown", purpose_embedding_ref="qdrant:point-1",
        branch_identity={"normalized_input_family": "pdf_text"},
        behavior_signature=example_behavior_signature(),
        code_evidence_ref="artifacts/cand-1/snapshot.py", signature_hash="blake3:cc",
    )


def example_skill_manifest() -> SkillManifest:
    return SkillManifest(
        name="doc-to-markdown",
        purpose="任意文档转换为 LLM 友好的 markdown",
        when_to_use="需要把 pdf/word/excel/ppt/html 统一为 markdown 时",
        contract={"input": {"document_path": "file"}, "output": {"markdown": "string", "assets": "dir"}},
        tags=["convert", "markdown", "document"],
        branches=[Branch(key="pdf", active_impl_ref="./branches/pdf.py",
                         retained_impls=[ImplRef(impl_ref="./branches/pdf.py", version=1)])],
        shared_post_processing=["table_to_list", "sanitize_text"],
        host_native={"mcp_tool": "doc_to_markdown"},
        source={"author": "proj-A", "origin_host": "claude-code"},
        created_by="proj-A", visibility="hidden",
    )
