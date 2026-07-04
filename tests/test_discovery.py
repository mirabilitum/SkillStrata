"""tests/test_discovery.py — M2 候选发现 + Gate0 测试

覆盖点：
  - shape_match：认出 pdf→md 单入口（通过）；纯计算（拒绝）；无 md 输出（拒绝）
  - is_noise：砍掉纯计算（无文件 I/O）；正常候选不砍
  - discover：从 example_enriched_event 产出 Candidate；字段校验
  - probe_determinism：从代码文本检出 soffice；不误判纯净代码
  - apply_gate0：系统依赖候选 → deferred + dependency + requires_host_capability

所有测试只用标准库 + distiller.contracts / .discovery / .gate0，无外部依赖。
"""
from __future__ import annotations

import pytest

from distiller.contracts import (
    Artifact,
    Candidate,
    DeterminismSignals,
    EnrichedToolEvent,
    ExecContext,
    RawToolEvent,
    example_candidate,
    example_enriched_event,
)
from distiller.discovery import (
    _has_md_output,
    _is_doc_artifact,
    correlate,
    discover,
    is_noise,
    shape_match,
)
from distiller.gate0 import apply_gate0, probe_determinism


# ---------------------------------------------------------------------------
# 辅助：构造最小 EnrichedToolEvent
# ---------------------------------------------------------------------------

def _make_event(
    *,
    task_id: str = "t-test",
    cwd: str = "/work",
    event_type: str = "command_exec",
    argv: list[str] | None = None,
    name: str = "",
    exit_code: int = 0,
    input_artifacts: list[Artifact] | None = None,
    output_artifacts: list[Artifact] | None = None,
    file_changes: list[dict] | None = None,
    event_id: str = "evt-test",
    session_id: str = "s-test",
    timestamp: str = "2026-06-20T10:00:00Z",
) -> EnrichedToolEvent:
    raw = RawToolEvent(
        event_id=event_id,
        session_id=session_id,
        project_id="proj-test",
        task_id=task_id,
        host_agent="claude-code",
        timestamp=timestamp,
        event_type=event_type,
        name=name or (" ".join(argv) if argv else ""),
        cwd=cwd,
        argv=argv or [],
        exit_code=exit_code,
    )
    return EnrichedToolEvent(
        raw=raw,
        input_artifacts=input_artifacts or [],
        output_artifacts=output_artifacts or [],
        file_changes=file_changes or [],
    )


# ---------------------------------------------------------------------------
# _is_doc_artifact / _has_md_output（内部工具函数快测）
# ---------------------------------------------------------------------------

