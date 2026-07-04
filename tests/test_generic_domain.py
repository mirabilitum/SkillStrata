"""GenericFileTransformDomain 测试（阶段 3）。"""
from __future__ import annotations

import csv, io, json as _json
from pathlib import Path

from distiller import db, pipeline
from distiller.contracts import Artifact, EnrichedToolEvent, RawToolEvent
from distiller.domains.generic_file_transform import (
    GenericFileTransformDomain,
    _conservation_pass,
)


# ——————————————————————————————————— #
# 单元测试
# ——————————————————————————————————— #

class TestConservationPass:
    def test_csv_to_json_row_count_match(self):
        inp = "a,b\n1,2\n3,4\n"
        out = '[{"a":"1","b":"2"},{"a":"3","b":"4"}]'
        assert _conservation_pass(inp, out, ("text/csv", "application/json")) is True

    def test_csv_to_json_row_count_mismatch(self):
        inp = "a,b\n1,2\n3,4\n5,6\n"
        out = '[{"a":"1"}]'
        assert _conservation_pass(inp, out, ("text/csv", "application/json")) is False

    def test_text_to_text_coverage(self):
        inp = "Revenue grew across every region this quarter"
        out = "Revenue grew across every region this quarter"
        assert _conservation_pass(inp, out, ("text/plain", "text/markdown")) is True

    def test_text_to_text_empty_output(self):
        assert _conservation_pass("hello", "", ("text/plain", "text/markdown")) is False


class TestGenericShapeMatch:
    def test_matches_file_transform(self):
        d = GenericFileTransformDomain()
        rec = {
            "entry_ref": "conv.py", "entry_kind": "script",
            "exit_code": 0,
            "input_artifacts": [Artifact(path="in.csv", media_type="text/csv")],
            "output_artifacts": [Artifact(path="out.json", media_type="application/json")],
        }
        assert d.shape_match(rec) is True

    def test_rejects_same_paths(self):
        d = GenericFileTransformDomain()
        rec = {
            "entry_ref": "conv.py", "entry_kind": "script",
            "exit_code": 0,
            "input_artifacts": [Artifact(path="f.json", media_type="application/json")],
            "output_artifacts": [Artifact(path="f.json", media_type="application/json")],
        }
        assert d.shape_match(rec) is False

    def test_rejects_no_input(self):
        d = GenericFileTransformDomain()
        rec = {"entry_ref": "conv.py", "exit_code": 0, "input_artifacts": [],
               "output_artifacts": [Artifact(path="out.txt")]}
        assert d.shape_match(rec) is False

    def test_rejects_failed(self):
        d = GenericFileTransformDomain()
        rec = {"entry_ref": "conv.py", "exit_code": 1,
               "input_artifacts": [Artifact(path="a.txt")],
               "output_artifacts": [Artifact(path="b.txt")]}
        assert d.shape_match(rec) is False


class TestBranchKey:
    def test_derives_from_media_types(self):
        d = GenericFileTransformDomain()
        from distiller.contracts import Candidate, ContractSignature
        c = Candidate(id="x", purpose_guess="p",
                      input_artifacts=[Artifact(path="a.csv", media_type="text/csv")],
                      output_artifacts=[Artifact(path="a.json", media_type="application/json")])
        sig = ContractSignature()
        assert d.branch_key(c, sig) == "csv_to_json"


# ——————————————————————————————————— #
# e2e：CSV → JSON 完整链路
# ——————————————————————————————————— #

_CSV_TO_JSON_SRC = '''\
import csv, json, sys
rows = list(csv.reader(open(sys.argv[1], encoding="utf-8")))
headers = rows[0]
data = [dict(zip(headers, r)) for r in rows[1:]]
print(json.dumps(data, indent=2))
'''


def _write(p: Path, s: str) -> Path:
    p.write_text(s, encoding="utf-8")
    return p


def _event(task_id, cwd, script, inp, in_media, out_path, out_media, eid):
    raw = RawToolEvent(
        event_id=eid, session_id="s", project_id="p", task_id=task_id,
        host_agent="cc", timestamp="2026-07-04T10:00:00Z",
        event_type="command_exec", name=f"python {script} {inp}",
        cwd=cwd, argv=["python", script, inp], exit_code=0,
    )
    return EnrichedToolEvent(
        raw=raw,
        input_artifacts=[Artifact(path=inp, media_type=in_media)],
        output_artifacts=[Artifact(path=out_path, media_type=out_media)],
    )


def test_e2e_csv_to_json_promoted_as_generic(tmp_path):
    """CSV→JSON 转换被 generic 域抓取、过行数守恒 gate、沉淀为 promoted skill。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    csv_in = (
        "name,score\n"
        "Alice,95\n"
        "Bob,87\n"
        "Carol,92\n"
    )
    _write(ws / "scores.csv", csv_in)
    _write(ws / "conv.py", _CSV_TO_JSON_SRC)

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "meta.sqlite"

    events = [_event("t1", str(ws), "conv.py", "scores.csv", "text/csv",
                     str(ws / "out.json"), "application/json", "e1")]

    result = pipeline.run_from_db(db_path, events)
    assert result.promoted_skills
    skill_name = result.promoted_skills[0]

    # generic 域的 purpose_guess 格式
    assert skill_name.startswith("convert-csv-to-json") or "csv" in skill_name

    o = result.outcomes[0]
    assert o.pipeline_status == "active"
    # generic 域应命中（不是 doc 域）
    conn = db.connect(db_path)
    try:
        ctx_raw = conn.execute(
            "SELECT context FROM candidates WHERE id=?", (o.candidate_id,)
        ).fetchone()[0]
        import json
        ctx = json.loads(ctx_raw) if isinstance(ctx_raw, str) else {}
        assert ctx.get("source_ref", {}).get("domain") == "generic_file_transform"
    finally:
        conn.close()


def test_e2e_doc_domain_still_wins_for_html_to_md(tmp_path):
    """HTML→MD 仍被 document_to_markdown 域抓取（注册顺序保证 doc 域优先）。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    _write(ws / "conv.py", 'import sys; print("# " + open(sys.argv[1]).read())')
    _write(ws / "report.html", "<html><body>" + "Revenue grew. " * 10 + "</body></html>")

    data_dir = tmp_path / "data"
    data_dir.mkdir()

    events = [_event("t1", str(ws), "conv.py", "report.html", "text/html",
                     str(ws / "out.md"), "text/markdown", "e1")]
    result = pipeline.run_from_db(str(data_dir / "meta.sqlite"), events)
    assert result.promoted_skills
    assert "document-to-markdown" in result.promoted_skills


def test_e2e_dangerous_script_rejected_by_safety(tmp_path):
    """含 os.remove 的脚本 → safety 判 dangerous → rejected，不进 replay。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    # 脚本里有 os.remove（危险操作）
    _write(ws / "danger.py",
        'import sys, os, csv, json\n'
        'os.remove("cleanup.tmp")\n'  # dangerous
        'rows = list(csv.reader(open(sys.argv[1])))\n'
        'print(json.dumps(rows))\n'
    )
    _write(ws / "scores.csv", "name,score\nAlice,95\n")

    data_dir = tmp_path / "data"
    data_dir.mkdir()

    events = [_event("t-d", str(ws), "danger.py", "scores.csv", "text/csv",
                     str(ws / "out.json"), "application/json", "e-d")]
    result = pipeline.run_from_db(str(data_dir / "meta.sqlite"), events)

    o = result.outcomes[0]
    assert o.pipeline_status == "rejected"
    assert "dangerous" in o.reason
    assert result.promoted_skills == []
