"""最小安全门（阶段 3 同步落地，见演进评估 §二·问题 4）。

Safety Gate 在 generic file-transform 上线时必须有基本防护——脚本已经开始被
replay 和执行，不能等到 P6 才补安全。本模块做**静态扫描**（扫源码/argv/file_changes），
不对 replay 期实际副作用监控（后者留 P6）。

返回三级裁决：
  safe      → 可继续 gate
  review    → pipeline_status=deferred, deferred_reason=safety_review
  dangerous → rejected

只依赖标准库，不引入第三方包。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

SafetyVerdict = Literal["safe", "review", "dangerous"]

# ---------------------------------------------------------------------------
# 危险操作模式
# ---------------------------------------------------------------------------

# 删除/移动文件系统
_DELETE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p) for p in [
        r"\bos\.remove\b",
        r"\bos\.unlink\b",
        r"\bshutil\.rmtree\b",
        r"\bshutil\.move\b",
        r"\bos\.rmdir\b",
        r"\bpathlib.*\.unlink\b",
        r"\bPath\(.*\)\.unlink\b",
    ]
]

# 写出工作区（非 tmp 路径）— 静态检测有限，完整覆盖需 replay 期文件监控（P6）
_WRITE_OUTSIDE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p) for p in [
        r"""os\.makedirs\b""",
        r"""pathlib.*\.mkdir\b""",
    ]
]

# 执行 shell 拼接命令
_SHELL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p) for p in [
        r"\bos\.system\b",
        r"\bsubprocess\.(call|run|Popen)\b.*shell\s*=\s*True",
    ]
]

# 读取密钥/敏感文件
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p) for p in [
        r"""\.env""",
        r"""os\.environ""",
        r"""\.ssh/""",
        r"""credentials""",
        r"""api[_]?key""",
    ]
]

# git 仓库修改
_GIT_MODIFY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p) for p in [
        r"""git\s+(commit|push|tag|branch\s+-[dD])""",
        r"""subprocess.*git""",
    ]
]


def scan_source(code_text: str) -> set[str]:
    """扫脚本源码，返回命中的风险标签集合。"""
    found: set[str] = set()
    if not code_text:
        return found
    if any(p.search(code_text) for p in _DELETE_PATTERNS):
        found.add("file_deletion")
    if any(p.search(code_text) for p in _SHELL_PATTERNS):
        found.add("shell_exec")
    if any(p.search(code_text) for p in _SECRET_PATTERNS):
        found.add("secret_access")
    if any(p.search(code_text) for p in _GIT_MODIFY_PATTERNS):
        found.add("git_modification")
    if any(p.search(code_text) for p in _WRITE_OUTSIDE_PATTERNS):
        found.add("write_outside_workspace")
    return found


def assess(risks: set[str]) -> SafetyVerdict:
    """据风险标签集合判定总体安全等级。

    分级规则：
      dangerous: 文件删除 / shell 拼接命令 / git 修改——不可自动 promote
      review:    覆盖输入 / 密钥访问 / 写工作区外——需人审
      safe:      无命中风险标签，或仅有可逆副作用
    """
    dangerous = {"file_deletion", "shell_exec", "git_modification"}
    review = {"secret_access", "write_outside_workspace"}
    if risks & dangerous:
        return "dangerous"
    if risks & review:
        return "review"
    return "safe"


def scan_and_assess(code_text: str) -> tuple[SafetyVerdict, set[str]]:
    """一站式：扫源码 → 判等级。返回 (verdict, risks)。"""
    risks = scan_source(code_text)
    return assess(risks), risks


# ---------------------------------------------------------------------------
# Replay 期副作用审计（阶段 6：完整 Safety Gate）
# ---------------------------------------------------------------------------

def audit_file_changes(
    file_changes: list[dict],
    *,
    cwd: str = "",
    input_paths: set[str] | None = None,
) -> tuple[SafetyVerdict, set[str]]:
    """审计原始执行的 file_changes，检测路径逃逸、覆盖输入、写工作区外。

    静态扫描看不出脚本实际动了哪些文件——这里用原始 trace 的 file_changes
    做二次校验。不替换静态扫描，而是互补：静态挡危险调用，文件审计挡实际越界。

    Parameters
    ----------
    file_changes : list[dict]
        原始执行中记录的文件变更（capture 层产出）。
    cwd : str
        原执行的工作目录。
    input_paths : set[str] | None
        输入文件的绝对路径集合（用于检测覆盖输入）。

    Returns
    -------
    tuple[SafetyVerdict, set[str]]
    """
    risks: set[str] = set()
    if not file_changes:
        return "safe", risks
    cwd_path = (Path(cwd).resolve() if cwd else None)
    in_paths = {Path(p).resolve() for p in (input_paths or set())}
    import tempfile as _tempfile

    for change in file_changes:
        if not isinstance(change, dict):
            continue
        path_str = change.get("path", "")
        if not path_str:
            continue
        try:
            rp = Path(path_str).resolve()
        except (OSError, ValueError):
            risks.add("path_escape")
            continue

        # 路径逃逸：在 cwd 外且不在临时目录内
        if cwd_path and cwd_path not in rp.parents and rp != cwd_path:
            in_temp = False
            for td in (_tempfile.gettempdir(),):
                try:
                    if Path(td).resolve() in rp.parents or rp == Path(td).resolve():
                        in_temp = True
                        break
                except (OSError, ValueError):
                    pass
            if not in_temp:
                # 也检查 distiller-replay- 前缀（replay 沙箱在系统 temp 下）
                if "distiller-replay-" not in str(rp) and "pytest-" not in str(rp):
                    risks.add("write_outside_workspace")

        # 覆盖输入：change path 与某输入文件相同
        if in_paths and rp in in_paths:
            action = change.get("action", change.get("type", ""))
            if action in ("modify", "write", "delete", ""):
                risks.add("overwrite_input")

        # 文件删除
        action = change.get("action", change.get("type", ""))
        if action in ("delete", "remove"):
            risks.add("file_deletion")

    # overwrite_input 不是 assess 内置 review 项，在此直接判定
    if "overwrite_input" in risks:
        # 被改输入 → review（不自动 reject，但要求人审）
        base = assess(risks - {"overwrite_input"})
        return "review" if base == "safe" else base, risks

    return assess(risks), risks
