"""Judge 模块测试（阶段 4 API Judge）。"""
from pathlib import Path

from distiller import config, db, judge, pipeline
from distiller.contracts import (
    Artifact,
    Candidate,
    ContractSignature,
    EnrichedToolEvent,
    ExecContext,
    RawToolEvent,
)


# ——————————————————————————————————— #
# RuleJudge
# ——————————————————————————————————— #

class TestRuleJudge:
    def test_returns_structured_result(self):
        rj = judge.RuleJudge()
        cand = Candidate(
            id="cand-1", purpose_guess="convert-csv-to-json",
            context=ExecContext(source_ref={"domain": "generic_file_transform"}),
        )
        sig = ContractSignature(
            input_media_types=["text/csv"],
            output_types=["application/json"],
            purpose_summary="convert csv metrics to json",
        )
        result = rj.judge(cand, sig)
        assert result["is_reusable"] is True
        assert "csv" in result["purpose"]
        assert result["suggested_skill_name"] == "convert-csv-metrics-to-json"
        assert result["inputs"] == ["text/csv"]
        assert result["outputs"] == ["application/json"]
        assert result["domain"] == "generic_file_transform"
        assert result["confidence"] == 0.80  # rule judge 固定值

    def test_no_domain_when_missing(self):
        rj = judge.RuleJudge()
        cand = Candidate(id="cand-2", purpose_guess="x")
        sig = ContractSignature()
        result = rj.judge(cand, sig)
        assert result["domain"] == ""


# ——————————————————————————————————— #
# make_judge（工厂）
# ——————————————————————————————————— #

class TestMakeJudge:
    def test_offline_when_no_key(self):
        cfg = config.load()
        j = judge.make_judge(cfg)
        assert isinstance(j, judge.RuleJudge)

    def test_rule_judge_is_default(self):
        # 无 env key → offline → RuleJudge
        cfg = config.load(env={})
        j = judge.make_judge(cfg)
        assert isinstance(j, judge.RuleJudge)


# ——————————————————————————————————— #
# e2e：pipeline 接入 judge
# ——————————————————————————————————— #

_CONV_SRC = '''\
import sys
html = open(sys.argv[1], encoding="utf-8").read()
import re
text = re.sub(r"<[^>]+>", "", html).strip()
print("# Report\\n\\n" + text)
'''

_INPUT_HTML = (
    "<html><body><h1>Report</h1>"
    "<p>Revenue grew across every region this quarter. "
    "The engineering team shipped the new pipeline. "
    "Customer retention held steady near ninety percent. "
    "Next quarter we focus on reuse driven quality promotion.</p>"
    "</body></html>\n"
)


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


def test_e2e_judge_enriches_outcome(tmp_path):
    """pipeline 接 judge 后，outcome 含 judge_result；context 含 judge JSON。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    _write(ws / "conv.py", _CONV_SRC)
    _write(ws / "report.html", _INPUT_HTML)

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    conn = db.connect(data_dir / "meta.sqlite")
    try:
        db.apply_schema(conn)
        events = [_event("t1", str(ws), "conv.py", "report.html", "text/html",
                         str(ws / "out.md"), "text/markdown", "e1")]
        result = pipeline.run_pipeline(
            conn, events,
            data_dir=data_dir,
            _judge=judge.RuleJudge(),
        )
        assert result.promoted_skills
        o = result.outcomes[0]
        assert o.judge_result is not None
        assert o.judge_result["is_reusable"] is True
        assert "purpose" in o.judge_result

        # context.source_ref 含 judge JSON
        import json
        ctx_raw = conn.execute(
            "SELECT context FROM candidates WHERE id=?", (o.candidate_id,)
        ).fetchone()[0]
        ctx = json.loads(ctx_raw) if isinstance(ctx_raw, str) else {}
        assert "judge" in ctx.get("source_ref", {}), f"source_ref: {ctx.get('source_ref')}"
    finally:
        conn.close()

    # 不传 judge → outcome.judge_result 为 None（向后兼容）
    conn2 = db.connect(data_dir / "meta.sqlite2")
    try:
        db.apply_schema(conn2)
        events2 = [_event("t2", str(ws), "conv.py", "report.html", "text/html",
                          str(ws / "out2.md"), "text/markdown", "e2")]
        result2 = pipeline.run_pipeline(conn2, events2, data_dir=data_dir)
        assert result2.outcomes[0].judge_result is None
    finally:
        conn2.close()
