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
