"""tests/test_observe.py — M7a 只读观测模块测试。

建内存库 → apply_schema → 手动 INSERT fixtures → 验证每个查询函数。
列名以 db.py 真实 schema 为准。
"""
import sqlite3

import pytest

from distiller import db
from distiller.observe import (
    failures,
    list_skills,
    quality_of,
    show_skill,
    usage,
)


# --------------------------------------------------------------------------- #
# Fixture：临时内存库（schema + 样本数据）
# --------------------------------------------------------------------------- #

@pytest.fixture
def conn():
    """内存库：apply_schema + fixtures，yield 后关闭。"""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    db.apply_schema(c)

    # ── skills ──────────────────────────────────────────────────────────────
    c.execute(
        """INSERT INTO skills(name, purpose, when_to_use, status, visibility, tags)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            "doc-to-markdown",
            "文档转 markdown",
            "需要把 pdf/docx 转 md 时",
            "promoted",
            "invokable_by_id",
            '["convert","markdown"]',
        ),
    )
    # 第二个 skill：无 quality / 无 branches / 无 usage
    c.execute(
        """INSERT INTO skills(name, purpose, status, visibility)
           VALUES (?, ?, ?, ?)""",
        ("another-skill", "另一个示例", "promoted", "hidden"),
    )

    # ── branches ────────────────────────────────────────────────────────────
    c.execute(
        """INSERT INTO branches(skill_name, key, active_impl_ref, active_version, retained_impls)
           VALUES (?, ?, ?, ?, ?)""",
        ("doc-to-markdown", "pdf", "./branches/pdf.py", 1, "[]"),
    )
    c.execute(
        """INSERT INTO branches(skill_name, key, active_impl_ref, active_version, retained_impls)
           VALUES (?, ?, ?, ?, ?)""",
        ("doc-to-markdown", "docx", "./branches/docx.py", 2, "[]"),
    )

    # ── quality_rollup ──────────────────────────────────────────────────────
    c.execute(
        """INSERT INTO quality_rollup(skill_name, reuse_count, success_rate, last_used)
           VALUES (?, ?, ?, ?)""",
        ("doc-to-markdown", 7, 0.857, "2026-06-20T10:00:00Z"),
    )

    # ── usage_events ────────────────────────────────────────────────────────
    c.execute(
        """INSERT INTO usage_events
               (skill_name, branch_key, host_agent, status, input_summary, warmstart_hit, ts)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("doc-to-markdown", "pdf", "claude-code", "success", "a.pdf", 1, "2026-06-20T09:00:00Z"),
    )
    c.execute(
        """INSERT INTO usage_events
               (skill_name, branch_key, host_agent, status, input_summary, warmstart_hit, ts)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("doc-to-markdown", "pdf", "claude-code", "error", "b.pdf", 0, "2026-06-20T10:00:00Z"),
    )
    # 属于 another-skill 的事件（用于隔离测试）
    c.execute(
        """INSERT INTO usage_events
               (skill_name, branch_key, host_agent, status, input_summary, warmstart_hit, ts)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("another-skill", "default", "codex", "success", "x.txt", 0, "2026-06-20T08:00:00Z"),
    )

    # ── r_miss ──────────────────────────────────────────────────────────────
    c.execute(
        """INSERT INTO r_miss(skill_name, branch_key, contract_slice, version, failure_class, ts)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            "doc-to-markdown", "pdf",
            '{"input_type":"pdf_scanned"}',
            1, "output_not_pass", "2026-06-20T10:00:00Z",
        ),
    )
    c.execute(
        """INSERT INTO r_miss(skill_name, branch_key, contract_slice, version, failure_class, ts)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            "doc-to-markdown", "docx",
            '{"input_type":"docx_complex"}',
            1, "crash", "2026-06-20T11:00:00Z",
        ),
    )

    c.commit()
    yield c
    c.close()


# --------------------------------------------------------------------------- #
# list_skills
# --------------------------------------------------------------------------- #

class TestListSkills:
    def test_returns_both_skills(self, conn):
        result = list_skills(conn)
        names = [r["name"] for r in result]
        assert "doc-to-markdown" in names
        assert "another-skill" in names

    def test_branch_count_doc_to_markdown(self, conn):
        rows = {r["name"]: r for r in list_skills(conn)}
        assert rows["doc-to-markdown"]["branch_count"] == 2

    def test_branch_count_zero_for_no_branches(self, conn):
        rows = {r["name"]: r for r in list_skills(conn)}
        assert rows["another-skill"]["branch_count"] == 0

    def test_reuse_count_from_quality_rollup(self, conn):
        rows = {r["name"]: r for r in list_skills(conn)}
        assert rows["doc-to-markdown"]["reuse_count"] == 7

    def test_success_rate_from_quality_rollup(self, conn):
        rows = {r["name"]: r for r in list_skills(conn)}
        assert abs(rows["doc-to-markdown"]["success_rate"] - 0.857) < 1e-9

    def test_no_quality_row_defaults_to_zero(self, conn):
        rows = {r["name"]: r for r in list_skills(conn)}
        assert rows["another-skill"]["reuse_count"] == 0
        assert rows["another-skill"]["success_rate"] == 0.0

    def test_visibility_and_status(self, conn):
        rows = {r["name"]: r for r in list_skills(conn)}
        assert rows["doc-to-markdown"]["visibility"] == "invokable_by_id"
        assert rows["doc-to-markdown"]["status"] == "promoted"
        assert rows["another-skill"]["visibility"] == "hidden"

    def test_result_is_list_of_dicts(self, conn):
        result = list_skills(conn)
        assert isinstance(result, list)
        assert all(isinstance(r, dict) for r in result)


