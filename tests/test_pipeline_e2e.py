"""端到端集成测试 — 证明 pipeline 真能从一条 trace 走完全链沉淀出可被搜到的 skill。

复审（2026-07-04）P0：此前 337 项测试全是函数级，没有一项证明整条线接通。
本文件补上这个缺口，覆盖：
  · happy path：events → discovery → gate0 → replay → output_gate → 契约
    → 三选一(new_skill) → composer → persist(skills+branches) → observe 可见
    → 复用×3 成功 → auto_upgrade → mcp search 可搜到（价值靠复用确认）
  · 显式搁置：系统依赖候选被 gate0 defer，落库不静默丢，不产 skill
  · 幂等：同契约再跑一次 → duplicate，不重复建 skill

用真实沙箱重放（subprocess），不 mock —— 这正是要验证的东西。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from distiller import db, observe, pipeline, review, warmstart
from distiller.contracts import Artifact, EnrichedToolEvent, RawToolEvent


# --------------------------------------------------------------------------- #
# fixtures：真实转换脚本 + 真实输入文件
# --------------------------------------------------------------------------- #

# 一个确定性、无外部依赖的 html→md 转换器：读 argv[1]，去标签，打印 markdown 到 stdout。
# 刻意避开 gate0 的网络/时间随机/系统二进制模式，保持 active。
_CONVERTER_SRC = '''\
import re
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    html = f.read()

text = re.sub(r"<[^>]+>", "", html)
text = re.sub(r"\\n{3,}", "\\n\\n", text).strip()
print("# Converted Document\\n")
print(text)
'''

# 一个走系统依赖分支的转换器：正文含 "soffice" → gate0 探测 → deferred(dependency)。
_LEGACY_CONVERTER_SRC = '''\
import subprocess
import sys

# 依赖 LibreOffice（soffice）转换旧格式；replay 前就会被 gate0 显式搁置。
subprocess.run(["soffice", "--headless", "--convert-to", "md", sys.argv[1]])
'''

_INPUT_HTML = """\
<html><body>
<h1>Quarterly Report</h1>
<p>Revenue grew across every region this quarter. The engineering team shipped
the new pipeline orchestrator and closed the persistence gap that had blocked
end to end distillation. Customer retention held steady near ninety percent.</p>
<p>Next quarter we focus on reuse driven quality promotion and warm start recall.</p>
</body></html>
"""


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def _exec_event(
    *,
    task_id: str,
    cwd: str,
    script_path: str,
    input_path: str,
    input_media: str,
    event_id: str,
) -> EnrichedToolEvent:
    """构造一条 command_exec enriched 事件（discovery 的输入原料）。"""
    raw = RawToolEvent(
        event_id=event_id,
        session_id="s-e2e",
        project_id="proj-e2e",
        task_id=task_id,
        host_agent="claude-code",
        timestamp="2026-07-04T10:00:00Z",
        event_type="command_exec",
        name=f"python {script_path} {input_path}",
        cwd=cwd,
        argv=["python", script_path, input_path],
        exit_code=0,
    )
    return EnrichedToolEvent(
        raw=raw,
        input_artifacts=[Artifact(path=input_path, media_type=input_media)],
        output_artifacts=[Artifact(path=str(Path(cwd) / "out.md"), media_type="text/markdown")],
    )


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(tmp_path / "e2e.sqlite")
    db.apply_schema(c)
    yield c
    c.close()


# --------------------------------------------------------------------------- #
# happy path
# --------------------------------------------------------------------------- #

def test_e2e_trace_becomes_searchable_skill(conn, tmp_path):
    conv = _write(tmp_path / "conv.py", _CONVERTER_SRC)
    inp = _write(tmp_path / "report.html", _INPUT_HTML)

    events = [
        _exec_event(
            task_id="t-1",
            cwd=str(tmp_path),
            script_path=str(conv),
            input_path=str(inp),
            input_media="text/html",
            event_id="evt-1",
        )
    ]

    result = pipeline.run_pipeline(conn, events)

    # 1) 流水线产出恰好一个 promoted skill
    assert result.promoted_skills, f"没有 skill 沉淀：{[o.__dict__ for o in result.outcomes]}"
    skill_name = result.promoted_skills[0]
    assert result.outcomes[0].classification == "new_skill"
    assert result.outcomes[0].pipeline_status == "active"

    # 2) 落库可观测（此前读侧建立在空表之上，这里证明表非空）
    listed = observe.list_skills(conn)
    assert any(s["name"] == skill_name for s in listed)
    detail = observe.show_skill(conn, skill_name)
    assert detail["branches"], "skill 应至少有一条分支落库"

    # 3) 复用×3 成功 → auto_upgrade 把 hidden 升 searchable（价值靠复用确认）
    for _ in range(3):
        warmstart.record_usage(conn, skill_name, detail["branches"][0]["key"], "success")
    upgraded = review.auto_upgrade_quality(conn)
    assert skill_name in upgraded

    vis = conn.execute("SELECT visibility FROM skills WHERE name=?", (skill_name,)).fetchone()[0]
    assert vis == "searchable"

    # 4) MCP 搜索能搜到（升级后 visibility != hidden）
    from distiller import mcp_server
    found = mcp_server.search_capability(conn, "markdown")
    assert any(h["name"] == skill_name for h in found), \
        f"搜索应命中 {skill_name}，实际：{[h['name'] for h in found]}"


# --------------------------------------------------------------------------- #
# 显式搁置：系统依赖不静默丢
# --------------------------------------------------------------------------- #

def test_e2e_system_dependency_candidate_is_deferred(conn, tmp_path):
    legacy = _write(tmp_path / "legacy_conv.py", _LEGACY_CONVERTER_SRC)
    doc = _write(tmp_path / "old.doc", "binary-ish placeholder content")

    events = [
        _exec_event(
            task_id="t-legacy",
            cwd=str(tmp_path),
            script_path=str(legacy),
            input_path=str(doc),
            input_media="application/msword",
            event_id="evt-legacy",
        )
    ]

    result = pipeline.run_pipeline(conn, events)

    # 不产 skill，但候选显式落库为 deferred（Q6：搁置不静默丢）
    assert result.promoted_skills == []
    deferred = result.by_status("deferred")
    assert len(deferred) == 1
    assert deferred[0].reason == "dependency"

    row = conn.execute(
        "SELECT pipeline_status, deferred_reason, requires_host_capability FROM candidates"
    ).fetchone()
    assert row["pipeline_status"] == "deferred"
    assert row["deferred_reason"] == "dependency"
    assert "libreoffice" in row["requires_host_capability"]


# --------------------------------------------------------------------------- #
# 幂等：同契约再跑 → duplicate，不重复建 skill
# --------------------------------------------------------------------------- #

def test_e2e_identical_contract_is_duplicate(conn, tmp_path):
    conv = _write(tmp_path / "conv.py", _CONVERTER_SRC)
    inp = _write(tmp_path / "report.html", _INPUT_HTML)

    def one(task_id, event_id):
        return [
            _exec_event(
                task_id=task_id,
                cwd=str(tmp_path),
                script_path=str(conv),
                input_path=str(inp),
                input_media="text/html",
                event_id=event_id,
            )
        ]

    first = pipeline.run_pipeline(conn, one("t-a", "evt-a"))
    assert first.outcomes[0].classification == "new_skill"
    skill_name = first.promoted_skills[0]

    second = pipeline.run_pipeline(conn, one("t-b", "evt-b"))
    # 同 signature_hash → same_branch → 行为相等 → duplicate（不再建新 skill）
    assert second.outcomes[0].classification == "duplicate"

    count = conn.execute(
        "SELECT COUNT(*) FROM skills WHERE name=?", (skill_name,)
    ).fetchone()[0]
    assert count == 1


# --------------------------------------------------------------------------- #
# 相对路径：cwd + relative argv 走完整 pipeline（复审 P1）
# --------------------------------------------------------------------------- #

def test_e2e_relative_paths_resolve_via_cwd(conn, tmp_path):
    """真实 trace 形态：argv/artifact 是相对路径，靠 event.cwd 归一。

    此前 pipeline 用 Path(entry_ref) 直接解析，orchestrator 不在 cwd 下就全崩。
    """
    _write(tmp_path / "conv.py", _CONVERTER_SRC)
    _write(tmp_path / "report.html", _INPUT_HTML)

    # 关键：argv 与 artifact.path 都用**相对**名，cwd 指向 tmp_path
    events = [
        _exec_event(
            task_id="t-rel",
            cwd=str(tmp_path),
            script_path="conv.py",
            input_path="report.html",
            input_media="text/html",
            event_id="evt-rel",
        )
    ]

    result = pipeline.run_pipeline(conn, events)

    assert result.promoted_skills, (
        f"相对路径应能走完全链，实际：{[o.__dict__ for o in result.outcomes]}"
    )
    assert result.outcomes[0].classification == "new_skill"
    assert result.outcomes[0].pipeline_status == "active"


def test_e2e_relative_system_dependency_deferred(conn, tmp_path):
    """相对路径的系统依赖候选：gate0 仍能读到脚本里的 soffice → deferred。"""
    _write(tmp_path / "legacy_conv.py", _LEGACY_CONVERTER_SRC)
    _write(tmp_path / "old.doc", "placeholder")

    events = [
        _exec_event(
            task_id="t-rel-legacy",
            cwd=str(tmp_path),
            script_path="legacy_conv.py",
            input_path="old.doc",
            input_media="application/msword",
            event_id="evt-rel-legacy",
        )
    ]

    result = pipeline.run_pipeline(conn, events)
    deferred = result.by_status("deferred")
    assert len(deferred) == 1
    assert deferred[0].reason == "dependency"  # gate0 读到相对脚本里的 soffice


def test_e2e_binary_input_deferred_not_falsely_rejected(conn, tmp_path):
    """复审 P2：二进制文档（无 extractor）覆盖率不可测 → deferred，不误判 fail。

    构造一个 active（无系统依赖）、但输入是 pdf 的候选：脚本能跑、打印 markdown，
    但 pipeline 不该拿二进制 pdf 当 UTF-8 算覆盖率再 fail，而应显式 deferred。
    """
    # 一个不依赖系统二进制、直接打印固定 markdown 的转换器（避开 gate0 defer）
    _write(tmp_path / "pdfconv.py", 'print("# Title\\n\\nsome extracted body text")\n')
    (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.4\x00\x01binary\xff\xfe not text")

    events = [
        _exec_event(
            task_id="t-bin",
            cwd=str(tmp_path),
            script_path="pdfconv.py",
            input_path="doc.pdf",
            input_media="application/pdf",
            event_id="evt-bin",
        )
    ]

    result = pipeline.run_pipeline(conn, events)
    o = result.outcomes[0]
    assert o.pipeline_status == "deferred", o.__dict__
    assert o.reason == "input_text_unmeasurable"
    assert result.promoted_skills == []


# --------------------------------------------------------------------------- #
# pending / lifecycle 推进（复审 P1-pending）
# --------------------------------------------------------------------------- #

# 同一长正文（保证覆盖率/grade 相等），仅在 image vs key-value 两个可比字段上互有胜负
_AMBIG_BODY = (
    "Revenue grew across every region this quarter. The engineering team shipped the new pipeline "
    "orchestrator and closed the persistence gap that had blocked end to end distillation. Customer "
    "retention held steady near ninety percent. Next quarter we focus on reuse driven quality promotion "
    "and warm start recall across every team and project in the whole organization this fiscal year."
)
# 有图片、无键值 → image_ref_coverage=1.0, key_value_rendering=False
_CONV_IMAGE = 'print("""# Report\n\n![chart](assets/chart.png)\n\n%s\n""")\n' % _AMBIG_BODY
# 无图片、有键值 → image_ref_coverage=0.0, key_value_rendering=True（两字段与上相反 → 不可比）
_CONV_KV = 'print("""# Report\n\nRegion: North\nStatus: green\n\n%s\n""")\n' % _AMBIG_BODY


