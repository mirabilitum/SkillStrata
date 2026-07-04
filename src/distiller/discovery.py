"""M2 · 候选发现（discovery）

候选发现是高召回提名器，不是精度过滤器。原则：
  - 便宜：只用已有字段，不跑重活。
  - 高召回：形状中 + 非噪声 = 提名，让下游 Gate 去筛。
  - 按入口/目的提名，不按函数切碎，不沿链展开（§4 粒度边界）。

对照：候选发现规则.md / v0.4 §13.2 step2 / contracts.py。
只依赖标准库 + distiller.contracts，不引入任何第三方包。
"""
from __future__ import annotations

import os
import uuid
from collections import defaultdict
from typing import Any, Optional

from distiller.contracts import (
    Artifact,
    Candidate,
    EnrichedToolEvent,
    ExecContext,
)

# ---------------------------------------------------------------------------
# 文档类型判定
# ---------------------------------------------------------------------------

# 已识别文档 media_type（pdf/docx/xlsx/pptx/html 系列）
_KNOWN_DOC_MEDIA_TYPES: frozenset[str] = frozenset({
    "application/pdf",
    # Word
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.oasis.opendocument.text",
    # Excel
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.oasis.opendocument.spreadsheet",
    # PowerPoint
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.oasis.opendocument.presentation",
    # HTML
    "text/html",
    "application/xhtml+xml",
    # RTF/EPUB
    "application/rtf",
    "text/rtf",
    "application/epub+zip",
})

# 已识别文档扩展名（无 media_type 时按文件扩展名判断）
_KNOWN_DOC_EXTENSIONS: frozenset[str] = frozenset({
    ".pdf",
    ".doc", ".docx", ".odt", ".rtf",
    ".xls", ".xlsx", ".ods", ".csv",
    ".ppt", ".pptx", ".odp",
    ".html", ".htm", ".xhtml",
    ".epub",
})

# 已知转换库（佐证信号，不是过滤条件）
_KNOWN_CONVERT_LIBS: frozenset[str] = frozenset({
    "fitz", "pymupdf", "pdfplumber", "pdfminer",
    "docx", "python-docx",
    "openpyxl", "xlrd", "xlwt",
    "pptx", "python-pptx",
    "markitdown", "pandoc",
    "html2text", "html2markdown",
    "ebooklib",
})

# 我们自己已转正的 MCP 工具 / skill 名称（调这些 = 复用事件，不是新候选）
_OWN_SKILL_NAMES: frozenset[str] = frozenset({
    "doc_to_markdown",
    "distiller",
    "distiller-mcp",
})


def _is_doc_artifact(artifact: Artifact) -> bool:
    """判断一个 artifact 是否是已识别的文档类型。"""
    if artifact.media_type and artifact.media_type in _KNOWN_DOC_MEDIA_TYPES:
        return True
    _, ext = os.path.splitext(artifact.path.lower())
    return ext in _KNOWN_DOC_EXTENSIONS


def _has_md_output(artifacts: list[Artifact]) -> bool:
    """判断 artifacts 中是否含 .md 文件。"""
    return any(a.path.endswith(".md") for a in artifacts)


def _extract_entry(argv: list[str], name: str) -> tuple[str, str]:
    """从 argv / name 提取 (entry_ref, entry_kind)。

    优先找 .py / .sh 脚本；其余当命令。
    """
    for arg in argv:
        if arg.endswith(".py") or arg.endswith(".sh"):
            return arg, "script"
    # 检查 -m module 形式
    if "-m" in argv:
        idx = argv.index("-m")
        if idx + 1 < len(argv):
            return f"-m {argv[idx+1]}", "script"
    # 取第一个参数或 name 作为命令入口
    entry = argv[0] if argv else name
    return entry, "command"


def _guess_input_profile(artifacts: list[Artifact]) -> str:
    """粗判 input_profile（pdf_text / office_docx / office_xlsx / office_pptx / html / …）。

    只取第一个匹配。发现层不细判 pdf_text vs pdf_scanned——那是 Gate0/M3 的活。
    """
    for a in artifacts:
        mt = a.media_type.lower() if a.media_type else ""
        ext = os.path.splitext(a.path.lower())[1]
        if mt == "application/pdf" or ext == ".pdf":
            return "pdf_text"
        if "word" in mt or "opendocument.text" in mt or ext in (".docx", ".odt"):
            return "office_docx"
        if ext == ".doc":
            return "office_legacy"
        if "spreadsheet" in mt or "excel" in mt or ext in (".xlsx", ".ods"):
            return "office_xlsx"
        if ext == ".xls":
            return "office_legacy"
        if "presentation" in mt or "powerpoint" in mt or ext in (".pptx", ".odp"):
            return "office_pptx"
        if ext == ".ppt":
            return "office_legacy"
        if "html" in mt or ext in (".html", ".htm", ".xhtml"):
            return "html"
        if ext == ".epub":
            return "epub"
    return "unknown"


