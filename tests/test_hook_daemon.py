"""Hook + Daemon 测试（阶段 7）。"""
import json
import tempfile
from pathlib import Path

from distiller import daemon, db, hook, observe


class TestHook:
    def test_writes_events_jsonl(self, tmp_path):
        traces = tmp_path / "traces"
        eid = hook.write_event(
            traces,
            session_id="s1",
            cwd="/work",
            tool_name="Bash",
            command="python conv.py a.html",
            exit_code=0,
        )
        assert eid

        events_file = traces / "s1" / "events.jsonl"
        assert events_file.exists()

        lines = events_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) >= 1
        first = json.loads(lines[0])
        assert first["event_id"] == eid
        assert first["session_id"] == "s1"
        assert first["command"] == "python conv.py a.html"

    def test_silent_failure_on_bad_path(self):
        """写事件到只读/无效路径时静默失败，不抛异常。"""
        uid = hook.write_event(
            Path("/dev/null/readonly"),
            session_id="s", cwd=".", tool_name="X", command="x",
        )
        assert uid  # 仍返回 uuid，只是不写盘


class TestDaemonCheckpoint:
    def test_new_events(self, tmp_path):
        cp = daemon.Checkpoint(tmp_path / "cp.json")
        assert cp.is_new("s1", "e1")
        cp.mark("s1", ["e1"])
        assert not cp.is_new("s1", "e1")
        assert cp.is_new("s1", "e2")

    def test_persists_and_reloads(self, tmp_path):
        p = tmp_path / "cp.json"
        cp1 = daemon.Checkpoint(p)
        cp1.mark("s1", ["e1"])
        cp1.save()
        cp2 = daemon.Checkpoint(p)
        assert not cp2.is_new("s1", "e1")
        assert cp2.total_processed == 1


class TestDaemonIngest:
    """daemon ingest 端到端 — Hook 写入 → Daemon 处理 → promoted skill"""
    @staticmethod
    def _setup_workspace(ws: Path):
        """在指定 workspace 里创建可 replay 的脚本和 HTML 输入。"""
        (ws / "conv.py").write_text(
            'import sys\n'
            'html = open(sys.argv[1], encoding="utf-8").read()\n'
            'import re\n'
            'text = re.sub(r"<[^>]+>", "", html).strip()\n'
            'print("# Report\\n\\n" + text)\n',
            encoding="utf-8",
        )
        body = "Revenue grew across every region this quarter. " * 5
        (ws / "report.html").write_text(
            f"<html><body><h1>R</h1><p>{body}</p></body></html>",
            encoding="utf-8",
        )

    def test_ingest_happy_path(self, tmp_path):
        """Hook 写入 → daemon ingest → promoted skill 落地。"""
        ws = tmp_path / "ws"; ws.mkdir()
        self._setup_workspace(ws)
        data_dir = tmp_path / "data"; data_dir.mkdir()
        traces = data_dir / "traces"

        hook.write_event(
            traces, session_id="s1", cwd=str(ws),
            tool_name="Bash",
            command="python conv.py report.html",
            exit_code=0,
            input_paths=[str(ws / "report.html")],
            output_paths=[str(ws / "out.md")],
        )
        result = daemon.ingest_traces(data_dir)
        assert result["promoted"] >= 1

    def test_ingest_respects_checkpoint(self, tmp_path):
        """同 session 处理完后不再重复处理。"""
        ws = tmp_path / "ws"; ws.mkdir()
        self._setup_workspace(ws)
        data_dir = tmp_path / "data"; data_dir.mkdir()
        traces = data_dir / "traces"

        hook.write_event(
            traces, session_id="s1", cwd=str(ws),
            tool_name="Bash", command="python conv.py report.html", exit_code=0,
            input_paths=[str(ws / "report.html")],
            output_paths=[str(ws / "out.md")],
        )
        r1 = daemon.ingest_traces(data_dir)
        assert r1["promoted"] >= 1
        r2 = daemon.ingest_traces(data_dir)
        assert r2["new_events"] == 0
        assert r2["promoted"] == 0

    def test_ingest_noop_on_empty_traces(self, tmp_path):
        data_dir = tmp_path / "data"; data_dir.mkdir()
        (data_dir / "traces").mkdir()
        result = daemon.ingest_traces(data_dir)
        assert result["new_events"] == 0
