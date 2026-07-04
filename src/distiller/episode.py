"""Episode Builder（阶段 5）—— 从长链条任务中识别最终可复用能力。

现有 `discovery.correlate` 已按 (task_id,cwd) 分组、关联写事件、拼 IO。
Episode Builder 在其上增强（演进评估 §二·问题 5：定位为 correlate 的时序增强，
不是另起炉灶）：

  - 区分最终成功命令 vs 中间失败尝试 vs 探索/检查命令
  - 失败尝试 → 记 lineage（不提名）
  - 探索命令 → 既不入库也不提名
  - 跨输入复用识别 → 同脚本跑第二个输入 = 置信度提升信号

只依赖标准库 + contracts，不引入第三方包。
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .contracts import EnrichedToolEvent


@dataclass
class Episode:
    """一个任务片段（通常是一次任务 id + cwd 下的一组操作）。

    final_exec: 最终的、exit_code=0 的 command_exec（如果没有成功命令 = None）。
    related_writes: 与 final_exec 同脚本名的生成/写入事件。
    failed_attempts: exit_code≠0 的命令（供 lineage 证据）。
    noise_events: 探索/检查类命令（暂按无 I/O 或无入口判）。
    """
    id: str              # task_id
    cwd: str
    events: list[EnrichedToolEvent] = field(default_factory=list)
    final_exec: EnrichedToolEvent | None = None
    related_writes: list[EnrichedToolEvent] = field(default_factory=list)
    failed_attempts: list[EnrichedToolEvent] = field(default_factory=list)
    noise_events: list[EnrichedToolEvent] = field(default_factory=list)

    @property
    def has_success(self) -> bool:
        return self.final_exec is not None

    @property
    def event_count(self) -> int:
        return len(self.events)

    @property
    def attempt_count(self) -> int:
        return len(self.failed_attempts) + (1 if self.final_exec else 0)


def build_episodes(events: list[EnrichedToolEvent]) -> list[Episode]:
    """把一组长链条事件分组为 episode。

    聚合键 = (task_id, cwd)。组内按时间排序，区分：
      - final_exec：最后一个 exit_code==0 的 command_exec
      - failed_attempts：exit_code≠0 的命令
      - noise：无入口（无可辨 entry_ref）或无文件 I/O 的命令（探索/查看）
      - related_writes：与 final_exec 同脚本名的生成/写入事件
    """
    if not events:
        return []

    groups: dict[tuple[str, str], list[EnrichedToolEvent]] = defaultdict(list)
    for ev in events:
        key = (ev.raw.task_id, ev.raw.cwd)
        groups[key].append(ev)

    episodes: list[Episode] = []

    for (task_id, cwd), group in groups.items():
        group_sorted = sorted(group, key=lambda e: e.raw.timestamp)

        exec_events = [e for e in group_sorted if e.raw.event_type == "command_exec"]
        write_events = [e for e in group_sorted
                        if e.raw.event_type in ("generated_code", "file_edit")]

        # 分离失败/成功/噪声 exec 事件
        failures: list[EnrichedToolEvent] = []
        successes: list[EnrichedToolEvent] = []
        noise: list[EnrichedToolEvent] = []

        for ee in exec_events:
            entry_ref = _extract_entry_ref(ee)
            if not entry_ref:
                noise.append(ee)
            elif ee.raw.exit_code != 0:
                failures.append(ee)
            else:
                successes.append(ee)

        # 探索命令：无文件 I/O 的命令（查看/确认，不算噪声但也不提名）
        explore = [
            e for e in group_sorted
            if e.raw.event_type not in ("command_exec", "generated_code", "file_edit")
        ]

        # final_exec = 最后一个成功的命令
        final = successes[-1] if successes else None

        # related_writes：与 final_exec 同脚本名的写入事件
        related: list[EnrichedToolEvent] = []
        if final:
            entry_ref = _extract_entry_ref(final)
            related = [
                w for w in write_events
                if entry_ref and (
                    entry_ref in w.raw.name
                    or any(entry_ref in a for a in w.raw.argv)
                )
            ]

        ep = Episode(
            id=task_id,
            cwd=cwd,
            events=group_sorted,
            final_exec=final,
            related_writes=related,
            failed_attempts=failures,
            noise_events=noise + explore,
        )
        episodes.append(ep)

    return episodes


def _extract_entry_ref(ev: EnrichedToolEvent) -> str:
    """从事件 argv 提取入口引用，与 discovery._extract_entry 等价。"""
    argv = list(ev.raw.argv)
    for arg in argv:
        if arg.endswith(".py") or arg.endswith(".sh"):
            return arg
    if "-m" in argv:
        idx = argv.index("-m")
        if idx + 1 < len(argv):
            return f"-m {argv[idx + 1]}"
    return argv[0] if argv else ""


def cross_input_count(episodes: list[Episode]) -> int:
    """跨输入复用计数：同 entry_ref 被用于不同输入文件的次数。

    返回 ≥2 时表示脚本被至少复用到第二个输入——这是置信度提升信号。
    """
    seen: dict[str, set[str]] = defaultdict(set)  # entry_ref → {input paths}
    for ep in episodes:
        if not ep.has_success:
            continue
        ref = _extract_entry_ref(ep.final_exec)
        if not ref:
            continue
        in_paths = {a.path for a in ep.final_exec.input_artifacts}
        seen[ref] |= in_paths
    # 跨输入：同 entry_ref 下出现不同 input path 的 episode 数
    total = sum(1 for paths in seen.values() if len(paths) >= 2)
    return total
