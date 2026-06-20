"""M2 · Gate0 确定性探测

对照：v0.4 §5.2 / 技术栈与运行时-canonical §3.2 / 落地实现规划 T2.3。

职责：
  - probe_determinism：静态信号扫描（只用标准库 + re），粗判网络/外部模型/时间随机源/系统二进制。
  - apply_gate0：据信号更新 Candidate 的 determinism / pipeline_status / deferred_reason /
      requires_host_capability。系统二进制 → 显式搁置（deferred + dependency），不静默丢。

只依赖标准库，不引入任何第三方包。
"""
from __future__ import annotations

import copy
import re

from distiller.contracts import Candidate, DeterminismSignals

# ---------------------------------------------------------------------------
# 静态信号：正则模式表
# ---------------------------------------------------------------------------

# 网络访问
_NETWORK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p) for p in [
        r"\burllib\b",
        r"\brequests\b",
        r"\bhttpx\b",
        r"\baiohttp\b",
        r"\bhttp\.client\b",
        r"\bhttplib2\b",
        r"\bsocket\b",
        r"\bsmtplib\b",
        r"\bftplib\b",
        r"\bparamiko\b",
    ]
]

# 外部模型调用
_EXTERNAL_MODEL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p) for p in [
        r"\bopenai\b",
        r"\banthropic\b",
        r"\bgemini\b",
        r"\btransformers\b",
        r"\btorch\.hub\b",
        r"\bhuggingface_hub\b",
        r"\bcohere\b",
        r"\bmistralai\b",
        r"\bllama_cpp\b",
        r"\bvertexai\b",
    ]
]

# 时间/随机源
_TIME_RANDOM_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p) for p in [
        r"\btime\.time\b",
        r"\btime\.monotonic\b",
        r"\bdatetime\.now\b",
        r"\bdatetime\.utcnow\b",
        r"\bdatetime\.today\b",
        r"\brandom\.",
        r"\bos\.urandom\b",
        r"\bsecrets\.",
        # uuid4 用时间/随机；uuid5 是确定性的，不标
        r"\buuid\.uuid4\b",
        r"\buuid4\(\)",
    ]
]

# 系统二进制：(pattern, capability_name)
# pattern 匹配任何代码中出现的调用点（subprocess / os.system / 字面量字符串）
_SYSTEM_BINARY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bsoffice\b"),         "libreoffice"),
    (re.compile(r"\blibreoffice\b"),     "libreoffice"),
    (re.compile(r"\bwin32com\b"),        "win32com"),
    (re.compile(r"\bwkhtmltopdf\b"),     "wkhtmltopdf"),
    (re.compile(r"\btesseract\b"),       "tesseract"),
    (re.compile(r"\bghostscript\b"),     "ghostscript"),
    # gs 太短易误判，加上 subprocess 前缀限制；保留简写供明显 import 场景
    (re.compile(r"""["'`]gs\b"""),       "ghostscript"),
    (re.compile(r"\bpoppler\b"),         "poppler"),
    (re.compile(r"\bpandoc\b"),          "pandoc"),
    (re.compile(r"\bunoconv\b"),         "unoconv"),
]


# ---------------------------------------------------------------------------
# probe_determinism
# ---------------------------------------------------------------------------

def probe_determinism(candidate: Candidate, code_text: str = "") -> DeterminismSignals:  # noqa: ARG001
    """静态信号扫描：从 code_text 正则匹配确定性信号。

    candidate 参数预留（供后续从 entry_ref/code_snapshot_ref 加载代码），
    MVP 阶段直接传 code_text 字符串。

    只做"粗筛"——v0.4 §10：静态分析不宣称完全确定性，实测重放是准则。
    replay_byte_identical 由 M3 Replay Gate 回填，这里保持 None。
    """
    signals = DeterminismSignals()

    if not code_text:
        return signals

    # 网络访问
    if any(p.search(code_text) for p in _NETWORK_PATTERNS):
        signals.network_access = True

    # 外部模型调用
    if any(p.search(code_text) for p in _EXTERNAL_MODEL_PATTERNS):
        signals.external_model_call = True

    # 时间/随机源
    if any(p.search(code_text) for p in _TIME_RANDOM_PATTERNS):
        signals.uses_time_or_random = True

    # 系统二进制
    found: list[str] = []
    for pattern, cap_name in _SYSTEM_BINARY_PATTERNS:
        if pattern.search(code_text) and cap_name not in found:
            found.append(cap_name)

    if found:
        signals.calls_system_binary = True
        signals.system_binaries = found

    return signals


# ---------------------------------------------------------------------------
# apply_gate0
# ---------------------------------------------------------------------------

def apply_gate0(candidate: Candidate, signals: DeterminismSignals) -> Candidate:
    """据 DeterminismSignals 更新 Candidate 的确定性字段与流水线状态。

    规则（按优先级）：

    1. 命中系统二进制（calls_system_binary）
       → pipeline_status="deferred", deferred_reason="dependency",
         requires_host_capability 填入检测到的二进制名称。
         （Q6 显式搁置，不静默失败）

    2. 非确定性（network_access | external_model_call | uses_time_or_random）
       且 同时有系统二进制 → determinism="mixed"，仍执行规则1（dependency 优先）
       仅非确定性无系统二进制 → determinism="nondeterministic"，
         pipeline_status="deferred", deferred_reason="nondeterministic"

    3. 混合（mixed）且仅来自非确定性（无系统二进制）
       → determinism="mixed"，deferred_reason="nondeterministic"，标记待拆

    4. 纯确定性 → determinism="deterministic"，pipeline_status 不变（active）

    返回新 Candidate 副本，不修改传入对象。
    """
    c: Candidate = copy.deepcopy(candidate)

    nondeterministic = (
        signals.network_access
        or signals.external_model_call
        or signals.uses_time_or_random
    )
    has_sys_binary = signals.calls_system_binary

    # --- 确定 determinism 字段 ---
    if nondeterministic and has_sys_binary:
        c.determinism = "mixed"
    elif nondeterministic:
        c.determinism = "nondeterministic"
    else:
        # 系统二进制本身不影响确定性等级（程序行为确定，只是依赖外部环境）
        c.determinism = "deterministic"

    # --- 系统二进制：显式搁置（Q6 / deferred_dependency）---
    if has_sys_binary:
        c.pipeline_status = "deferred"
        c.deferred_reason = "dependency"
        # 合并已有能力列表，避免覆盖
        existing = set(c.requires_host_capability)
        for cap in signals.system_binaries:
            existing.add(cap)
        c.requires_host_capability = sorted(existing)
        return c

    # --- 非确定性（无系统二进制）：搁置 / 标记待拆 ---
    if c.determinism == "nondeterministic":
        c.pipeline_status = "deferred"
        c.deferred_reason = "nondeterministic"
    elif c.determinism == "mixed":
        # mixed 且无系统二进制（理论上不会到这里，但留保险）
        c.pipeline_status = "deferred"
        c.deferred_reason = "nondeterministic"

    return c
