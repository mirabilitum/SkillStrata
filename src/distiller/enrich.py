"""M1 daemon enrichment：RawToolEvent → EnrichedToolEvent。

只用标准库（hashlib / mimetypes / json / pathlib）。
不在 hook 里跑——这是 daemon 的工作，可以慢一点。
"""
from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path
from typing import Union

from distiller.contracts import Artifact, DeterminismSignals, EnrichedToolEvent, RawToolEvent

# 脱敏版本号（与 capture.py 对齐）
REDACTION_VERSION = "v1"

# --------------------------------------------------------------------------- #
# 系统二进制 / 重量级依赖检测（Q6：soffice/libreoffice/win32com → calls_system_binary）
# --------------------------------------------------------------------------- #

_SYSTEM_BINARIES: frozenset[str] = frozenset({
    "soffice",
    "libreoffice",
    "libreoffice7",
    "libreoffice6",
    "unoconv",
    "abiword",
    "docx2txt",
    "win32com",   # Python COM 桥——视为系统依赖
    "win32api",
    "wscript",
    "cscript",
    "msiexec",
})

# 网络访问关键词（在 argv/name token 中扫描）
_NETWORK_KEYWORDS: frozenset[str] = frozenset({
    "http://", "https://", "ftp://", "sftp://",
    "requests", "urllib", "httpx", "aiohttp",
    "socket", "wget", "curl", "fetch",
})

# 时间 / 随机源关键词
_TIME_RANDOM_KEYWORDS: frozenset[str] = frozenset({
    "random", "rand(", "uuid", "time.time",
    "datetime.now", "datetime.utcnow",
    "clock(", "sleep(", "perf_counter",
})

# 扩展名 → MIME 类型的补充映射（mimetypes 标准库并不总包含所有类型）
_MIME_OVERRIDE: dict[str, str] = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".doc": "application/msword",
    ".xls": "application/vnd.ms-excel",
    ".ppt": "application/vnd.ms-powerpoint",
    ".txt": "text/plain",
    ".json": "application/json",
    ".jsonl": "application/jsonl",
    ".py": "text/x-python",
    ".html": "text/html",
    ".htm": "text/html",
    ".csv": "text/csv",
    ".xml": "application/xml",
    ".yaml": "text/yaml",
    ".yml": "text/yaml",
    ".toml": "application/toml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".zip": "application/zip",
    ".tar": "application/x-tar",
    ".gz": "application/gzip",
}


# --------------------------------------------------------------------------- #
# 内部工具函数
# --------------------------------------------------------------------------- #


def _hash_file(path: Path) -> str:
    """blake2b hash of a file.  Returns 'blake2b:<hex>' or '' on error."""
    h = hashlib.blake2b()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65_536), b""):
                h.update(chunk)
        return f"blake2b:{h.hexdigest()}"
    except OSError:
        return ""


def _detect_media_type(path: Union[Path, str]) -> str:
    """Guess media type by extension.

    扩展名优先使用 ``_MIME_OVERRIDE`` 表（覆盖系统注册表中可能缺失的类型），
    找不到时回退到 ``mimetypes.guess_type``，最后兜底 ``application/octet-stream``。
    """
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in _MIME_OVERRIDE:
        return _MIME_OVERRIDE[suffix]
    mt, _ = mimetypes.guess_type(str(path))
    return mt or "application/octet-stream"


def _find_system_binaries(tokens: list[str]) -> list[str]:
    """在 token 列表中查找已知系统二进制名称（子串匹配）。"""
    found: list[str] = []
    for token in tokens:
        lower = token.lower()
        for binary in _SYSTEM_BINARIES:
            if binary in lower and binary not in found:
                found.append(binary)
    return found


def _has_any_keyword(tokens: list[str], keywords: frozenset[str]) -> bool:
    """检查任意 token 是否包含关键词集中的任意一个（子串匹配）。"""
    for token in tokens:
        lower = token.lower()
        for kw in keywords:
            if kw in lower:
                return True
    return False


# --------------------------------------------------------------------------- #
# 核心 API
# --------------------------------------------------------------------------- #


def enrich(
    raw: RawToolEvent,
    *,
    input_paths: list[Union[Path, str]],
    output_paths: list[Union[Path, str]],
    artifacts_dir: Union[Path, str],
) -> EnrichedToolEvent:
    """daemon enrichment：把 RawToolEvent 补全成 EnrichedToolEvent。

    补充内容
    --------
    - ``input_artifacts`` / ``output_artifacts``：每个文件的 blake2b hash + media_type
    - ``determinism_signals``：
        - ``calls_system_binary``：argv/name 中出现 soffice/libreoffice/win32com 等
        - ``system_binaries``：检出的系统二进制名称列表
        - ``network_access``：argv/name 含网络访问关键词
        - ``uses_time_or_random``：argv/name 含随机/时间关键词

    只用标准库（hashlib / mimetypes / json / pathlib）。
    """
    _artifacts_dir = Path(artifacts_dir)  # noqa: F841（预留：快照引用）

    # ── 输入产物 ──────────────────────────────────────────────────────────── #
    input_artifacts: list[Artifact] = []
    for p in input_paths:
        p = Path(p)
        input_artifacts.append(
            Artifact(
                path=str(p),
                media_type=_detect_media_type(p),
                hash=_hash_file(p),
            )
        )

    # ── 输出产物 ──────────────────────────────────────────────────────────── #
    output_artifacts: list[Artifact] = []
    for p in output_paths:
        p = Path(p)
        output_artifacts.append(
            Artifact(
                path=str(p),
                media_type=_detect_media_type(p),
                hash=_hash_file(p),
            )
        )

    # ── 确定性信号 ────────────────────────────────────────────────────────── #
    # 扫描 argv 和 name（name 可能是完整命令字符串，含 argv 中没有的上下文）
    all_tokens: list[str] = list(raw.argv) + ([raw.name] if raw.name else [])

    sys_bins = _find_system_binaries(all_tokens)
    network = _has_any_keyword(all_tokens, _NETWORK_KEYWORDS)
    time_rand = _has_any_keyword(all_tokens, _TIME_RANDOM_KEYWORDS)

    det = DeterminismSignals(
        network_access=network,
        external_model_call=False,          # M1 不做 LLM 调用检测，留给 M2 tree-sitter
        uses_time_or_random=time_rand,
        calls_system_binary=bool(sys_bins),
        system_binaries=sys_bins,
        replay_byte_identical=None,         # 实测重放回填（None=未测）
    )

    return EnrichedToolEvent(
        raw=raw,
        input_artifacts=input_artifacts,
        output_artifacts=output_artifacts,
        file_changes=[],
        stdout_ref="",
        stderr_ref="",
        env_fingerprint={},
        determinism_signals=det,
        transcript_ref=raw.transcript_ref,
        redaction_version=raw.redaction_version or REDACTION_VERSION,
        redacted_fields=list(raw.redacted_fields),
    )
