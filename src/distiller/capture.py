"""M1 采集层：CC PostToolUse hook 的极轻采集逻辑。

职责（守则①）：
- 只写不算：不算 hash、不解析文件、不联网。
- 静默：所有函数绝不向 stdout/stderr 写任何内容。
- 极轻：append-only，失败也静默，绝不阻塞 CC。
"""
from __future__ import annotations

import json
import shlex
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from distiller.contracts import RawToolEvent

# 脱敏版本号——配合 RawToolEvent.redaction_version 字段
REDACTION_VERSION = "v1"

# 工具名 → event_type 映射（未知工具默认 tool_call）
_TOOL_EVENT_TYPE: dict[str, str] = {
    "Bash": "command_exec",
    "Write": "file_edit",
    "Edit": "file_edit",
    "MultiEdit": "file_edit",
    "Read": "tool_call",
    "Glob": "tool_call",
    "Grep": "tool_call",
    "Task": "tool_call",
    "WebFetch": "tool_call",
    "WebSearch": "tool_call",
}

# --flag=VALUE 风格的秘密 flag 前缀（含等号）
_SECRET_FLAG_PREFIXES: tuple[str, ...] = (
    "--token=",
    "--api-key=",
    "--api_key=",
    "--secret=",
    "--password=",
    "--passwd=",
    "--access-token=",
    "--access_token=",
    "--private-key=",
    "--private_key=",
)

# HTTP 头风格秘密前缀（大小写均支持）
_SECRET_HEADER_PREFIXES: tuple[str, ...] = (
    "Authorization:",
    "authorization:",
    "X-Api-Key:",
    "x-api-key:",
)


def _now_iso() -> str:
    """UTC 时间，ISO 8601 带 Z 后缀。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _event_type(tool_name: str) -> str:
    return _TOOL_EVENT_TYPE.get(tool_name, "tool_call")


# --------------------------------------------------------------------------- #
# 核心 API
# --------------------------------------------------------------------------- #


def build_raw_event(payload: dict, *, host_agent: str = "claude-code") -> RawToolEvent:
    """从 CC PostToolUse 给的 JSON payload 构造 RawToolEvent。

    极轻约定：
    - 不算 hash
    - 不解析文件内容
    - 不联网

    CC PostToolUse hook stdin 典型结构::

        {
            "session_id": "...",
            "tool_name": "Bash",
            "tool_input": {"command": "python conv.py a.pdf"},
            "tool_response": {"returnCode": 0, "output": "..."},
            "cwd": "/proj/A"
        }
    """
    tool_name: str = payload.get("tool_name", payload.get("name", ""))
    tool_input: dict = payload.get("tool_input", {})
    tool_response: dict = payload.get("tool_response", {})

    # 会话/项目/任务 ID
    session_id: str = payload.get("session_id", "")
    project_id: str = payload.get("project_id", payload.get("cwd", ""))
    task_id: str = payload.get("task_id", "")

    # 当前工作目录
    cwd: str = payload.get("cwd", tool_input.get("cwd", ""))

    # argv 构造：Bash 工具拆分命令；文件工具用路径
    raw_command: str = tool_input.get("command", tool_input.get("cmd", ""))
    if raw_command:
        try:
            argv: list[str] = shlex.split(raw_command)
        except ValueError:
            argv = raw_command.split()
    else:
        file_path = tool_input.get("path", tool_input.get("file_path", ""))
        argv = [tool_name] + ([file_path] if file_path else [])

    # 退出码（兼容 returnCode / exit_code / exitCode）
    exit_code: Optional[int] = None
    for key in ("returnCode", "exit_code", "exitCode", "return_code"):
        rc = tool_response.get(key)
        if rc is not None:
            try:
                exit_code = int(rc)
            except (TypeError, ValueError):
                exit_code = None
            break

    # source_ref
    source_ref: dict[str, str] = {}
    if payload.get("message_id"):
        source_ref["message_id"] = str(payload["message_id"])
    if payload.get("hook_event_name"):
        source_ref["hook"] = str(payload["hook_event_name"])

    # name：优先用完整命令字符串
    name: str = raw_command or tool_input.get("path", tool_name)

    return RawToolEvent(
        event_id=str(uuid.uuid4()),
        session_id=session_id,
        project_id=project_id,
        task_id=task_id,
        host_agent=host_agent,
        timestamp=_now_iso(),
        event_type=_event_type(tool_name),
        name=name,
        cwd=cwd,
        argv=argv,
        exit_code=exit_code,
        source_ref=source_ref,
        raw_payload_ref="",
        transcript_ref="",
        redaction_version=REDACTION_VERSION,
        redacted_fields=[],
    )


def fast_redact(
    argv: list[str],
    known_secrets: set[str],
) -> tuple[list[str], list[str]]:
    """采集即脱敏——只处理 argv 里常见形态。

    处理三类形态：
    1. ``--token=VALUE`` / ``--api-key=VALUE`` 等 flag 风格
    2. ``Authorization: Bearer VALUE`` 等 HTTP 头风格
    3. ``known_secrets`` 中的精确值（env 已知 secret）

    要快、不做复杂正则扫描。

    参数
    ----
    argv:           原始 argv 列表（将不被原地修改）
    known_secrets:  已知 secret 的精确字符串值集合

    返回
    ----
    (脱敏后的 argv, 被脱敏的字段名列表)
    """
    redacted_argv: list[str] = []
    field_names: list[str] = []

    for arg in argv:
        # ① 精确值匹配已知 secret
        if known_secrets and arg in known_secrets:
            redacted_argv.append("REDACTED")
            field_names.append("secret_value")
            continue

        # ② --flag=VALUE 风格
        matched = False
        for prefix in _SECRET_FLAG_PREFIXES:
            if arg.startswith(prefix) and len(arg) > len(prefix):
                # 提取 flag 名（去掉前导 -- 和尾部 =，- 换 _）
                flag_name = prefix.rstrip("=").lstrip("-").replace("-", "_")
                redacted_argv.append(f"{prefix}REDACTED")
                field_names.append(flag_name)
                matched = True
                break
        if matched:
            continue

        # ③ Header 风格：保留 "Header:" 前缀，脱敏值
        for hdr_prefix in _SECRET_HEADER_PREFIXES:
            if arg.startswith(hdr_prefix):
                colon_idx = arg.index(":")
                key_part = arg[: colon_idx + 1]   # 含冒号
                field_names.append(arg[:colon_idx])  # 不含冒号
                redacted_argv.append(f"{key_part} REDACTED")
                matched = True
                break
        if matched:
            continue

        redacted_argv.append(arg)

    return redacted_argv, field_names


def append_event(traces_dir, raw: RawToolEvent) -> None:
    """把事件 append 一行 JSON 到 traces/<session_id>/events.jsonl（append-only）。

    目录不存在时自动创建。失败静默（hook 守则①：绝不阻塞 CC）。

    存储路径规则::

        traces_dir/
          <session_id>/
            events.jsonl   ← 每行一个 RawToolEvent JSON
    """
    try:
        traces_dir = Path(traces_dir)
        session_dir = traces_dir / (raw.session_id or "unknown")
        session_dir.mkdir(parents=True, exist_ok=True)
        events_file = session_dir / "events.jsonl"
        line = json.dumps(asdict(raw), ensure_ascii=False) + "\n"
        with open(events_file, "a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:  # noqa: BLE001
        # 采集守则①：失败也静默退出，绝不向外抛出
        pass