def test_e2e_new_skill_promoted_not_in_pending(conn, tmp_path):
    """成功沉淀的 new_skill → lifecycle=promoted，不出现在 pending。"""
    from distiller import cli_pending
    _write(tmp_path / "conv.py", _CONVERTER_SRC)
    _write(tmp_path / "report.html", _INPUT_HTML)
    events = [_exec_event(task_id="t-p", cwd=str(tmp_path), script_path="conv.py",
                          input_path="report.html", input_media="text/html", event_id="evt-p")]
    result = pipeline.run_pipeline(conn, events)
    assert result.promoted_skills

    cid = result.outcomes[0].candidate_id
    lc = conn.execute("SELECT lifecycle FROM candidates WHERE id=?", (cid,)).fetchone()[0]
    assert lc == "promoted"
    assert cid not in {r["id"] for r in cli_pending.list_pending(conn)}


def test_e2e_output_gate_fail_rejected_not_in_pending(conn, tmp_path):
    """Output Gate 失败 → rejected，不进 pending。"""
    from distiller import cli_pending
    # 转换器打印空白 → integrity fail → output_gate fail
    _write(tmp_path / "conv.py", 'print("   ")\n')
    _write(tmp_path / "report.html", _INPUT_HTML)
    events = [_exec_event(task_id="t-f", cwd=str(tmp_path), script_path="conv.py",
                          input_path="report.html", input_media="text/html", event_id="evt-f")]
    result = pipeline.run_pipeline(conn, events)
    o = result.outcomes[0]
    assert o.pipeline_status == "rejected"
    assert cli_pending.list_pending(conn) == []


