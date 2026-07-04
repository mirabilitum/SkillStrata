"""Artifact Store 单元测试 + 端到端快照存活测试（阶段 2）。

验证 promoted skill 的实现与 fixture 被快照到数据目录内后：
  - branches.active_impl_ref 指向 data-dir 相对路径（不依赖原工作区）
  - 删除原工作区后 distiller show 仍能看到可用 impl ref
  - 幂等 re-promote 覆盖旧快照
"""
from __future__ import annotations

from pathlib import Path

from distiller import artifact_store, db, pipeline
from distiller.contracts import Artifact, EnrichedToolEvent, RawToolEvent


# ———————————————————————————————————————————————————————————— #
# fixtures
# ———————————————————————————————————————————————————————————— #

_CONV_SRC = '''\
import sys
html = open(sys.argv[1], encoding="utf-8").read()
import re
text = re.sub(r"<[^>]+>", "", html).strip()
print("# Smoke Report\\n\\n" + text)
'''

_INPUT_HTML = (
    "<html><body><h1>Q2 Report</h1>"
    "<p>Revenue grew across every region this quarter. The engineering team "
    "shipped the new pipeline and reduced manual reporting work across all teams.</p>"
    "<p>Customer retention held steady near ninety percent overall.</p>"
    "</body></html>\n"
)


def _write(p: Path, s: str) -> Path:
    p.write_text(s, encoding="utf-8")
    return p


def _event(task_id, cwd, script, inp, eid):
    raw = RawToolEvent(
        event_id=eid, session_id="s", project_id="p", task_id=task_id,
        host_agent="cc", timestamp="2026-07-04T10:00:00Z",
        event_type="command_exec", name=f"python {script} {inp}",
        cwd=cwd, argv=["python", script, inp], exit_code=0,
    )
    return EnrichedToolEvent(
        raw=raw,
        input_artifacts=[Artifact(path=inp, media_type="text/html")],
        output_artifacts=[Artifact(path=str(Path(cwd) / "out.md"), media_type="text/markdown")],
    )


# ———————————————————————————————————————————————————————————— #
# 单元测试：snapshot_promoted
# ———————————————————————————————————————————————————————————— #

class TestSnapshotPromoted:
    def test_creates_skill_dir_structure(self, tmp_path):
        data_root = tmp_path / "data"
        data_root.mkdir()
        impl = _write(tmp_path / "conv.py", "print('hello')")
        inp = _write(tmp_path / "in.html", "<p>x</p>")

        impl_ref, fix_ref = artifact_store.snapshot_promoted(
            data_root, "doc-to-md", "html", 1,
            impl_path=impl, input_fixture_path=inp,
            output_text="# Title\n\nbody",
        )

        skill_dir = data_root / "skills" / "doc-to-md" / "html" / "v1"
        assert skill_dir.is_dir()
        assert (skill_dir / "impl.py").read_text() == "print('hello')"
        assert (skill_dir / "fixtures" / "input.html").read_text() == "<p>x</p>"
        assert (skill_dir / "fixtures" / "output.md").read_text() == "# Title\n\nbody"
        assert (skill_dir / "manifest.json").exists()

        # refs 是 data-dir 相对路径
        assert "skills/doc-to-md/html/v1/impl.py" in impl_ref
        assert not impl_ref.startswith("/")

    def test_idempotent_overwrite(self, tmp_path):
        data_root = tmp_path / "data"
        data_root.mkdir()
        impl = _write(tmp_path / "v1.py", "v1")
        impl2 = _write(tmp_path / "v2.py", "v2-updated")

        artifact_store.snapshot_promoted(data_root, "s", "b", 1, impl_path=impl)
        artifact_store.snapshot_promoted(data_root, "s", "b", 1, impl_path=impl2)

        skill_dir = data_root / "skills" / "s" / "b" / "v1"
        assert (skill_dir / "impl.py").read_text() == "v2-updated"


# ———————————————————————————————————————————————————————————— #
# 端到端：pipeline 接入后快照存活
# ———————————————————————————————————————————————————————————— #

def test_e2e_snapshot_survives_workspace_deletion(tmp_path):
    """run_from_db → promoted skill 快照到 data-dir；删掉工作区后 impl 仍可寻址。"""
    # 模拟工作区（类似 .cc-smoke/）
    ws = tmp_path / "workspace"
    ws.mkdir()
    _write(ws / "conv.py", _CONV_SRC)
    _write(ws / "report.html", _INPUT_HTML)

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "meta.sqlite"

    events = [_event("t1", str(ws), "conv.py", "report.html", "e1")]

    # 走 run_from_db → 自动启用 Artifact Store
    result = pipeline.run_from_db(db_path, events)
    assert result.promoted_skills

    # 验证快照落盘到 data-dir
    impl_snapshot = data_dir / "skills" / "document-to-markdown" / "html" / "v1" / "impl.py"
    assert impl_snapshot.is_file(), f"expected snapshot at {impl_snapshot}"
    assert (data_dir / "skills" / "document-to-markdown" / "html" / "v1" / "manifest.json").exists()

    # DB 里的 active_impl_ref 应指向快照相对路径，而非原工作区
    conn = db.connect(db_path)
    try:
        row = conn.execute(
            "SELECT active_impl_ref, fixtures_ref FROM branches WHERE skill_name=?",
            ("document-to-markdown",),
        ).fetchone()
        assert row["active_impl_ref"].startswith("skills/")
        assert "workspace" not in row["active_impl_ref"]
    finally:
        conn.close()

    # 删掉原工作区 → skill 元数据仍完整
    import shutil
    shutil.rmtree(ws)

    # CLI show 仍能找到 impl ref（因为现在指向 data-dir 内部）
    conn2 = db.connect(db_path)
    try:
        row2 = conn2.execute(
            "SELECT active_impl_ref FROM branches WHERE skill_name=?",
            ("document-to-markdown",),
        ).fetchone()
        impl_ref = row2["active_impl_ref"]
        snapshot_path = data_dir / impl_ref
        assert snapshot_path.is_file()
    finally:
        conn2.close()
