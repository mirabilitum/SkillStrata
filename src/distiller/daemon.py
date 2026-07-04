"""Daemon —— 异步读取 traces、enrich、跑 pipeline（阶段 7）。

设计要求（无感硬约束）：
  - 独立进程，不抢前台资源
  - 空闲触发（有新 trace 才跑）
  - 断点续跑（处理过的 trace 不重复）
  - 批次提交（积攒后再批量入 pipeline，减少锁竞争）
  - 崩溃不影响 CC（无共享状态）

当前实现：同步批处理模式（真实 daemon 常驻进程留团队阶段）。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import capture, config, db, enrich, pipeline
from .contracts import EnrichedToolEvent


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Checkpoint:
    """断点：记录哪些 session 的哪些 event 已处理过。"""

    def __init__(self, path: Path | str):
        self._path = Path(path)
        self._processed: dict[str, set[str]] = {}  # session_id → {event_id}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            for sid, eids in (data.get("sessions") or {}).items():
                self._processed[sid] = set(eids)
        except (json.JSONDecodeError, OSError):
            pass

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(
                {"sessions": {k: sorted(v) for k, v in self._processed.items()}},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def is_new(self, session_id: str, event_id: str) -> bool:
        return event_id not in self._processed.get(session_id, set())

    def mark(self, session_id: str, event_ids: list[str]) -> None:
        s = self._processed.setdefault(session_id, set())
        s.update(event_ids)

    @property
    def total_processed(self) -> int:
        return sum(len(v) for v in self._processed.values())


def _to_cc_payload(raw: dict) -> dict:
    """把 hook 的扁平格式转成 CC PostToolUse payload（build_raw_event 期望的格式）。

    hook 写：
      {command, tool_name, exit_code, cwd, session_id, ...}
    CC format：
      {tool_name, tool_input:{command}, tool_response:{returnCode}, cwd, session_id, ...}

    注意：build_raw_event 用 shlex.split(command) 构造 argv，在 Windows 上会吃掉
    路径里的反斜杠。作为 bypass：如果 command 里含绝对路径，改用 tool_input.path 模式
    （走 _extract_entry 的 file_path 分支，绕过 shlex）。
    """
    # 已经是 CC 格式 → 直接返回
    if "tool_input" in raw or "tool_response" in raw:
        return raw
    command = raw.get("command", "")
    # 检测命令中含 Windows 绝对路径 → 用 path-based payload 绕过 shlex
    import platform
    is_windows = platform.system() == "Windows"
    if is_windows:
        import re
        # 找第一个绝对路径（可能是脚本）
        matches = re.findall(r'[A-Za-z]:[\\/][^\s"\'<>]+\.py', command)
        first_abs_path = matches[0] if matches else ""
    else:
        first_abs_path = ""
    return {
        "tool_name": raw.get("tool_name", "Bash"),
        "tool_input": {
            "command": command,
            "path": first_abs_path,
        },
        "tool_response": {"returnCode": raw.get("exit_code", 0)},
        "cwd": raw.get("cwd", ""),
        "session_id": raw.get("session_id", ""),
        "project_id": raw.get("project_id", raw.get("cwd", "")),
        "task_id": raw.get("task_id", ""),
        "host_agent": raw.get("host_agent", "claude-code"),
        "hook_event_name": "PostToolUse",
        "message_id": raw.get("event_id", ""),
    }


def ingest_traces(
    data_dir: Path | str,
    *,
    batch_size: int = 16,
    cfg: Optional[config.Config] = None,
) -> dict:
    """读取 traces 目录、enrich、跑 pipeline，返回处理统计。

    断点续跑：只处理 checkpoint 之后的新事件。
    调用方可以 cron 或 event loop 轮询此函数。

    Parameters
    ----------
    data_dir : Path | str
        数据目录根（含 traces/、meta.sqlite、checkpoint.json）。
    batch_size : int
        单次最多处理的事件数。
    cfg : Config | None
        配置（默认从 data_dir 加载）。

    Returns
    -------
    dict
        统计：{"new_events": int, "promoted": int, "rejected": int, "deferred": int,
               "errors": int, "total_processed_before": int}
    """
    root = Path(data_dir)
    traces_dir = root / "traces"
    db_path = root / "meta.sqlite"
    checkpoint = Checkpoint(root / "checkpoint.json")

    if cfg is None:
        cfg = config.load(overrides={"data_dir": str(root)})

    # 收集新事件
    new_events: list[tuple[str, str, dict]] = []  # (session_id, event_id, raw_json)

    if traces_dir.is_dir():
        for session_dir in sorted(traces_dir.iterdir()):
            if not session_dir.is_dir():
                continue
            sid = session_dir.name
            events_file = session_dir / "events.jsonl"
            if not events_file.exists():
                continue
            try:
                for line in events_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    eid = raw.get("event_id", "")
                    if not eid:
                        continue
                    if checkpoint.is_new(sid, eid):
                        if len(new_events) >= batch_size:
                            break
                        new_events.append((sid, eid, raw))
            except OSError:
                continue
            if len(new_events) >= batch_size:
                break

    if not new_events:
        return {
            "new_events": 0, "promoted": 0, "rejected": 0,
            "deferred": 0, "errors": 0,
            "total_processed_before": checkpoint.total_processed,
        }

    # enrich → pipeline
    enriched: list[EnrichedToolEvent] = []
    processed: dict[str, list[str]] = {}  # session_id → [event_id]
    errors = 0

    for sid, eid, raw in new_events:
        try:
            # hook 写的扁平格式 → CC PostToolUse payload（build_raw_event 期望的格式）
            payload = _to_cc_payload(raw)
            ev = capture.build_raw_event(payload, host_agent=payload.get("host_agent", "claude-code"))
            # input/output path：优先读 hook payload 显式传递的路径；
            # 若无，从 command 字符串 + 文件后缀反向推断（fallback）
            input_paths = [Path(p) for p in raw.get("input_paths", []) if p]
            output_paths = [Path(p) for p in raw.get("output_paths", []) if p]
            if not input_paths:
                cwd = Path(raw.get("cwd", "."))
                cmd = raw.get("command", "")
                if cmd:
                    parts = cmd.split()
                    for p in parts[1:]:
                        candidate = cwd / p
                        if candidate.suffix.lower() in {
                            ".html", ".htm", ".csv", ".json", ".txt", ".md",
                            ".pdf", ".docx", ".xlsx",
                        }:
                            input_paths.append(candidate)

            enriched.append(
                enrich.enrich(ev, input_paths=input_paths or [Path(".")],
                              output_paths=output_paths or [Path(".")],
                              artifacts_dir=data_dir / "artifacts")
            )
            processed.setdefault(sid, []).append(eid)
        except Exception:
            errors += 1

    if not enriched:
        return {
            "new_events": len(new_events), "promoted": 0, "rejected": 0,
            "deferred": 0, "errors": errors,
            "total_processed_before": checkpoint.total_processed,
        }

    # 跑 pipeline
    conn = db.connect(db_path)
    try:
        db.apply_schema(conn)
        result = pipeline.run_pipeline(conn, enriched, data_dir=root)
    finally:
        conn.close()

    # 更新 checkpoint
    for sid, eids in processed.items():
        checkpoint.mark(sid, eids)
    checkpoint.save()

    return {
        "new_events": len(new_events),
        "promoted": len(result.promoted_skills),
        "rejected": len(result.by_status("rejected")),
        "deferred": len(result.by_status("deferred")),
        "errors": errors,
        "total_processed_before": checkpoint.total_processed,
    }
