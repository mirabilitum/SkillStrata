"""T0.4 — 冻结的模块间接口契约。

这是 M1-M7 能并行 build 的地基：每个模块只对着这里的数据结构编程，不依赖别人的实现。
**改这里 = 影响所有人，需谨慎并交 Codex 审。**

约定：所有契约都可 JSON 序列化（`to_dict` / `from_dict`），用于落 SQLite / traces / 跨模块传递。
对照设计：技术栈 trace schema、契约引擎 §3、属性OutputGate §3、v0.4 §9 manifest。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional

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
Determinism = Literal["deterministic", "nondeterministic", "mixed"]

# behavior_signature 字段级比较规则（Codex P1：支配判定要靠它；categorical 无全局序）
BEHAVIOR_FIELD_RULES: dict[str, str] = {
    "markdown_valid": "boolean",
    "assets_emitted": "boolean",
    "image_ref_coverage": "numeric",      # higher better, 带容差
    "heading_preservation": "numeric",
    "content_coverage_grade": "ordinal",  # D < C < B < A
    "table_render_mode": "categorical",   # 无全局优劣
    "key_value_rendering": "boolean",
    "is_thin_wrapper": "boolean",
}
GRADE_ORDER = ("D", "C", "B", "A")


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
        )


# --------------------------------------------------------------------------- #
# 候选发现（M2）
# --------------------------------------------------------------------------- #

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
    stage: str = "discovered"
    lifecycle: str = "raw"
    source_trace_ids: list[str] = field(default_factory=list)
    replay_pass: Optional[bool] = None
    output_pass: Optional[bool] = None
    requires_host_capability: list[str] = field(default_factory=list)  # Q6 系统依赖

    @property
    def stage_rank(self) -> int:
        return STAGE_RANK[self.stage]


# --------------------------------------------------------------------------- #
# 验证 + 指纹（M3）
# --------------------------------------------------------------------------- #

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


RelationLabel = Literal["same_branch", "same_purpose_new_branch", "different_purpose"]
Classification = Literal["new_skill", "new_branch", "iteration", "duplicate", "ambiguous"]


# --------------------------------------------------------------------------- #
# 沉淀（M5 / Composer）
# --------------------------------------------------------------------------- #

@dataclass
class Branch:
    key: str
    impl_ref: str = ""
    is_thin_wrapper: bool = False
    active: bool = True
    fixtures_ref: str = ""
    requires_host_capability: list[str] = field(default_factory=list)


@dataclass
class SkillManifest:
    name: str
    purpose: str
    when_to_use: str = ""
    contract: dict = field(default_factory=dict)
    branches: list[Branch] = field(default_factory=list)
    shared_post_processing: list[str] = field(default_factory=list)
    determinism: Determinism = "deterministic"
    quality: dict = field(default_factory=dict)
    # 团队预留字段（入 schema 不驱动行为）
    created_by: str = ""
    visibility: str = "hidden"
    dedup_key: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "SkillManifest":
        d = dict(d)
        d["branches"] = [Branch(**b) for b in d.get("branches", [])]
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
        source_ref={"message_id": "m-1"},
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
        source_trace_ids=["evt-1"],
    )


def example_behavior_signature() -> BehaviorSignature:
    return BehaviorSignature(
        markdown_valid=True, assets_emitted=True, image_ref_coverage=1.0,
        heading_preservation=1.0, content_coverage_grade="A",
        table_render_mode="kv_list", key_value_rendering=True, is_thin_wrapper=False,
    )


def example_skill_manifest() -> SkillManifest:
    return SkillManifest(
        name="doc-to-markdown",
        purpose="任意文档转换为 LLM 友好的 markdown",
        when_to_use="需要把 pdf/word/excel/ppt/html 统一为 markdown 时",
        contract={"input": {"document_path": "file"}, "output": {"markdown": "string", "assets": "dir"}},
        branches=[Branch(key="pdf", impl_ref="./process_pdf.py")],
        shared_post_processing=["table_to_list", "sanitize_text"],
        created_by="proj-A", visibility="hidden",
    )
