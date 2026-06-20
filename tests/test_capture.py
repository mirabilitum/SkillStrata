"""tests/test_capture.py — M1 采集 + enrichment 单元测试。

只用标准库 + pytest；无需额外装包。
"""
from __future__ import annotations

import json
import tempfile
import uuid
from dataclasses import asdict
from pathlib import Path

import pytest

from distiller.capture import REDACTION_VERSION, append_event, build_raw_event, fast_redact
from distiller.contracts import EnrichedToolEvent, RawToolEvent, example_raw_event
from distiller.enrich import enrich


# =========================================================================== #
# build_raw_event
# =========================================================================== #


def _bash_payload(**overrides) -> dict:
    """最小合法 CC PostToolUse payload（Bash 工具）。"""
    payload: dict = {
        "session_id": "s-test",
        "tool_name": "Bash",
        "tool_input": {"command": "python conv.py a.pdf"},
        "tool_response": {"returnCode": 0},
        "cwd": "/proj/A",
    }
    payload.update(overrides)
    return payload


class TestBuildRawEvent:
    def test_returns_raw_tool_event_instance(self):
        evt = build_raw_event(_bash_payload())
        assert isinstance(evt, RawToolEvent)

    def test_session_id_propagated(self):
        evt = build_raw_event(_bash_payload())
        assert evt.session_id == "s-test"

    def test_event_type_command_exec_for_bash(self):
        evt = build_raw_event(_bash_payload())
        assert evt.event_type == "command_exec"

    def test_event_type_file_edit_for_write(self):
        payload = {
            "session_id": "s-2",
            "tool_name": "Write",
            "tool_input": {"path": "/proj/A/out.md", "content": "# Hello"},
            "tool_response": {},
            "cwd": "/proj/A",
        }
        evt = build_raw_event(payload)
        assert evt.event_type == "file_edit"

    def test_exit_code_parsed_from_return_code(self):
        evt = build_raw_event(_bash_payload())
        assert evt.exit_code == 0

    def test_exit_code_none_when_absent(self):
        payload = _bash_payload()
        payload["tool_response"] = {}
        evt = build_raw_event(payload)
        assert evt.exit_code is None

    def test_argv_split_from_command(self):
        evt = build_raw_event(_bash_payload())
        assert evt.argv == ["python", "conv.py", "a.pdf"]

    def test_cwd_propagated(self):
        evt = build_raw_event(_bash_payload())
        assert evt.cwd == "/proj/A"

    def test_host_agent_default_claude_code(self):
        evt = build_raw_event(_bash_payload())
        assert evt.host_agent == "claude-code"

    def test_host_agent_override(self):
        evt = build_raw_event(_bash_payload(), host_agent="codex")
        assert evt.host_agent == "codex"

    def test_event_id_is_valid_uuid(self):
        evt = build_raw_event(_bash_payload())
        # Should not raise
        uuid.UUID(evt.event_id)

    def test_timestamp_nonempty_and_contains_T(self):
        evt = build_raw_event(_bash_payload())
        assert "T" in evt.timestamp  # ISO 8601 格式

    def test_redaction_version_set(self):
        evt = build_raw_event(_bash_payload())
        assert evt.redaction_version == REDACTION_VERSION

    def test_redacted_fields_initially_empty(self):
        evt = build_raw_event(_bash_payload())
        assert evt.redacted_fields == []

    def test_name_is_command_string(self):
        evt = build_raw_event(_bash_payload())
        # name 应该是原始命令字符串，不是分割后的 argv[0]
        assert evt.name == "python conv.py a.pdf"

    def test_to_dict_roundtrip(self):
        """asdict → RawToolEvent(**d) 还原要完整一致。"""
        evt = build_raw_event(_bash_payload())
        d = asdict(evt)
        restored = RawToolEvent(**d)
        assert restored.event_id == evt.event_id
        assert restored.session_id == evt.session_id
        assert restored.argv == evt.argv

    def test_message_id_in_source_ref_when_present(self):
        payload = _bash_payload()
        payload["message_id"] = "msg-999"
        evt = build_raw_event(payload)
        assert evt.source_ref.get("message_id") == "msg-999"

    def test_unknown_tool_defaults_to_tool_call(self):
        payload = {
            "session_id": "s-x",
            "tool_name": "SomeUnknownTool",
            "tool_input": {},
            "tool_response": {},
            "cwd": "/tmp",
        }
        evt = build_raw_event(payload)
        assert evt.event_type == "tool_call"