def test_e2e_ambiguous_candidate_enters_pending(conn, tmp_path):
    """行为不可比的同分支候选 → ambiguous → 进 pending 待人工 pin。"""
    from distiller import cli_pending
    _write(tmp_path / "report.html", _INPUT_HTML)
    _write(tmp_path / "conv_img.py", _CONV_IMAGE)
    _write(tmp_path / "conv_kv.py", _CONV_KV)

    def ev(script, task, eid):
        return [_exec_event(task_id=task, cwd=str(tmp_path), script_path=script,
                            input_path="report.html", input_media="text/html", event_id=eid)]

    first = pipeline.run_pipeline(conn, ev("conv_img.py", "t-1", "e1"))
    assert first.outcomes[0].classification == "new_skill"

    second = pipeline.run_pipeline(conn, ev("conv_kv.py", "t-2", "e2"))
    # 同契约 same_branch，但 image vs key-value 互有胜负 → incomparable → ambiguous
    assert second.outcomes[0].classification == "ambiguous", second.outcomes[0].__dict__
    assert second.outcomes[0].pipeline_status == "deferred"

    pending_ids = {r["id"] for r in cli_pending.list_pending(conn)}
    assert second.outcomes[0].candidate_id in pending_ids


# --------------------------------------------------------------------------- #
# 可观测性 + 幂等（复审补充 B/C/D）
# --------------------------------------------------------------------------- #