# --------------------------------------------------------------------------- #
# show_skill
# --------------------------------------------------------------------------- #

class TestShowSkill:
    def test_basic_fields(self, conn):
        result = show_skill(conn, "doc-to-markdown")
        assert result["name"] == "doc-to-markdown"
        assert result["purpose"] == "文档转 markdown"
        assert result["status"] == "promoted"

    def test_branches_list(self, conn):
        result = show_skill(conn, "doc-to-markdown")
        assert "branches" in result
        assert isinstance(result["branches"], list)
        assert len(result["branches"]) == 2

    def test_branch_keys(self, conn):
        result = show_skill(conn, "doc-to-markdown")
        keys = {b["key"] for b in result["branches"]}
        assert keys == {"pdf", "docx"}

    def test_branch_active_impl_ref(self, conn):
        result = show_skill(conn, "doc-to-markdown")
        pdf_b = next(b for b in result["branches"] if b["key"] == "pdf")
        assert pdf_b["active_impl_ref"] == "./branches/pdf.py"
        assert pdf_b["active_version"] == 1

    def test_branch_retained_impls_field_present(self, conn):
        result = show_skill(conn, "doc-to-markdown")
        for b in result["branches"]:
            assert "retained_impls" in b

    def test_quality_embedded(self, conn):
        result = show_skill(conn, "doc-to-markdown")
        q = result["quality"]
        assert q["reuse_count"] == 7
        assert abs(q["success_rate"] - 0.857) < 1e-9
        assert q["last_used"] == "2026-06-20T10:00:00Z"

    def test_quality_empty_when_no_row(self, conn):
        result = show_skill(conn, "another-skill")
        assert result["quality"] == {}

    def test_contract_signatures_is_list(self, conn):
        result = show_skill(conn, "doc-to-markdown")
        assert isinstance(result["contract_signatures"], list)

    def test_nonexistent_returns_empty_dict(self, conn):
        assert show_skill(conn, "no-such-skill") == {}


# --------------------------------------------------------------------------- #
# usage
# --------------------------------------------------------------------------- #

class TestUsage:
    def test_returns_two_events_for_doc_to_markdown(self, conn):
        result = usage(conn, "doc-to-markdown")
        assert len(result) == 2

    def test_event_statuses(self, conn):
        result = usage(conn, "doc-to-markdown")
        statuses = {r["status"] for r in result}
        assert statuses == {"success", "error"}

    def test_warmstart_hit_values(self, conn):
        result = usage(conn, "doc-to-markdown")
        hits = [r["warmstart_hit"] for r in result]
        assert 1 in hits
        assert 0 in hits

    def test_required_fields_present(self, conn):
        result = usage(conn, "doc-to-markdown")
        required = (
            "id", "skill_name", "branch_key", "host_agent",
            "status", "input_summary", "warmstart_hit", "ts",
        )
        for row in result:
            for field in required:
                assert field in row, f"missing field: {field}"

    def test_no_cross_skill_contamination(self, conn):
        result = usage(conn, "doc-to-markdown")
        assert all(r["skill_name"] == "doc-to-markdown" for r in result)

    def test_another_skill_own_events(self, conn):
        result = usage(conn, "another-skill")
        assert len(result) == 1
        assert result[0]["skill_name"] == "another-skill"

    def test_unknown_skill_returns_empty(self, conn):
        assert usage(conn, "nonexistent") == []


# --------------------------------------------------------------------------- #
# failures
# --------------------------------------------------------------------------- #

class TestFailures:
    def test_returns_two_rows(self, conn):
        result = failures(conn, "doc-to-markdown")
        assert len(result) == 2

    def test_failure_classes(self, conn):
        result = failures(conn, "doc-to-markdown")
        classes = {r["failure_class"] for r in result}
        assert "output_not_pass" in classes
        assert "crash" in classes

    def test_required_fields_present(self, conn):
        result = failures(conn, "doc-to-markdown")
        required = (
            "id", "skill_name", "branch_key", "contract_slice",
            "version", "env_fingerprint", "failure_class", "ts",
        )
        for row in result:
            for field in required:
                assert field in row, f"missing field: {field}"

    def test_contract_slice_content(self, conn):
        result = failures(conn, "doc-to-markdown")
        slices = {r["contract_slice"] for r in result}
        assert '{"input_type":"pdf_scanned"}' in slices

    def test_no_failures_for_another_skill(self, conn):
        assert failures(conn, "another-skill") == []

    def test_unknown_skill_returns_empty(self, conn):
        assert failures(conn, "nonexistent") == []


# --------------------------------------------------------------------------- #
# quality_of
# --------------------------------------------------------------------------- #

class TestQualityOf:
    def test_reuse_count(self, conn):
        assert quality_of(conn, "doc-to-markdown")["reuse_count"] == 7

    def test_success_rate(self, conn):
        assert abs(quality_of(conn, "doc-to-markdown")["success_rate"] - 0.857) < 1e-9

    def test_last_used(self, conn):
        assert quality_of(conn, "doc-to-markdown")["last_used"] == "2026-06-20T10:00:00Z"

    def test_no_row_returns_empty_dict(self, conn):
        assert quality_of(conn, "another-skill") == {}

    def test_unknown_skill_returns_empty_dict(self, conn):
        assert quality_of(conn, "nonexistent") == {}

    def test_result_is_dict(self, conn):
        assert isinstance(quality_of(conn, "doc-to-markdown"), dict)
