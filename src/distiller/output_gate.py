"""M3 · 属性 Output Gate — 重放输出的属性验证与 behavior_signature 生成。

对照：属性OutputGate与behavior_signature.md / 技术栈与运行时-canonical §3.2。
设计要点（见属性OutputGate文档 §0 + §5）：
  - A(门禁) 与 B(指纹) 是同一次解析输出的两个产物，不是两套系统。
  - 守恒 oracle：用输入自己当真值——不依赖标准答案。
  - 输入侧测量必须用独立抽取器（防循环）——但 MVP 中不引入额外依赖，
    只做文本层面的统计（非 NLP），留接口供将来接入 pdfminer/markitdown 等。
  - 门禁按 input_profile 分支化（§5.2）。
  - 只用标准库（re），不用 mistune。

使用示例：
    from distiller.contracts import Candidate
    gate_pass, bs = output_gate(candidate, output_md, input_text, assets_dir)
    # gate_pass -> True / False
    # bs       -> BehaviorSignature(...)
"""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path

from distiller.contracts import BehaviorSignature, Candidate

# ---------------------------------------------------------------------------
# A · 内在合法性（Job A 硬门禁）
# ---------------------------------------------------------------------------

# 松散 markdown 结构模式：标题、表格、图片、列表、引用、代码块、段落文本
_MD_HEADING_RE = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)
_MD_TABLE_RE = re.compile(r"^\|.+\|\s*$", re.MULTILINE)
_MD_IMAGE_RE = re.compile(r"!\[.*?\]\(.*?\)")
_MD_LIST_RE = re.compile(r"^[\s]*[-*+]\s+\S", re.MULTILINE)
_MD_BLOCKQUOTE_RE = re.compile(r"^>\s+\S", re.MULTILINE)
_MD_FENCED_CODE = re.compile(r"^```", re.MULTILINE)

# 悬空图片引用（![] 后缺少 ()）
_HANGING_IMG_REF_RE = re.compile(r"!\[.*?\]\s*[^(\[]")

# 不可接受的控制字符（保留 \t \n \r；其余 C0 控制符 + DEL 视为破损输出）
_BAD_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def check_integrity(output_md: str) -> bool:
    """检查 markdown 基本合法性（复审 P2-a：普通段落是合法 markdown）。

    硬门禁只判"输出是不是坏的"，不判"结构化程度"（后者是 behavior 评分，不该 fail）：
    - 非空（空 / 纯空白 → False）
    - 无悬空图片引用（`![]` 后缺少 `()`）
    - 无不可接受的控制字符（保留 \\t \\n \\r）

    结构性标记（标题/表格/列表…）是否存在 → 反映在 BehaviorSignature 里，
    由复用价值与质量门控决定优劣，而不是在此处硬性拒绝合法正文。
    """
    if not output_md or not output_md.strip():
        return False

    # 悬空图片引用 = 破损输出
    if _HANGING_IMG_REF_RE.search(output_md):
        return False

    # 不可接受的控制字符 = 破损输出
    if _BAD_CONTROL_RE.search(output_md):
        return False

    return True


# ---------------------------------------------------------------------------
# A 辅助 · 文本覆盖比（输入↔输出守恒）
# ---------------------------------------------------------------------------

# 移除去 markdown 标记：代码块、行内代码、图片、链接、HTML 标签、markdown 修饰符
_MD_STRIP_RE = re.compile(
    r"```.*?```|"        # 多行代码块
    r"`[^`]*`|"          # 行内代码
    r"!\[.*?\]\(.*?\)|"  # 图片
    r"\[.*?\]\(.*?\)|"   # 链接
    r"<[^>]+>|"          # HTML 标签
    r"[#*_~>`|>-]",      # markdown 修饰符
    re.DOTALL,
)


def _strip_markdown(md: str) -> str:
    """去除 markdown 标记，保留纯文本。"""
    return _MD_STRIP_RE.sub("", md)


