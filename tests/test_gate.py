"""tests/test_gate.py — M3 Replay Gate + 属性 Output Gate 测试

覆盖点：
  - check_integrity 通过/失败
  - measure_coverage 比例计算
  - detect_table_mode 识别 kv_list / pipe_table
  - output_gate 产出 pass + BehaviorSignature（所有字段）
  - replay 沙箱隔离（能用 temp 目录运行脚本并返回结果）

所有测试只用标准库 + distiller.contracts / .output_gate / .replay，无外部依赖。
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from distiller.contracts import Candidate, example_candidate
from distiller.output_gate import (
    BehaviorSignature,
    check_integrity,
    count_image_refs,
    detect_table_mode,
    measure_coverage,
    output_gate,
)
from distiller.replay import replay

# ===================================================================
# check_integrity
# ===================================================================


class TestCheckIntegrity:
    def test_passes_valid_markdown(self):
        md = "# Hello\n\nThis is a paragraph with **bold** text."
        assert check_integrity(md) is True

    def test_passes_markdown_with_table(self):
        md = "| A | B |\n|---|---|\n| 1 | 2 |"
        assert check_integrity(md) is True

    def test_passes_markdown_with_image(self):
        md = "Here is an image:\n\n![alt](assets/img.png)"
        assert check_integrity(md) is True

    def test_passes_markdown_with_list(self):
        md = "- item one\n- item two\n- item three"
        assert check_integrity(md) is True

    def test_fails_empty_string(self):
        assert check_integrity("") is False

    def test_fails_whitespace_only(self):
        assert check_integrity("   \n  \n  ") is False

    def test_fails_no_structure(self):
        assert check_integrity("just some plain text without markdown struct.") is False

    def test_fails_hanging_image_ref(self):
        md = "![alt]  (should not have space)\n\n![broken]"
        assert check_integrity(md) is False

    def test_passes_unicode_text(self):
        md = "# 标题\n\n这是一段中文文本。"
        assert check_integrity(md) is True

    def test_passes_code_block_only(self):
        md = "```\ncode block\n```"
        assert check_integrity(md) is True


# ===================================================================
# measure_coverage
# ===================================================================


class TestMeasureCoverage:
    def test_full_coverage(self):
        inp = "Hello world, this is the input text."
        out = "Hello world, this is the **input** text."
        cov = measure_coverage(inp, out)
        assert 0.9 <= cov <= 1.0

    def test_partial_coverage(self):
        inp = "A B C D E F G H I J K L M N O P"
        out = "# A B C"
        cov = measure_coverage(inp, out)
        assert 0.0 < cov < 0.5

    def test_zero_input_returns_zero(self):
        assert measure_coverage("", "Some output text") == 0.0

    def test_empty_output(self):
        assert measure_coverage("Some text", "") == 0.0

    def test_markdown_stripped_correctly(self):
        inp = "key: value"
        out = "| key | value |\n|-----|-------|\n| a   | b     |\n"
        cov = measure_coverage(inp, out)
        # 去标记后，"key: value" 与 "keyvalueab" 比
        assert 0.0 < cov <= 1.0


# ===================================================================
# count_image_refs
# ===================================================================


class TestCountImageRefs:
    def test_no_images(self):
        assert count_image_refs("Just text.") == 0

    def test_one_image(self):
        assert count_image_refs("![alt](img.png)") == 1

    def test_multiple_images(self):
        md = "![a](1.png) some text ![b](2.png) and ![c](3.png)"
        assert count_image_refs(md) == 3

    def test_images_with_assets_dir(self):
        md = "![x](assets/x.png)\n![y](assets/y.png)"
        assert count_image_refs(md) == 2


# ===================================================================
# detect_table_mode
# ===================================================================


class TestDetectTableMode:
    def test_pipe_table(self):
        md = "| Name | Age |\n|------|-----|\n| Alice | 30 |"
        assert detect_table_mode(md) == "pipe_table"

    def test_pipe_table_min_two_rows(self):
        md = "| A | B |\n| 1 | 2 |"
        assert detect_table_mode(md) == "pipe_table"

    def test_kv_list(self):
        md = "Name: Alice\nAge: 30\nLocation: Beijing"
        assert detect_table_mode(md) == "kv_list"

    def test_kv_list_with_colon(self):
        md = "name：张三\nage：25\ncity：上海"
        assert detect_table_mode(md) == "kv_list"

    def test_unknown_single_line(self):
        assert detect_table_mode("Just a line.") == "unknown"

    def test_unknown_empty(self):
        assert detect_table_mode("") == "unknown"

    def test_single_pipe_line_is_not_table(self):
        md = "| just one row |"
        assert detect_table_mode(md) == "unknown"


# ===================================================================
# output_gate — 主门禁函数
# ===================================================================


class TestOutputGate:
    def test_passes_pdf_text_profile(self):
        """pdf_text profile：文本覆盖通过 + integrity 通过 → pass"""
        cand = example_candidate()
        cand.input_profile = "pdf_text"
        output_md = "# Result\n\nThis is the converted content from the input document."
        input_text = "This is the converted content from the input document."
        gate_pass, bs = output_gate(cand, output_md, input_text)
        assert gate_pass is True
        assert isinstance(bs, BehaviorSignature)
        assert bs.markdown_valid is True

    def test_fails_integrity(self):
        """空输出 → integrity fail → gate fail"""
        cand = example_candidate()
        cand.input_profile = "pdf_text"
        gate_pass, bs = output_gate(cand, "", "some input")
        assert gate_pass is False
        assert bs.markdown_valid is False

    def test_pdf_scanned_requires_image(self):
        """pdf_scanned profile 需要至少 1 个图片引用"""
        cand = example_candidate()
        cand.input_profile = "pdf_scanned"
        output_md = "# Only text\n\nNo images here."
        input_text = "Only text No images here."
        gate_pass, bs = output_gate(cand, output_md, input_text)
        assert gate_pass is False

    def test_pdf_scanned_with_image_passes(self):
        """pdf_scanned profile 有图片引用则通过"""
        cand = example_candidate()
        cand.input_profile = "pdf_scanned"
        output_md = "# Scanned\n\n![diagram](assets/dia.png)\n\nText content."
        input_text = "Scanned diagram Text content."
        gate_pass, bs = output_gate(cand, output_md, input_text)
        assert gate_pass is True

    def test_xlsx_table_requires_table_structure(self):
        """xlsx_table profile：需要输出有表格标记"""
        cand = example_candidate()
        cand.input_profile = "xlsx_table"
        gate_pass, bs = output_gate(cand, "Just text.", "cell data")
        assert gate_pass is False

    def test_xlsx_table_with_table_passes(self):
        """xlsx_table profile：输出 pipe_table 则通过"""
        cand = example_candidate()
        cand.input_profile = "xlsx_table"
        md = "| A | B |\n| 1 | 2 |"
        gate_pass, bs = output_gate(cand, md, "cell data")
        assert gate_pass is True

    def test_behavior_signature_all_fields_present(self):
        """BehaviorSignature 所有字段齐全"""
        cand = example_candidate()
        cand.input_profile = "pdf_text"
        output_md = "# Hello\n\n![img](a.png)\n\n| K | V |\n|---|---|\n| a | 1 |"
        input_text = "Hello img a 1"
        gate_pass, bs = output_gate(cand, output_md, input_text)

        assert bs.markdown_valid is True
        assert bs.image_ref_coverage == 1.0
        assert bs.table_render_mode == "pipe_table"
        assert isinstance(bs.content_coverage_grade, str)
        assert bs.content_coverage_grade in ("A", "B", "C", "D")
        assert bs.schema_version == 1
        assert bs.is_thin_wrapper is False

    def test_default_profile_fallback(self):
        """未知 profile 走默认文本覆盖底线"""
        cand = example_candidate()
        cand.input_profile = "some_unknown_type"
        output_md = "# Some content\n\nText here."
        input_text = "Some content Text here."
        gate_pass, bs = output_gate(cand, output_md, input_text)
        assert gate_pass is True

    def test_assets_emitted_with_real_dir(self):
        """真实存在的 assets_dir → assets_emitted=True"""
        cand = example_candidate()
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建一个非空文件
            (Path(tmpdir) / "img.png").write_text("fake-image-data")
            output_md = "# Test\n\n![img](img.png)"
            gate_pass, bs = output_gate(
                cand, output_md, "Test img", assets_dir=tmpdir
            )
            assert bs.assets_emitted is True

    def test_no_assets_dir(self):
        """assets_dir 为空字符串 → assets_emitted=False"""
        cand = example_candidate()
        gate_pass, bs = output_gate(cand, "# Hi", "Hi")
        assert bs.assets_emitted is False


# ===================================================================
# replay — 沙箱重放（集成层面，只在有 Python 解释器时跑）
# ===================================================================


class TestReplay:
    def test_replay_basic_script(self):
        """临时目录中执行简单脚本并获取 stdout"""
        script = "import sys; sys.stdout.write('# Hello from replay\\n')"

        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "test_replay.py"
            script_path.write_text(script)

            input_path = Path(tmpdir) / "input.txt"
            input_path.write_text("dummy")

            result = replay(str(script_path), str(input_path), timeout=10)
            assert result["exit_code"] == 0
            assert "# Hello from replay" in result["stdout_md"]
            assert isinstance(result["duration_ms"], int)
            assert result["duration_ms"] >= 0

    def test_replay_script_with_exit_code(self):
        """脚本返回非零退出码"""
        script = "import sys; sys.exit(42)"
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "fail.py"
            script_path.write_text(script)

            input_path = Path(tmpdir) / "input.txt"
            input_path.write_text("dummy")

            result = replay(str(script_path), str(input_path), timeout=10)
            assert result["exit_code"] == 42

    def test_replay_timeout(self):
        """超时脚本返回 None exit_code"""
        script = "import time; time.sleep(10)"
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "slow.py"
            script_path.write_text(script)

            input_path = Path(tmpdir) / "input.txt"
            input_path.write_text("dummy")

            result = replay(str(script_path), str(input_path), timeout=1)
            assert result["exit_code"] is None
            assert "TIMEOUT" in result["stderr"]

    def test_replay_file_not_found(self):
        """不存在的脚本引发 FileNotFoundError"""
        with pytest.raises(FileNotFoundError):
            replay("/nonexistent/script.py", "input.txt", timeout=1)

    def test_replay_isolated_temp_dir(self):
        """验证脚本确实在 temp 目录中运行"""
        script = (
            "import os, sys\n"
            'sys.stdout.write(os.getcwd() + "\\n")\n'
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "whereami.py"
            script_path.write_text(script)

            input_path = Path(tmpdir) / "input.txt"
            input_path.write_text("dummy")

            result = replay(str(script_path), str(input_path), timeout=10)
            assert result["exit_code"] == 0
            cwd_out = result["stdout_md"].strip()
            # 应包含 temp 路径特征（distiller-replay- 前缀）
            assert "distiller-replay-" in cwd_out