class TestDocArtifact:
    def test_pdf_by_media_type(self):
        a = Artifact(path="report.pdf", media_type="application/pdf")
        assert _is_doc_artifact(a)

    def test_docx_by_media_type(self):
        a = Artifact(
            path="f.docx",
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        assert _is_doc_artifact(a)

    def test_pdf_by_extension(self):
        # media_type 空，靠扩展名
        a = Artifact(path="report.pdf", media_type="")
        assert _is_doc_artifact(a)

    def test_html_by_extension(self):
        a = Artifact(path="page.html", media_type="")
        assert _is_doc_artifact(a)

    def test_txt_not_doc(self):
        a = Artifact(path="notes.txt", media_type="text/plain")
        assert not _is_doc_artifact(a)

    def test_md_not_doc(self):
        # .md 是输出，不是输入文档类型
        a = Artifact(path="out.md", media_type="text/markdown")
        assert not _is_doc_artifact(a)


class TestHasMdOutput:
    def test_has_md(self):
        arts = [Artifact(path="out.md"), Artifact(path="assets/img.png")]
        assert _has_md_output(arts)

    def test_no_md(self):
        arts = [Artifact(path="out.txt"), Artifact(path="out.pdf")]
        assert not _has_md_output(arts)

    def test_empty(self):
        assert not _has_md_output([])


# ---------------------------------------------------------------------------
# shape_match
# ---------------------------------------------------------------------------

class TestShapeMatch:
    def _pdf_to_md_record(self) -> dict:
        """最小合法记录：pdf 进、md 出、成功、有入口。"""
        return {
            "entry_ref": "conv.py",
            "entry_kind": "script",
            "argv": ["python", "conv.py", "doc.pdf"],
            "input_artifacts": [
                Artifact(path="doc.pdf", media_type="application/pdf")
            ],
            "output_artifacts": [
                Artifact(path="doc.md", media_type="text/markdown")
            ],
            "exit_code": 0,
            "result_status": "success",
            "file_changes": [],
        }

    def test_pdf_to_md_passes(self):
        assert shape_match(self._pdf_to_md_record())

    def test_docx_to_md_passes(self):
        rec = self._pdf_to_md_record()
        rec["input_artifacts"] = [
            Artifact(
                path="doc.docx",
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        ]
        assert shape_match(rec)

    def test_xlsx_by_extension_passes(self):
        rec = self._pdf_to_md_record()
        rec["input_artifacts"] = [Artifact(path="data.xlsx", media_type="")]
        assert shape_match(rec)

    def test_html_to_md_passes(self):
        rec = self._pdf_to_md_record()
        rec["input_artifacts"] = [Artifact(path="page.html", media_type="text/html")]
        assert shape_match(rec)

    def test_no_entry_ref_fails(self):
        rec = self._pdf_to_md_record()
        rec["entry_ref"] = ""
        assert not shape_match(rec)

    def test_exit_code_nonzero_fails(self):
        rec = self._pdf_to_md_record()
        rec["exit_code"] = 1
        assert not shape_match(rec)

    def test_exit_code_none_fails(self):
        rec = self._pdf_to_md_record()
        rec["exit_code"] = None
        assert not shape_match(rec)

    def test_no_inputs_fails(self):
        rec = self._pdf_to_md_record()
        rec["input_artifacts"] = []
        assert not shape_match(rec)

    def test_txt_input_not_doc_fails(self):
        rec = self._pdf_to_md_record()
        rec["input_artifacts"] = [Artifact(path="notes.txt", media_type="text/plain")]
        assert not shape_match(rec)

    def test_no_md_output_fails(self):
        rec = self._pdf_to_md_record()
        rec["output_artifacts"] = [Artifact(path="out.txt")]
        assert not shape_match(rec)

    def test_no_outputs_fails(self):
        rec = self._pdf_to_md_record()
        rec["output_artifacts"] = []
        assert not shape_match(rec)


# ---------------------------------------------------------------------------
# is_noise
# ---------------------------------------------------------------------------

class TestIsNoise:
    def test_pure_compute_no_io(self):
        """无文件 I/O → 纯计算探针 → 噪声。"""
        rec = {
            "entry_ref": "calc.py",
            "argv": ["python", "calc.py"],
            "input_artifacts": [],
            "output_artifacts": [],
            "exit_code": 0,
            "file_changes": [],
        }
        assert is_noise(rec)

    def test_no_entry_ref_noise(self):
        """无入口 → REPL 试探 → 噪声。"""
        rec = {
            "entry_ref": "",
            "argv": [],
            "input_artifacts": [Artifact(path="a.pdf")],
            "output_artifacts": [Artifact(path="a.md")],
            "exit_code": 0,
            "file_changes": [],
        }
        assert is_noise(rec)

    def test_normal_conversion_not_noise(self):
        """pdf→md 转换：有 I/O + 有入口 → 不是噪声。"""
        rec = {
            "entry_ref": "conv.py",
            "argv": ["python", "conv.py", "a.pdf"],
            "input_artifacts": [Artifact(path="a.pdf", media_type="application/pdf")],
            "output_artifacts": [Artifact(path="a.md")],
            "exit_code": 0,
            "file_changes": [],
        }
        assert not is_noise(rec)

    def test_calls_own_skill_is_noise(self):
        """调用自己的 MCP skill → 复用事件 → 噪声。"""
        rec = {
            "entry_ref": "doc_to_markdown",
            "argv": ["doc_to_markdown", "a.pdf"],
            "input_artifacts": [Artifact(path="a.pdf")],
            "output_artifacts": [Artifact(path="a.md")],
            "exit_code": 0,
            "file_changes": [],
        }
        assert is_noise(rec)

    def test_workspace_modification_is_noise(self):
        """file_changes 触及输出以外的工作区文件 → 副作用脚本 → 噪声。"""
        rec = {
            "entry_ref": "setup.py",
            "argv": ["python", "setup.py"],
            "input_artifacts": [Artifact(path="a.pdf")],
            "output_artifacts": [Artifact(path="a.md")],
            "exit_code": 0,
            "file_changes": [{"path": "config.json"}],  # 工作区文件
        }
        assert is_noise(rec)

    def test_file_change_within_outputs_not_noise(self):
        """file_changes 只含输出路径 → 正常写出行为 → 不是噪声。"""
        rec = {
            "entry_ref": "conv.py",
            "argv": ["python", "conv.py", "a.pdf"],
            "input_artifacts": [Artifact(path="a.pdf")],
            "output_artifacts": [Artifact(path="a.md")],
            "exit_code": 0,
            "file_changes": [{"path": "a.md"}],
        }
        assert not is_noise(rec)


# ---------------------------------------------------------------------------
# correlate
# ---------------------------------------------------------------------------

class TestCorrelate:
    def test_empty_events(self):
        assert correlate([]) == []

    def test_single_command_exec(self):
        ev = example_enriched_event()
        records = correlate([ev])
        assert len(records) == 1
        r = records[0]
        assert r["entry_ref"] == "conv.py"
        assert r["entry_kind"] == "script"
        assert r["exit_code"] == 0
        assert r["result_status"] == "success"
        assert len(r["input_artifacts"]) == 1
        assert r["input_artifacts"][0].path == "a.pdf"
        assert len(r["output_artifacts"]) == 1
        assert r["output_artifacts"][0].path == "a.md"

    def test_context_populated(self):
        ev = example_enriched_event()
        records = correlate([ev])
        ctx: ExecContext = records[0]["context"]
        assert ctx.task_id == "t-1"
        assert ctx.cwd == "/proj/A"
        assert ctx.session_id == "s-1"

    def test_source_trace_ids_contains_event_id(self):
        ev = example_enriched_event()
        records = correlate([ev])
        assert "evt-1" in records[0]["source_trace_ids"]

    def test_non_exec_event_ignored(self):
        """file_edit 事件没有 command_exec 相伴时，不产生候选。"""
        ev = _make_event(event_type="file_edit", argv=[])
        records = correlate([ev])
        assert records == []

    def test_groups_by_task_and_cwd(self):
        """不同 task_id / cwd 的 exec 事件产出两条候选。"""
        ev1 = _make_event(
            event_id="e1", task_id="t-A", cwd="/projA",
            argv=["python", "conv.py", "a.pdf"],
            input_artifacts=[Artifact(path="a.pdf", media_type="application/pdf")],
            output_artifacts=[Artifact(path="a.md")],
        )
        ev2 = _make_event(
            event_id="e2", task_id="t-B", cwd="/projB",
            argv=["python", "conv.py", "b.pdf"],
            input_artifacts=[Artifact(path="b.pdf", media_type="application/pdf")],
            output_artifacts=[Artifact(path="b.md")],
        )
        records = correlate([ev1, ev2])
        assert len(records) == 2

    def test_write_event_merges_source_id(self):
        """同 task_id+cwd 的 generated_code 事件 id 进入 source_trace_ids。"""
        write_ev = _make_event(
            event_id="e-write", task_id="t-1", cwd="/proj/A",
            event_type="generated_code",
            name="conv.py",
            argv=["conv.py"],
            input_artifacts=[],
            output_artifacts=[],
        )
        exec_ev = example_enriched_event()  # task_id="t-1", cwd="/proj/A"
        records = correlate([write_ev, exec_ev])
        assert len(records) == 1
        ids = records[0]["source_trace_ids"]
        assert "evt-1" in ids
        assert "e-write" in ids


# ---------------------------------------------------------------------------
# discover
# ---------------------------------------------------------------------------

class TestDiscover:
    def test_discover_from_example_event(self):
        """example_enriched_event → 1 Candidate。"""
        ev = example_enriched_event()
        candidates = discover([ev])
        assert len(candidates) == 1
        c = candidates[0]
        assert isinstance(c, Candidate)

    def test_candidate_stage_lifecycle(self):
        candidates = discover([example_enriched_event()])
        c = candidates[0]
        assert c.stage == "discovered"
        assert c.lifecycle == "raw"
        assert c.pipeline_status == "active"

    def test_candidate_fields(self):
        candidates = discover([example_enriched_event()])
        c = candidates[0]
        assert c.entry_ref == "conv.py"
        assert c.exit_code == 0
        assert c.result_status == "success"
        # source_trace_ids 不空
        assert c.source_trace_ids

    def test_candidate_input_profile_pdf(self):
        candidates = discover([example_enriched_event()])
        c = candidates[0]
        assert c.input_profile == "pdf_text"

    def test_candidate_artifacts_preserved(self):
        candidates = discover([example_enriched_event()])
        c = candidates[0]
        assert any(a.path == "a.pdf" for a in c.input_artifacts)
        assert any(a.path == "a.md" for a in c.output_artifacts)

    def test_discover_purpose_guess(self):
        candidates = discover([example_enriched_event()])
        assert candidates[0].purpose_guess == "document-to-markdown"

    def test_no_candidates_from_pure_compute(self):
        """纯计算事件（无 I/O）→ discover 产 0 候选。"""
        ev = _make_event(
            argv=["python", "calc.py"],
            input_artifacts=[],
            output_artifacts=[],
        )
        assert discover([ev]) == []

    def test_no_candidates_when_no_md_output(self):
        """无脚本入口 → 两域均不匹配 → 0 候选（阶段 3：generic 域会捕捉有入口的文件转换）。"""
        ev = _make_event(
            argv=[],
            name="",
            input_artifacts=[Artifact(path="a.pdf", media_type="application/pdf")],
            output_artifacts=[Artifact(path="a.md")],
        )
        assert discover([ev]) == []

    def test_no_candidates_when_exit_nonzero(self):
        ev = _make_event(
            argv=["python", "conv.py", "a.pdf"],
            exit_code=1,
            input_artifacts=[Artifact(path="a.pdf", media_type="application/pdf")],
            output_artifacts=[Artifact(path="a.md")],
        )
        assert discover([ev]) == []

    def test_multiple_events_produce_multiple_candidates(self):
        ev1 = _make_event(
            event_id="e1", task_id="t-1", cwd="/p1",
            argv=["python", "conv.py", "a.pdf"],
            input_artifacts=[Artifact(path="a.pdf", media_type="application/pdf")],
            output_artifacts=[Artifact(path="a.md")],
        )
        ev2 = _make_event(
            event_id="e2", task_id="t-2", cwd="/p2",
            argv=["python", "conv.py", "b.docx"],
            input_artifacts=[Artifact(
                path="b.docx",
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )],
            output_artifacts=[Artifact(path="b.md")],
        )
        candidates = discover([ev1, ev2])
        assert len(candidates) == 2

    def test_candidate_ids_unique(self):
        ev1 = _make_event(
            event_id="e1", task_id="t-1", cwd="/p1",
            argv=["python", "conv.py", "a.pdf"],
            input_artifacts=[Artifact(path="a.pdf", media_type="application/pdf")],
            output_artifacts=[Artifact(path="a.md")],
        )
        ev2 = _make_event(
            event_id="e2", task_id="t-2", cwd="/p2",
            argv=["python", "conv.py", "b.pdf"],
            input_artifacts=[Artifact(path="b.pdf", media_type="application/pdf")],
            output_artifacts=[Artifact(path="b.md")],
        )
        candidates = discover([ev1, ev2])
        ids = [c.id for c in candidates]
        assert len(ids) == len(set(ids)), "每个 Candidate 的 id 应唯一"

    def test_docx_input_profile(self):
        ev = _make_event(
            argv=["python", "conv.py", "b.docx"],
            input_artifacts=[Artifact(
                path="b.docx",
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )],
            output_artifacts=[Artifact(path="b.md")],
        )
        candidates = discover([ev])
        assert len(candidates) == 1
        assert candidates[0].input_profile == "office_docx"


# ---------------------------------------------------------------------------
# probe_determinism
# ---------------------------------------------------------------------------

class TestProbeDeterminism:
    def test_empty_code_all_false(self):
        signals = probe_determinism(example_candidate(), "")
        assert not signals.network_access
        assert not signals.external_model_call
        assert not signals.uses_time_or_random
        assert not signals.calls_system_binary
        assert signals.system_binaries == []

    def test_clean_conversion_code(self):
        """纯净 fitz 转换代码 → 所有信号 False。"""
        code = """
import fitz

def convert(path):
    doc = fitz.open(path)
    text = ""
    for page in doc:
        text += page.get_text()
    return text
"""
        signals = probe_determinism(example_candidate(), code)
        assert not signals.network_access
        assert not signals.external_model_call
        assert not signals.uses_time_or_random
        assert not signals.calls_system_binary

    def test_detects_soffice_subprocess(self):
        """subprocess 调用 soffice → calls_system_binary=True, libreoffice in list。"""
        code = (
            "import subprocess\n"
            "subprocess.run(['soffice', '--headless', '--convert-to', 'docx', input_path])"
        )
        signals = probe_determinism(example_candidate(), code)
        assert signals.calls_system_binary is True
        assert "libreoffice" in signals.system_binaries

    def test_detects_libreoffice_directly(self):
        code = "os.system('libreoffice --headless input.doc')"
        signals = probe_determinism(example_candidate(), code)
        assert signals.calls_system_binary is True
        assert "libreoffice" in signals.system_binaries

    def test_detects_win32com(self):
        """import win32com → calls_system_binary=True。"""
        code = "import win32com.client\napp = win32com.client.Dispatch('Word.Application')"
        signals = probe_determinism(example_candidate(), code)
        assert signals.calls_system_binary is True
        assert "win32com" in signals.system_binaries

    def test_detects_network_requests(self):
        code = "import requests\nresponse = requests.get(url)"
        signals = probe_determinism(example_candidate(), code)
        assert signals.network_access is True

    def test_detects_openai(self):
        code = "import openai\nclient = openai.OpenAI()"
        signals = probe_determinism(example_candidate(), code)
        assert signals.external_model_call is True

    def test_detects_random(self):
        code = "import random\nval = random.choice(['a', 'b'])"
        signals = probe_determinism(example_candidate(), code)
        assert signals.uses_time_or_random is True

    def test_detects_time(self):
        code = "import time\nts = time.time()"
        signals = probe_determinism(example_candidate(), code)
        assert signals.uses_time_or_random is True

    def test_multiple_binaries(self):
        """同时出现 soffice + tesseract → system_binaries 含两者。"""
        code = (
            "subprocess.run(['soffice', '--headless', src])\n"
            "subprocess.run(['tesseract', img, out])"
        )
        signals = probe_determinism(example_candidate(), code)
        assert signals.calls_system_binary is True
        assert "libreoffice" in signals.system_binaries
        assert "tesseract" in signals.system_binaries

    def test_replay_byte_identical_stays_none(self):
        """静态探测不设 replay_byte_identical（由 M3 回填）。"""
        signals = probe_determinism(example_candidate(), "import requests")
        assert signals.replay_byte_identical is None


# ---------------------------------------------------------------------------
# apply_gate0
# ---------------------------------------------------------------------------

class TestApplyGate0:
    def test_clean_candidate_stays_active(self):
        """无任何信号 → deterministic + active。"""
        signals = DeterminismSignals()
        c = apply_gate0(example_candidate(), signals)
        assert c.determinism == "deterministic"
        assert c.pipeline_status == "active"
        assert c.deferred_reason == ""
        assert c.requires_host_capability == []

    def test_system_binary_deferred_dependency(self):
        """系统二进制 → deferred + dependency + requires_host_capability 填上。"""
        signals = DeterminismSignals(
            calls_system_binary=True,
            system_binaries=["libreoffice"],
        )
        c = apply_gate0(example_candidate(), signals)
        assert c.pipeline_status == "deferred"
        assert c.deferred_reason == "dependency"
        assert "libreoffice" in c.requires_host_capability

    def test_system_binary_not_active(self):
        """系统依赖候选的 pipeline_status 绝不是 'active'。"""
        signals = DeterminismSignals(
            calls_system_binary=True,
            system_binaries=["libreoffice"],
        )
        c = apply_gate0(example_candidate(), signals)
        assert c.pipeline_status != "active"

    def test_win32com_deferred(self):
        signals = DeterminismSignals(
            calls_system_binary=True,
            system_binaries=["win32com"],
        )
        c = apply_gate0(example_candidate(), signals)
        assert c.pipeline_status == "deferred"
        assert c.deferred_reason == "dependency"
        assert "win32com" in c.requires_host_capability

    def test_nondeterministic_deferred(self):
        """非确定性（网络）→ deferred + nondeterministic。"""
        signals = DeterminismSignals(network_access=True)
        c = apply_gate0(example_candidate(), signals)
        assert c.determinism == "nondeterministic"
        assert c.pipeline_status == "deferred"
        assert c.deferred_reason == "nondeterministic"

    def test_external_model_deferred(self):
        signals = DeterminismSignals(external_model_call=True)
        c = apply_gate0(example_candidate(), signals)
        assert c.determinism == "nondeterministic"
        assert c.pipeline_status == "deferred"

    def test_mixed_system_binary_wins(self):
        """同时有网络 + 系统二进制 → mixed + dependency（系统二进制优先）。"""
        signals = DeterminismSignals(
            network_access=True,
            calls_system_binary=True,
            system_binaries=["libreoffice"],
        )
        c = apply_gate0(example_candidate(), signals)
        assert c.determinism == "mixed"
        assert c.pipeline_status == "deferred"
        assert c.deferred_reason == "dependency"
        assert "libreoffice" in c.requires_host_capability

    def test_does_not_mutate_original(self):
        """apply_gate0 不修改传入的 Candidate。"""
        original = example_candidate()
        original_status = original.pipeline_status
        signals = DeterminismSignals(
            calls_system_binary=True,
            system_binaries=["libreoffice"],
        )
        _ = apply_gate0(original, signals)
        assert original.pipeline_status == original_status

    def test_existing_capabilities_merged(self):
        """已有 requires_host_capability 不被覆盖，而是合并。"""
        cand = example_candidate()
        cand.requires_host_capability = ["some_existing_cap"]
        signals = DeterminismSignals(
            calls_system_binary=True,
            system_binaries=["libreoffice"],
        )
        c = apply_gate0(cand, signals)
        assert "libreoffice" in c.requires_host_capability
        assert "some_existing_cap" in c.requires_host_capability

    def test_multiple_capabilities(self):
        signals = DeterminismSignals(
            calls_system_binary=True,
            system_binaries=["libreoffice", "tesseract"],
        )
        c = apply_gate0(example_candidate(), signals)
        assert "libreoffice" in c.requires_host_capability
        assert "tesseract" in c.requires_host_capability

    def test_matches_example_deferred_candidate(self):
        """apply_gate0 的输出应与 contracts.example_deferred_candidate() 的字段一致。"""
        from distiller.contracts import example_deferred_candidate
        expected = example_deferred_candidate()
        signals = DeterminismSignals(
            calls_system_binary=True,
            system_binaries=["libreoffice"],
        )
        # 从纯净的 example_candidate 出发
        c = apply_gate0(example_candidate(), signals)
        assert c.pipeline_status == expected.pipeline_status
        assert c.deferred_reason == expected.deferred_reason
        assert "libreoffice" in c.requires_host_capability