def measure_coverage(input_text: str, output_md: str) -> float:
    """计算输出的文本覆盖输入的比例（非空白字符比）。

    这是一次非常保守的估计：
    - 去除 markdown 标记后，比较输出的非空白字符数与输入的非空白字符数。
    - 不引入 NLP 或语义理解。
    - 返回值范围 [0.0, 1.0]，1.0 表示输出字符 ≥ 输入字符。

    Parameters
    ----------
    input_text : str
        输入的原始文本（如从 pdf 抽取的文本）。
    output_md : str
        候选产生的 markdown 输出。

    Returns
    -------
    float
        最小覆盖比：min(1.0, 输出非空白字符数 / 输入非空白字符数)
    """
    input_chars = len(re.sub(r"\s+", "", input_text))
    if input_chars == 0:
        return 0.0

    plain_output = _strip_markdown(output_md)
    output_chars = len(re.sub(r"\s+", "", plain_output))

    ratio = output_chars / input_chars
    return min(1.0, ratio)


# ---------------------------------------------------------------------------
# A 辅助 · 图片引用计数
# ---------------------------------------------------------------------------


def count_image_refs(md: str) -> int:
    """统计 markdown 中 `![` 图片引用数量。"""
    return len(_MD_IMAGE_RE.findall(md))


# ---------------------------------------------------------------------------
# A 辅助 · 表格模式检测
# ---------------------------------------------------------------------------

_KV_LINE_RE = re.compile(r"^\s*\S+[：:]\s*\S", re.MULTILINE)
_PIPE_TABLE_ROW_RE = re.compile(r"^\|.+\|\s*$", re.MULTILINE)
_ROW_LIST_RE = re.compile(
    r"^\s*[-*+]\s+(?:\S+[：:]\s+)?\S", re.MULTILINE
)


def detect_table_mode(md: str) -> str:
    """检测 markdown 输出的表格渲染模式。

    模式优先级：
    1. pipe_table — 管道表（`| header | header |` 形式）
    2. kv_list — 键值对列表（`键：值` 行，无表格边框）
    3. row_list — 列表式行（每行以 `-` / `*` 开头，包含键值对）
    4. unknown — 无法识别

    返回字符串：pipe_table | kv_list | row_list | unknown
    """
    pipe_rows = _PIPE_TABLE_ROW_RE.findall(md)
    kv_lines = _KV_LINE_RE.findall(md)
    row_list_lines = _ROW_LIST_RE.findall(md)

    # 管道表至少需要 2 行（表头 + 分隔行 + 数据行 → 至少 2 行管道）
    if len(pipe_rows) >= 2:
        return "pipe_table"

    # 键值对列表至少 2 行
    if len(kv_lines) >= 2:
        return "kv_list"

    # 列表式行至少 2 行
    if len(row_list_lines) >= 2:
        return "row_list"

    return "unknown"


# ---------------------------------------------------------------------------
# B · 指纹字段计算
# ---------------------------------------------------------------------------


def _calc_content_coverage_grade(ratio: float) -> str:
    """文本覆盖比分桶：A (>=0.95) / B (>=0.80) / C (>=0.50) / D (<0.50)。"""
    if ratio >= 0.95:
        return "A"
    if ratio >= 0.80:
        return "B"
    if ratio >= 0.50:
        return "C"
    return "D"


def _calc_heading_preservation(output_md: str) -> float:
    """粗略估计标题保留率：以输出中标题总数 / 100 字符数为归一化比例。

    MVP 简化：输入侧标题数难以在没有 PDF 解析器的情况下获取，
    因此使用输出标题密度作为代理指标——越密集表示标题结构越丰富。
    返回 [0.0, 1.0]，密度 >= 0.05 标题/100字符记 1.0。

    正式版应使用独立抽取器分别统计输入/输出标题数后计算真实保留率。
    """
    headings = _MD_HEADING_RE.findall(output_md)
    if not headings:
        return 0.0
    char_count = len(output_md)
    if char_count == 0:
        return 0.0
    density = len(headings) / (char_count / 100)
    return min(1.0, density / 0.05)


def _detect_key_value_rendering(md: str) -> bool:
    """检测输出是否包含键值对渲染模式（连续多行 `键：值` 格式）。"""
    matches = _KV_LINE_RE.findall(md)
    # 至少 2 行键值对才认为有特判
    return len(matches) >= 2


# ---------------------------------------------------------------------------
# 主门禁函数
# ---------------------------------------------------------------------------

