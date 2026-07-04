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