# =========================================================================== #
# fast_redact
# =========================================================================== #


class TestFastRedact:
    def test_no_secrets_no_change(self):
        argv = ["python", "conv.py", "a.pdf"]
        result, fields = fast_redact(argv, set())
        assert result == argv
        assert fields == []

    def test_token_flag_redacted(self):
        argv = ["curl", "--token=supersecret", "https://example.com"]
        result, fields = fast_redact(argv, set())
        assert result[1] == "--token=REDACTED"
        assert "token" in fields

    def test_api_key_flag_redacted(self):
        argv = ["tool", "--api-key=my-key-123"]
        result, fields = fast_redact(argv, set())
        assert result[1] == "--api-key=REDACTED"
        assert any("api" in f for f in fields)

    def test_api_underscore_key_flag_redacted(self):
        argv = ["tool", "--api_key=my-key-123"]
        result, fields = fast_redact(argv, set())
        assert result[1] == "--api_key=REDACTED"
        assert "api_key" in fields

    def test_authorization_bearer_header_redacted(self):
        argv = ["curl", "-H", "Authorization: Bearer token123"]
        result, fields = fast_redact(argv, set())
        # 值被脱敏，"Authorization:" 前缀保留
        assert result[2].startswith("Authorization:")
        assert "REDACTED" in result[2]
        assert "Authorization" in fields

    def test_authorization_lowercase_header_redacted(self):
        argv = ["tool", "authorization: Bearer secret"]
        result, fields = fast_redact(argv, set())
        assert "REDACTED" in result[1]

    def test_known_secret_exact_match_redacted(self):
        argv = ["curl", "mysecretvalue", "https://example.com"]
        result, fields = fast_redact(argv, {"mysecretvalue"})
        assert result[1] == "REDACTED"
        assert len(fields) > 0

    def test_known_secret_no_partial_match(self):
        """精确值匹配：子串不应触发脱敏。"""
        argv = ["curl", "mysecretvalue_extra", "url"]
        result, fields = fast_redact(argv, {"mysecretvalue"})
        assert result[1] == "mysecretvalue_extra"  # 未脱敏
        assert fields == []

    def test_empty_flag_value_not_redacted(self):
        """--token= 没有值时不脱敏（值长度为 0）。"""
        argv = ["tool", "--token="]
        result, fields = fast_redact(argv, set())
        # len(arg) == len(prefix)，不满足 len(arg) > len(prefix)
        assert result[1] == "--token="
        assert fields == []

    def test_non_secret_flag_unchanged(self):
        argv = ["python", "script.py", "--output=results.json", "--verbose"]
        result, fields = fast_redact(argv, set())
        assert result == argv
        assert fields == []

    def test_multiple_secrets_in_argv(self):
        argv = ["tool", "--token=abc", "--password=xyz", "run"]
        result, fields = fast_redact(argv, set())
        assert result[1] == "--token=REDACTED"
        assert result[2] == "--password=REDACTED"
        assert len(fields) == 2

    def test_original_argv_not_mutated(self):
        argv = ["tool", "--token=secret"]
        original = list(argv)
        fast_redact(argv, set())
        assert argv == original  # 原列表不被修改

    def test_empty_argv(self):
        result, fields = fast_redact([], set())
        assert result == []
        assert fields == []


# =========================================================================== #
# append_event
# =========================================================================== #


