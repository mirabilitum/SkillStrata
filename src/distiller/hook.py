"""Hook —— 极轻 CC PostToolUse 事件写入器（阶段 7）。

设计要求（无感硬约束，see v0.4）：
  - <5ms 完成写入
  - append-only JSONL（一行一个事件）
  - 不 hash、不解析文件、不联网
  - 失败静默（不阻塞 CC）

用最朴素的 open/append，不引入任何第三方。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_event(
    traces_dir: Path | str,
    *,
    session_id: str,
    cwd: str,
    tool_name: str,
    command: str = "",
    exit_code: int | None = None,
    project_id: str = "",
    task_id: str = "",
    file_path: str = "",
    host_agent: str = "claude-code",
    input_paths: list[str] | None = None,
    output_paths: list[str] | None = None,
) -> str:
    """写一条 PostToolUse 事件到 traces/<session>/events.jsonl。

    极轻：只写文件、不读、不解析、不 hash。调用侧 1 行调用。

    Parameters
    ----------
    traces_dir : Path | str
        traces 目录根（如 .distiller-data/traces）。
    session_id : str
        CC 会话 ID。
    cwd : str
        命令执行时的工作目录。
    tool_name : str
        工具名（Bash / Write / Edit 等）。
    command : str
        执行的命令字符串。
    exit_code : int | None
        退出码。
    project_id : str
        项目 ID（可选，默认 ="")。
    task_id : str
        任务 ID（可选，默认 =""）。
    file_path : str
        如果工具是写文件类，传入文件路径。
    host_agent : str
        Agent 类型（默认 claude-code）。
    input_paths : list[str] | None
        输入文件的绝对路径列表（可选，帮助 daemon 识别 input artifact）。
    output_paths : list[str] | None
        输出文件的绝对路径列表（可选，帮助 daemon 识别 output artifact）。

    Returns
    -------
    str
        写入的 event_id。
    """
    event_id = str(uuid.uuid4())
    root = Path(traces_dir)
    session_dir = root / session_id
    try:
        session_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return event_id  # 静默失败

    payload = {
        "event_id": event_id,
        "session_id": session_id,
        "project_id": project_id or cwd,
        "task_id": task_id or "",
        "host_agent": host_agent,
        "timestamp": _now(),
        "tool_name": tool_name,
        "command": command,
        "cwd": cwd,
        "exit_code": exit_code,
        "file_path": file_path,
        "input_paths": input_paths or [],
        "output_paths": output_paths or [],
    }

    events_file = session_dir / "events.jsonl"
    try:
        with open(events_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        pass  # 静默

    return event_id