# ---------------------------------------------------------------------------
# correlate: 把多条 EnrichedToolEvent 拼成候选记录原料
# ---------------------------------------------------------------------------

def correlate(events: list[EnrichedToolEvent]) -> list[dict[str, Any]]:
    """按 task_id + cwd + 时序把多条事件拼成"候选记录原料"。

    关联键（强→弱）：
      1. task_id（同一任务）
      2. cwd + 脚本文件名（写入事件 + 调用事件 → 同脚本）
      3. 时间邻近 + artifact 路径衔接

    产出每个 command_exec 事件对应一条 record（dict），字段：
      entry_kind / entry_ref / argv / input_artifacts / output_artifacts /
      exit_code / result_status / context / source_trace_ids / file_changes
    """
    if not events:
        return []

    # 1. 按 (task_id, cwd) 分组，组内按 timestamp 排序
    groups: dict[tuple[str, str], list[EnrichedToolEvent]] = defaultdict(list)
    for ev in events:
        key = (ev.raw.task_id, ev.raw.cwd)
        groups[key].append(ev)

    records: list[dict[str, Any]] = []

    for (task_id, cwd), group in groups.items():
        group_sorted = sorted(group, key=lambda e: e.raw.timestamp)

        # 按事件类型分开
        exec_events = [e for e in group_sorted if e.raw.event_type == "command_exec"]
        write_events = [e for e in group_sorted
                        if e.raw.event_type in ("generated_code", "file_edit")]

        for exec_ev in exec_events:
            argv = list(exec_ev.raw.argv)
            entry_ref, entry_kind = _extract_entry(argv, exec_ev.raw.name)

            # 找关联的代码写入事件（同脚本名）
            related_writes = [
                w for w in write_events
                if entry_ref and (
                    entry_ref in w.raw.name
                    or any(entry_ref in a for a in w.raw.argv)
                )
            ]

            # 合并 artifacts（优先用 exec 事件自带的；去重）
            all_inputs: list[Artifact] = list(exec_ev.input_artifacts)
            all_outputs: list[Artifact] = list(exec_ev.output_artifacts)

            # 写入事件可能带有额外 output artifact（代码快照本身）
            for w in related_writes:
                for a in w.output_artifacts:
                    if a.path not in {x.path for x in all_outputs}:
                        all_outputs.append(a)

            # source_trace_ids：exec 事件 + 关联写入事件
            source_trace_ids = [exec_ev.raw.event_id] + [w.raw.event_id for w in related_writes]

            # file_changes 只取 exec 事件的（代表转换过程的副作用），
            # 不含写入事件的 file_changes（那是写脚本，不是转换副作用）
            exec_file_changes = list(exec_ev.file_changes)

            exit_code = exec_ev.raw.exit_code
            result_status = "success" if exit_code == 0 else "error"

            context = ExecContext(
                task_id=task_id,
                cwd=cwd,
                session_id=exec_ev.raw.session_id,
                source_ref=exec_ev.raw.source_ref,
            )

            records.append({
                "entry_kind": entry_kind,
                "entry_ref": entry_ref,
                "argv": argv,
                "input_artifacts": all_inputs,
                "output_artifacts": all_outputs,
                "exit_code": exit_code,
                "result_status": result_status,
                "context": context,
                "source_trace_ids": source_trace_ids,
                "file_changes": exec_file_changes,
                "determinism_signals": exec_ev.determinism_signals,
            })

    return records


# ---------------------------------------------------------------------------
# shape_match: MVP 形状过滤
# ---------------------------------------------------------------------------

def shape_match(record: dict[str, Any]) -> bool:
    """MVP 形状过滤——同时满足以下 5 条才返回 True：

    1. 单入口：有可辨入口（entry_ref 非空）
    2. 文件进：input_artifacts 非空，且至少一个是已识别文档类型
    3. md 出：output_artifacts 中含 .md 文件
    4. 成功：exit_code == 0
    5. 入口可定位（entry_ref 可作为重放入口）

    高召回：只要形状符合就提名，不做价值判断。
    """
    # 1 & 5: 有可辨入口
    entry_ref = record.get("entry_ref", "")
    if not entry_ref:
        return False

    # 4: 成功执行
    exit_code = record.get("exit_code")
    if exit_code != 0:
        return False

    # 2: 文件进，且是文档类型
    inputs: list[Artifact] = record.get("input_artifacts", [])
    if not inputs:
        return False
    if not any(_is_doc_artifact(a) for a in inputs):
        return False

    # 3: md 出
    outputs: list[Artifact] = record.get("output_artifacts", [])
    if not _has_md_output(outputs):
        return False

    return True