class TestAppendEvent:
    def _make_raw(self, session_id: str = "s-test") -> RawToolEvent:
        evt = example_raw_event()
        evt.session_id = session_id
        return evt

    def test_creates_jsonl_file(self):
        with tempfile.TemporaryDirectory() as td:
            traces = Path(td) / "traces"
            traces.mkdir()
            raw = self._make_raw()
            append_event(traces, raw)
            jsonl = traces / raw.session_id / "events.jsonl"
            assert jsonl.exists()

    def test_event_readable_back(self):
        with tempfile.TemporaryDirectory() as td:
            traces = Path(td) / "traces"
            traces.mkdir()
            raw = self._make_raw()
            append_event(traces, raw)
            jsonl = traces / raw.session_id / "events.jsonl"
            lines = jsonl.read_text(encoding="utf-8").strip().splitlines()
            assert len(lines) == 1
            d = json.loads(lines[0])
            assert d["event_id"] == raw.event_id
            assert d["session_id"] == raw.session_id

    def test_appends_multiple_events_same_session(self):
        with tempfile.TemporaryDirectory() as td:
            traces = Path(td) / "traces"
            traces.mkdir()
            raw1 = self._make_raw("sess-A")
            raw2 = self._make_raw("sess-A")
            raw2.event_id = str(uuid.uuid4())  # 不同 event_id
            append_event(traces, raw1)
            append_event(traces, raw2)
            jsonl = traces / "sess-A" / "events.jsonl"
            lines = jsonl.read_text(encoding="utf-8").strip().splitlines()
            assert len(lines) == 2

    def test_separate_sessions_separate_files(self):
        with tempfile.TemporaryDirectory() as td:
            traces = Path(td) / "traces"
            traces.mkdir()
            append_event(traces, self._make_raw("sess-X"))
            append_event(traces, self._make_raw("sess-Y"))
            assert (traces / "sess-X" / "events.jsonl").exists()
            assert (traces / "sess-Y" / "events.jsonl").exists()

    def test_each_line_valid_json(self):
        with tempfile.TemporaryDirectory() as td:
            traces = Path(td) / "traces"
            traces.mkdir()
            for _ in range(3):
                append_event(traces, self._make_raw("s-multi"))
            jsonl = traces / "s-multi" / "events.jsonl"
            for line in jsonl.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    json.loads(line)  # 不应抛出

    def test_roundtrip_preserves_argv(self):
        with tempfile.TemporaryDirectory() as td:
            traces = Path(td) / "traces"
            traces.mkdir()
            raw = self._make_raw()
            raw.argv = ["python", "conv.py", "a.pdf"]
            append_event(traces, raw)
            jsonl = traces / raw.session_id / "events.jsonl"
            d = json.loads(jsonl.read_text(encoding="utf-8").strip())
            assert d["argv"] == ["python", "conv.py", "a.pdf"]

    def test_auto_creates_traces_subdir(self):
        """traces_dir 下的 session 子目录不存在时应自动创建。"""
        with tempfile.TemporaryDirectory() as td:
            # traces 目录本身不预先创建
            traces = Path(td) / "traces" / "deep"
            raw = self._make_raw("s-deep")
            append_event(traces, raw)
            jsonl = traces / "s-deep" / "events.jsonl"
            assert jsonl.exists()

    def test_unknown_session_id_handled(self):
        """session_id 为空时不崩溃，写入 'unknown' 子目录。"""
        with tempfile.TemporaryDirectory() as td:
            traces = Path(td) / "traces"
            traces.mkdir()
            raw = self._make_raw("")
            raw.session_id = ""
            append_event(traces, raw)
            # 不崩溃即通过；"unknown" 子目录应存在
            assert (traces / "unknown" / "events.jsonl").exists()


# =========================================================================== #
# enrich
# =========================================================================== #


