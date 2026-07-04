"""generic_file_transform 能力域（阶段 3：第二个 domain，逼出共性边界）。

覆盖个人高频文件转换：CSV↔JSON、log→md、txt→md、目录索引等。
与 document_to_markdown 的区别：不对输出做"必须是合法 markdown 且包含标题/表格/图片之一"
的硬要求——只做可验证底线（输出存在、非空、行数/字段数/文本覆盖有基本守恒）。

gate 产物仍是全局统一的 BehaviorSignature（合并主轴不下放）。
"""
from __future__ import annotations

import csv
import io
import json as _json
from pathlib import Path
from typing import Any

from ..contracts import Artifact, BehaviorSignature, Candidate, ContractSignature
from ..output_gate import measure_coverage

DOMAIN_NAME = "generic_file_transform"

# 结构化格式对 (in, out)：需要行级/字段级守恒
_STRUCTURED_PAIRS = frozenset({
    ("text/csv", "application/json"),
    ("application/json", "text/csv"),
    ("application/json", "text/csv"),
})


def _media_pair(cand: Candidate):
    inp = cand.input_artifacts[0].media_type if cand.input_artifacts else ""
    out = cand.output_artifacts[0].media_type if cand.output_artifacts else ""
    return inp, out


def _conservation_pass(in_text: str, out_text: str, pair: tuple[str, str]) -> bool:
    """按媒体类型对做最低守恒检查，防止假转换（读 CSV 吐一行 hello）被误放行。"""
    inp_media, out_media = pair

    # csv → json：数据行数守恒（CSV 含 header，JSON 不含，减 1）
    if inp_media == "text/csv" and out_media == "application/json":
        try:
            in_rows = max(0, sum(1 for _ in csv.reader(io.StringIO(in_text))) - 1)
            out_data = _json.loads(out_text)
            out_rows = len(out_data) if isinstance(out_data, list) else 1
            return in_rows == out_rows
        except (csv.Error, _json.JSONDecodeError, ValueError):
            return False

    # json → csv：行数守恒
    if inp_media == "application/json" and out_media == "text/csv":
        try:
            in_data = _json.loads(in_text)
            in_rows = len(in_data) if isinstance(in_data, list) else 1
            out_rows = sum(1 for _ in csv.reader(io.StringIO(out_text)))
            return in_rows == out_rows
        except (_json.JSONDecodeError, csv.Error, ValueError):
            return False

    # 文本型：覆盖率 ≥ 0.30（比 doc 域宽松，不要求合法 markdown 结构）
    inp_media_prefix = inp_media.split("/")[0] if inp_media else ""
    out_media_prefix = out_media.split("/")[0] if out_media else ""
    if inp_media_prefix == "text" and out_media_prefix == "text":
        return measure_coverage(in_text, out_text) >= 0.30

    # 默认：输出存在、非空即可
    return bool(out_text and out_text.strip())


class GenericFileTransformDomain:
    name = DOMAIN_NAME
    version = 1

    def shape_match(self, record: dict[str, Any]) -> bool:
        """通用文件转换形状：有入口、有输入文件、有输出文件、成功、入出路径不同。"""
        entry_ref = record.get("entry_ref", "")
        if not entry_ref:
            return False
        if record.get("exit_code") != 0:
            return False
        inputs: list[Artifact] = record.get("input_artifacts", [])
        outputs: list[Artifact] = record.get("output_artifacts", [])
        if not inputs or not outputs:
            return False
        inp_paths = {a.path for a in inputs}
        out_paths = {a.path for a in outputs}
        if inp_paths & out_paths:
            return False  # 覆盖输入 = 危险，不提名为候选
        return True

    def guess_input_profile(self, input_artifacts: list[Artifact]) -> str:
        if not input_artifacts:
            return "unknown"
        mt = (input_artifacts[0].media_type or "").lower()
        # coarse profile for gate branching
        if "csv" in mt:
            return "csv"
        if "json" in mt:
            return "json"
        if mt.startswith("text/"):
            return "text"
        return "unknown"

    def purpose_guess(self, record: dict[str, Any]) -> str:
        inp = record.get("input_artifacts", [])
        out = record.get("output_artifacts", [])
        in_label = _ext_label(inp) if inp else "file"
        out_label = _ext_label(out) if out else "output"
        return f"convert-{in_label}-to-{out_label}"

    def read_input_text(self, cand: Candidate) -> str:
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

    def coverage_unmeasurable(self, cand: Candidate, input_text: str) -> bool:
        return not bool(input_text)

    def gate(
        self, cand: Candidate, output_text: str, input_text: str
    ) -> tuple[bool, BehaviorSignature]:
        """通用 gate：行级/字段级/文本覆盖守恒 + 输出基本合法性。"""
        integrity = bool(output_text and output_text.strip())
        pair = _media_pair(cand)
        conserved = _conservation_pass(input_text, output_text, pair)

        gate_pass = integrity and conserved

        bs = BehaviorSignature(
            markdown_valid=True,  # 非 md 域不要求 md 结构，总是 True
            assets_emitted=False,
            image_ref_coverage=0.0,
            heading_preservation=0.0,
            content_coverage_grade="C" if conserved else "D",
            table_render_mode="unknown",
            key_value_rendering=False,
            is_thin_wrapper=False,
        )
        return gate_pass, bs

    def branch_key(self, cand: Candidate, sig: ContractSignature) -> str:
        inp, out = _media_pair(cand)
        if inp and out:
            return f"{_short(inp)}_to_{_short(out)}"
        return "file_transform"


def _short(media_type: str) -> str:
    return media_type.split("/")[-1].split(".")[-1][:20]


def _ext_label(artifacts: list[Artifact]) -> str:
    mt = (artifacts[0].media_type or "").lower() if artifacts else ""
    if mt:
        return mt.split("/")[-1]
    return "file"