def test_e2e_pipeline_error_records_lineage_and_r_miss(conn, tmp_path, monkeypatch):
    """process_candidate 整体失败（首阶段前就崩）→ 外层兜底 rejected + lineage + r_miss。"""
    _write(tmp_path / "conv.py", _CONVERTER_SRC)
    _write(tmp_path / "report.html", _INPUT_HTML)
    events = [_exec_event(task_id="t-err", cwd=str(tmp_path), script_path="conv.py",
                          input_path="report.html", input_media="text/html", event_id="evt-err")]

    # 替换整个 process_candidate → 走 run_pipeline 外层兜底路径
    def boom(*a, **k):
        raise RuntimeError("injected")
    monkeypatch.setattr(pipeline, "process_candidate", boom)

    result = pipeline.run_pipeline(conn, events)
    assert result.outcomes[0].pipeline_status == "rejected"
    assert "injected" in result.outcomes[0].reason

    lin = conn.execute("SELECT COUNT(*) FROM lineage WHERE kind='pipeline_error'").fetchone()[0]
    rm = conn.execute("SELECT COUNT(*) FROM r_miss WHERE failure_class='crash'").fetchone()[0]
    assert lin == 1
    assert rm == 1


def test_e2e_mid_pipeline_error_does_not_rewind_candidate(conn, tmp_path, monkeypatch):
    """中后段抛错（已落库到 output_gated/verified 后）→ 不倒退 stage/lifecycle（复审三次 P2-2）。"""
    _write(tmp_path / "conv.py", _CONVERTER_SRC)
    _write(tmp_path / "report.html", _INPUT_HTML)
    events = [_exec_event(task_id="t-miderr", cwd=str(tmp_path), script_path="conv.py",
                          input_path="report.html", input_media="text/html", event_id="evt-miderr")]

    # 在 Output Gate 之后的契约抽取阶段抛错
    def boom(*a, **k):
        raise RuntimeError("mid-stage injected")
    monkeypatch.setattr(pipeline.contract_extract, "extract_contract", boom)

    result = pipeline.run_pipeline(conn, events)
    o = result.outcomes[0]
    assert o.pipeline_status == "rejected"
    assert "mid-stage injected" in o.reason

    row = conn.execute(
        "SELECT stage, lifecycle, pipeline_status FROM candidates WHERE id=?",
        (o.candidate_id,),
    ).fetchone()
    # 关键：DB 里是推进到的真实进度，不能倒退回 discovered/raw
    assert row["stage"] == "output_gated"
    assert row["lifecycle"] == "verified"
    assert row["pipeline_status"] == "rejected"

    # 信号也用推进后的 cand：lineage 的 stage 不 stale
    lin = conn.execute(
        "SELECT detail FROM lineage WHERE kind='pipeline_error' AND subject=?",
        (o.candidate_id,),
    ).fetchone()
    assert lin is not None
    import json as _json
    assert _json.loads(lin["detail"])["stage"] == "output_gated"
    rm = conn.execute("SELECT COUNT(*) FROM r_miss WHERE failure_class='crash'").fetchone()[0]
    assert rm == 1


def test_e2e_reprocess_does_not_duplicate_signatures(conn, tmp_path):
    """同一候选重复处理 → 契约签名不叠加（幂等，复审补充 D）。"""
    _write(tmp_path / "conv.py", _CONVERTER_SRC)
    _write(tmp_path / "report.html", _INPUT_HTML)
    events = [_exec_event(task_id="t-idem", cwd=str(tmp_path), script_path="conv.py",
                          input_path="report.html", input_media="text/html", event_id="evt-idem")]

    from distiller import discovery
    cands = discovery.discover(events)
    assert len(cands) == 1
    cid = cands[0].id

    # 处理两次同一候选
    pipeline.process_candidate(conn, cands[0])
    cands2 = discovery.discover(events)
    cands2[0].id = cid  # 同一候选 id
    pipeline.process_candidate(conn, cands2[0])

    cand_sigs = conn.execute(
        "SELECT COUNT(*) FROM contract_signatures WHERE entity_type='candidate' AND entity_id=?",
        (cid,),
    ).fetchone()[0]
    assert cand_sigs == 1  # 不叠加