class TestEnrich:
    def _make_raw(self) -> RawToolEvent:
        return example_raw_event()

    def test_returns_enriched_tool_event(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            in_file = td / "a.pdf"
            in_file.write_bytes(b"%PDF-1.4 fake")
            out_file = td / "a.md"
            out_file.write_text("# Result", encoding="utf-8")
            raw = self._make_raw()
            result = enrich(raw, input_paths=[in_file], output_paths=[out_file], artifacts_dir=td)
            assert isinstance(result, EnrichedToolEvent)

    def test_input_artifact_hash_set_and_prefixed(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            in_file = td / "a.pdf"
            in_file.write_bytes(b"%PDF-1.4 fake content")
            raw = self._make_raw()
            result = enrich(raw, input_paths=[in_file], output_paths=[], artifacts_dir=td)
            h = result.input_artifacts[0].hash
            assert h.startswith("blake2b:")
            assert len(h) > 10  # 不只是前缀

    def test_pdf_media_type_detected(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            in_file = td / "a.pdf"
            in_file.write_bytes(b"%PDF-1.4")
            raw = self._make_raw()
            result = enrich(raw, input_paths=[in_file], output_paths=[], artifacts_dir=td)
            assert result.input_artifacts[0].media_type == "application/pdf"

    def test_markdown_media_type_detected(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            out_file = td / "result.md"
            out_file.write_text("# Hello", encoding="utf-8")
            raw = self._make_raw()
            result = enrich(raw, input_paths=[], output_paths=[out_file], artifacts_dir=td)
            mt = result.output_artifacts[0].media_type
            assert mt in ("text/markdown", "text/x-markdown"), f"unexpected media type: {mt!r}"

    def test_soffice_detected_as_system_binary(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            raw = self._make_raw()
            raw.argv = ["soffice", "--headless", "--convert-to", "pdf", "doc.docx"]
            raw.name = "soffice --headless --convert-to pdf doc.docx"
            result = enrich(raw, input_paths=[], output_paths=[], artifacts_dir=td)
            assert result.determinism_signals.calls_system_binary is True
            assert "soffice" in result.determinism_signals.system_binaries

    def test_libreoffice_detected_as_system_binary(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            raw = self._make_raw()
            raw.argv = ["libreoffice", "--headless", "in.docx"]
            raw.name = "libreoffice --headless in.docx"
            result = enrich(raw, input_paths=[], output_paths=[], artifacts_dir=td)
            assert result.determinism_signals.calls_system_binary is True
            assert "libreoffice" in result.determinism_signals.system_binaries

    def test_normal_python_script_no_system_binary(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            raw = self._make_raw()
            raw.argv = ["python", "conv.py", "a.pdf"]
            raw.name = "python conv.py a.pdf"
            result = enrich(raw, input_paths=[], output_paths=[], artifacts_dir=td)
            assert result.determinism_signals.calls_system_binary is False
            assert result.determinism_signals.system_binaries == []

    def test_raw_reference_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            raw = self._make_raw()
            result = enrich(raw, input_paths=[], output_paths=[], artifacts_dir=td)
            assert result.raw is raw

    def test_different_files_have_different_hashes(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            in_file = td / "a.pdf"
            in_file.write_bytes(b"%PDF-1.4 fake pdf content UNIQUE_A")
            out_file = td / "a.md"
            out_file.write_text("# Converted content UNIQUE_B", encoding="utf-8")
            raw = self._make_raw()
            result = enrich(raw, input_paths=[in_file], output_paths=[out_file], artifacts_dir=td)
            in_hash = result.input_artifacts[0].hash
            out_hash = result.output_artifacts[0].hash
            assert in_hash != out_hash
            assert in_hash.startswith("blake2b:")
            assert out_hash.startswith("blake2b:")

    def test_empty_paths_yields_empty_artifact_lists(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            raw = self._make_raw()
            result = enrich(raw, input_paths=[], output_paths=[], artifacts_dir=td)
            assert result.input_artifacts == []
            assert result.output_artifacts == []

    def test_determinism_signals_type(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            raw = self._make_raw()
            result = enrich(raw, input_paths=[], output_paths=[], artifacts_dir=td)
            from distiller.contracts import DeterminismSignals
            assert isinstance(result.determinism_signals, DeterminismSignals)

    def test_replay_byte_identical_initially_none(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            raw = self._make_raw()
            result = enrich(raw, input_paths=[], output_paths=[], artifacts_dir=td)
            # 实测重放回填前应为 None
            assert result.determinism_signals.replay_byte_identical is None

    def test_multiple_input_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            f1 = td / "doc1.pdf"
            f2 = td / "doc2.pdf"
            f1.write_bytes(b"PDF1")
            f2.write_bytes(b"PDF2")
            raw = self._make_raw()
            result = enrich(raw, input_paths=[f1, f2], output_paths=[], artifacts_dir=td)
            assert len(result.input_artifacts) == 2
            assert result.input_artifacts[0].hash != result.input_artifacts[1].hash

    def test_network_access_detected_from_argv(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            raw = self._make_raw()
            raw.argv = ["curl", "https://api.example.com/data"]
            raw.name = "curl https://api.example.com/data"
            result = enrich(raw, input_paths=[], output_paths=[], artifacts_dir=td)
            assert result.determinism_signals.network_access is True