# ---------------------------------------------------------------------------
# is_noise: 噪声预过滤
# ---------------------------------------------------------------------------

def is_noise(record: dict[str, Any]) -> bool:
    """噪声预过滤——廉价规则砍掉明显不是工具的，任一命中返回 True：

    - 纯计算/探针：无文件 I/O
    - 一次性 REPL 试探：无可辨入口
    - 调用已转正能力（warm-start 复用事件，非新候选）
    - 改动工作区：file_changes 触及输出以外的工作区文件
    """
    inputs: list[Artifact] = record.get("input_artifacts", [])
    outputs: list[Artifact] = record.get("output_artifacts", [])

    # 1. 无文件 I/O → 纯计算/探针
    if not inputs and not outputs:
        return True

    # 2. 无入口 → REPL 试探（短暂、无法重放）
    entry_ref = record.get("entry_ref", "")
    if not entry_ref:
        return True

    # 3. 调用已转正能力 → warm-start 复用事件
    argv: list[str] = record.get("argv", [])
    if entry_ref in _OWN_SKILL_NAMES:
        return True
    if argv and argv[0] in _OWN_SKILL_NAMES:
        return True

    # 4. file_changes 触及输出以外的工作区文件 → 疑似副作用脚本
    output_paths: set[str] = {a.path for a in outputs}
    for change in record.get("file_changes", []):
        if isinstance(change, dict):
            changed_path = change.get("path", "")
        else:
            changed_path = str(change)
        if not changed_path:
            continue
        # 跳过临时路径 / 隐藏文件（OS 级副产物，不算工作区改动）
        if changed_path.startswith(("/tmp/", "/var/tmp/", "C:\\Temp\\", os.sep + ".")):
            continue
        if os.path.basename(changed_path).startswith("."):
            continue
        if changed_path not in output_paths:
            return True

    return False


# ---------------------------------------------------------------------------
# discover: 串起来，产出 Candidate
# ---------------------------------------------------------------------------

def _match_domain_for_record(record: dict[str, Any]) -> Optional[Any]:
    """懒 import 域注册表避免循环导入；返回命中的域或 None。"""
    from distiller import domains as _domains_lazy  # noqa：顶层 import 会形成环
    return _domains_lazy.match_domain(record)


def discover(events: list[EnrichedToolEvent]) -> list[Candidate]:
    """候选发现主入口：correlate → 噪声预过滤 → 形状过滤 → 产出 Candidate(raw)。

    高召回：形状中且非噪声就提名。价值判断全部下放到下游 Gate。

    阶段 1（domain adapter）：先走 domain registry 分配 purpose/profile，
    registry 无命中时退守旧硬编码（保持向后兼容，不丢候选）。
    """
    records = correlate(events)
    candidates: list[Candidate] = []

    for record in records:
        # 廉价噪声剔除先跑（更便宜）
        if is_noise(record):
            continue
        # 形状匹配：先走 domain registry，命中则用该域的 purpose/profile；
        # registry 无命中时退守旧硬编码（向后兼容，不丢候选）。
        domain = _match_domain_for_record(record)
        if domain is not None:
            fits = domain.shape_match(record)
        else:
            fits = shape_match(record)  # 旧硬编码 shape，测试直接调用此函数不受影响
        if not fits:
            continue

        input_artifacts: list[Artifact] = record["input_artifacts"]
        input_profile = (
            domain.guess_input_profile(input_artifacts)
            if domain is not None
            else _guess_input_profile(input_artifacts)
        )
        purpose_guess = (
            domain.purpose_guess(record)
            if domain is not None
            else "document-to-markdown"
        )

        # 把命中的域记进 context.source_ref，不改冻结 schema（演进评估 §三）。
        context: ExecContext = record["context"]
        if domain is not None:
            context.source_ref["domain"] = domain.name

        cand = Candidate(
            id=f"cand-{uuid.uuid4().hex[:8]}",
            purpose_guess=purpose_guess,
            entry_kind=record["entry_kind"],
            entry_ref=record["entry_ref"],
            argv=record["argv"],
            input_artifacts=input_artifacts,
            output_artifacts=record["output_artifacts"],
            input_profile=input_profile,
            stage="discovered",
            lifecycle="raw",
            pipeline_status="active",
            result_status=record["result_status"],
            exit_code=record["exit_code"],
            context=context,
            source_trace_ids=record["source_trace_ids"],
        )
        candidates.append(cand)

    return candidates