# 硬门禁分支化阈值：按 input_profile 选主力门禁
_COVERAGE_THRESHOLD = 0.15  # 兜底最低文本覆盖（未知 profile；宁可低，不漏杀）

# 复审 P2-b：文本型输入按 profile 分层，纯文本格式抬高覆盖底线，
# 防"只保留摘要/开头片段"的转换器蒙混过关。图文混合格式放低（正文外还有图/表）。
_COVERAGE_THRESHOLD_BY_PROFILE: dict[str, float] = {
    "pdf_text": 0.80,
    "office_docx": 0.80,
    "html": 0.60,
    "pptx_mixed": 0.30,   # 幻灯正文稀疏，另有图片/标题约束在 behavior 里
}


def _coverage_floor(profile: str) -> float:
    return _COVERAGE_THRESHOLD_BY_PROFILE.get(profile, _COVERAGE_THRESHOLD)


def output_gate(
    candidate: Candidate,
    output_md: str,
    input_text: str,
    assets_dir: str | Path = "",
) -> tuple[bool, BehaviorSignature]:
    """属性 Output Gate：同一次解析，产出 pass/fail + BehaviorSignature。

    Parameters
    ----------
    candidate : Candidate
        当前候选，其 input_profile 决定门禁分支化策略。
    output_md : str
        候选重放输出的 markdown 文本。
    input_text : str
        输入的原始文本（用独立抽取器测量，防循环）。
    assets_dir : str | Path
        资产目录路径（用于检查 assets_emitted），可为空。

    Returns
    -------
    tuple[bool, BehaviorSignature]
        (pass/fail, BehaviorSignature 全部字段)

    Notes
    -----
    硬门禁规则（§5.2）：
    - pdf_text：文本覆盖比 ≥ _COVERAGE_THRESHOLD（最低底线）
    - pdf_scanned：至少 1 个图片引用
    - xlsx_table：输出有表格结构标记（pipe_table / kv_list / row_list）
    - pptx_mixed、office_docx 等：文本覆盖底线
    - 默认值：文本覆盖底线
    所有 profile 都需通过 markdown 内在合法性检查。
    """
    # --- Job B：指纹（先算，哪怕门禁 fail 也产）---
    integrity = check_integrity(output_md)
    img_count = count_image_refs(output_md)
    coverage = measure_coverage(input_text, output_md)
    table_mode = detect_table_mode(output_md)
    kv_rendering = _detect_key_value_rendering(output_md)
    heading_preservation = _calc_heading_preservation(output_md)
    grade = _calc_content_coverage_grade(coverage)

    # assets_emitted 检测
    assets_emitted = False
    if assets_dir:
        ad = Path(assets_dir)
        if ad.is_dir():
            # 目录存在且有非空文件才认为有资产落盘
            non_empty = [
                f
                for f in ad.iterdir()
                if f.is_file() and f.stat().st_size > 0
            ]
            assets_emitted = bool(non_empty)

    # image_ref_coverage：输出图片引用数 / 至少 1 张就满（MVP 简化）
    image_ref_coverage = 1.0 if img_count > 0 else 0.0

    bs = BehaviorSignature(
        markdown_valid=integrity,
        assets_emitted=assets_emitted,
        image_ref_coverage=image_ref_coverage,
        heading_preservation=heading_preservation,
        content_coverage_grade=grade,
        table_render_mode=table_mode,
        key_value_rendering=kv_rendering,
        is_thin_wrapper=False,  # MVP 暂不实现基线对比
    )

    # --- Job A：门禁（按 input_profile 分支化）---
    # 硬门禁 1：所有 profile 都必须通过 markdown 合法性检查
    if not integrity:
        return False, bs

    profile = candidate.input_profile or ""

    if profile == "pdf_scanned":
        # 扫描件：至少产出图片引用
        gate_pass = img_count >= 1
    elif profile == "xlsx_table":
        # 表格：输出有表格结构标记
        gate_pass = table_mode in ("pipe_table", "kv_list", "row_list")
    else:
        # 文本型（pdf_text / office_docx / html / pptx_mixed / 未知）：分层覆盖底线
        gate_pass = coverage >= _coverage_floor(profile)

    return gate_pass, bs
