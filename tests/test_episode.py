"""Episode Builder 测试（阶段 5）。"""
from distiller import episode
from distiller.contracts import (
    Artifact,
    EnrichedToolEvent,
    RawToolEvent,
)


def _make_exec(task_id, cwd, argv, exit_code, inputs=None, outputs=None, event_id="e"):
    raw = RawToolEvent(
        event_id=event_id, session_id="s", project_id="p", task_id=task_id,
        host_agent="cc", timestamp="2026-07-04T10:00:00Z",
        event_type="command_exec",
        name=" ".join(argv), cwd=cwd, argv=argv, exit_code=exit_code,
    )
    return EnrichedToolEvent(
        raw=raw,
        input_artifacts=inputs or [],
        output_artifacts=outputs or [],
    )


def _make_write(task_id, cwd, name, argv, event_id="w"):
    raw = RawToolEvent(
        event_id=event_id, session_id="s", project_id="p", task_id=task_id,
        host_agent="cc", timestamp="2026-07-04T10:01:00Z",
        event_type="generated_code",
        name=name, cwd=cwd, argv=argv, exit_code=0,
    )
    return EnrichedToolEvent(raw=raw)


def _make_explore(task_id, cwd, event_id="x"):
    raw = RawToolEvent(
        event_id=event_id, session_id="s", project_id="p", task_id=task_id,
        host_agent="cc", timestamp="2026-07-04T10:02:00Z",
        event_type="prompt", name="", cwd=cwd, argv=[], exit_code=0,
    )
    return EnrichedToolEvent(raw=raw)


class TestBuildEpisodes:
    def test_single_success(self):
        ev = _make_exec("t1", "/w", ["python", "conv.py", "a.html"], 0)
        eps = episode.build_episodes([ev])
        assert len(eps) == 1
        assert eps[0].has_success
        assert eps[0].final_exec is not None

    def test_final_success_after_failures(self):
        f1 = _make_exec("t1", "/w", ["python", "conv.py", "a.html"], 1, event_id="e1")
        f2 = _make_exec("t1", "/w", ["python", "conv.py", "a.html"], 1, event_id="e2")
        ok = _make_exec("t1", "/w", ["python", "conv.py", "a.html"], 0, event_id="e3")
        eps = episode.build_episodes([f1, f2, ok])
        assert eps[0].has_success
        assert eps[0].final_exec.raw.event_id == "e3"
        assert len(eps[0].failed_attempts) == 2

    def test_noise_filtered_into_noise(self):
        x = _make_explore("t1", "/w")
        eps = episode.build_episodes([x])
        assert len(eps) == 1
        assert not eps[0].has_success
        assert len(eps[0].noise_events) == 1

    def test_all_failures_no_success(self):
        f1 = _make_exec("t-bad", "/w", ["python", "x.py"], 1, event_id="e1")
        f2 = _make_exec("t-bad", "/w", ["python", "x.py"], 1, event_id="e2")
        eps = episode.build_episodes([f1, f2])
        assert not eps[0].has_success
        assert len(eps[0].failed_attempts) == 2

    def test_multiple_groups(self):
        a = _make_exec("t-a", "/a", ["python", "a.py"], 0)
        b = _make_exec("t-b", "/b", ["python", "b.py"], 0)
        eps = episode.build_episodes([a, b])
        assert len(eps) == 2

    def test_fail_then_success_then_reuse_on_second_input(self):
        """10+ 动作长链：写 v1→失败→修→成功→复用第二输入。只沉淀最终成功。"""
        events = [
            _make_exec("t-long", "/w", ["python", "conv.py", "q1.html"], 1, event_id="e1"),
            _make_exec("t-long", "/w", ["python", "conv.py", "q1.html"], 0, event_id="e2",
                       inputs=[Artifact(path="q1.html", media_type="text/html")],
                       outputs=[Artifact(path="q1.md", media_type="text/markdown")]),
            _make_exec("t-long", "/w", ["python", "conv.py", "q2.html"], 0, event_id="e3",
                       inputs=[Artifact(path="q2.html", media_type="text/html")],
                       outputs=[Artifact(path="q2.md", media_type="text/markdown")]),
            _make_write("t-long", "/w", "conv.py", ["write", "conv.py"]),
            _make_explore("t-long", "/w"),
        ]
        eps = episode.build_episodes(events)
        assert len(eps) == 1
        ep = eps[0]
        assert ep.has_success
        # final_exec = 最后一个成功的 exec
        assert ep.final_exec.raw.event_id == "e3"
        assert len(ep.failed_attempts) == 1
        assert len(ep.noise_events) == 1
        assert len(ep.related_writes) == 1  # 写入事件的 name 含 "conv.py" → 匹配

    def test_related_writes_attached(self):
        ev = _make_exec("t1", "/w", ["python", "conv.py", "a.html"], 0,
                        inputs=[Artifact(path="a.html", media_type="text/html")],
                        outputs=[Artifact(path="a.md", media_type="text/markdown")])
        wr = _make_write("t1", "/w", "conv.py", ["write", "conv.py"])
        eps = episode.build_episodes([ev, wr])
        assert len(eps[0].related_writes) == 1


class TestCrossInputCount:
    def test_zero_when_no_reuse(self):
        ep = episode.build_episodes([
            _make_exec("t1", "/w", ["python", "conv.py", "a.html"], 0,
                       inputs=[Artifact(path="a.html", media_type="text/html")]),
        ])
        assert episode.cross_input_count(ep) == 0

    def test_counts_when_same_script_on_two_inputs(self):
        eps = [
            episode.build_episodes([
                _make_exec("t1", "/w", ["python", "conv.py", "q1.html"], 0,
                           inputs=[Artifact(path="q1.html", media_type="text/html")]),
            ])[0],
            episode.build_episodes([
                _make_exec("t2", "/w", ["python", "conv.py", "q2.html"], 0,
                           inputs=[Artifact(path="q2.html", media_type="text/html")]),
            ])[0],
        ]
        assert episode.cross_input_count(eps) >= 1
