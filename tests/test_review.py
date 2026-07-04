"""tests/test_review.py — M7b 审查动作 + 质量门控 + CLI 接线测试。

建内存库 → apply_schema → 手动 INSERT fixtures → 验证每个函数。
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from distiller import db
from distiller.cli_pending import get_review, list_pending
from distiller.review import (
    auto_upgrade_quality,
    deprecate,
    pin_path_b,
    resolve_iteration,
    resolve_keep_both,
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

    # ── candidates ────────────────────────────────────────────────────────
    # The schema has NO `entry_ref` column; only fields from db.py exist.
    # 一个已验证待 promoted 的候选
    c.execute(
        """INSERT INTO candidates
               (id, purpose_guess, stage, stage_rank, lifecycle,
                result_status, determinism, input_profile,
                branch_identity, context, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "cand-path-b",
            "doc-to-markdown",
            "judged",
            60,
            "verified",
            "success",
            "deterministic",
            "pdf_text",
            '{"normalized_input_family":"pdf_text"}',
            '{"task_id":"t-1","cwd":"/proj/A"}',
            "2026-06-20T10:00:00Z",
        ),
    )
    # 一个已验证但 result_status 非 success（不应出现在 pending 里）
    c.execute(
        """INSERT INTO candidates
               (id, purpose_guess, stage, stage_rank, lifecycle,
                result_status, determinism, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "cand-failed",
            "doc-to-markdown",
            "judged",
            60,
            "verified",
            "error",
            "deterministic",
            "2026-06-20T11:00:00Z",
        ),
    )
    # 一个 lifecycle=raw（不该出现在 pending 里）
    c.execute(
        """INSERT INTO candidates
               (id, purpose_guess, lifecycle, result_status, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (
            "cand-raw",
            "doc-to-markdown",
            "raw",
            "success",
            "2026-06-20T12:00:00Z",
        ),
    )
    # 一个 lifecycle=promoted（不该出现在 pending 里）
    c.execute(
        """INSERT INTO candidates
               (id, purpose_guess, lifecycle, result_status, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (
            "cand-promoted-already",
            "doc-to-markdown",
            "promoted",
            "success",
            "2026-06-20T13:00:00Z",
        ),
    )

    # ── skill ─────────────────────────────────────────────────────────────
    c.execute(
        """INSERT INTO skills(name, purpose, status, visibility)
           VALUES (?, ?, ?, ?)""",
        ("doc-to-markdown", "文档转 markdown", "promoted", "hidden"),
    )
    # 一个 skill 用于 deprecate 测试
    c.execute(
        """INSERT INTO skills(name, purpose, status, visibility)
           VALUES (?, ?, ?, ?)""",
        ("bad-skill", "一个烂工具", "promoted", "invokable_by_id"),
    )

    # ── branches ──────────────────────────────────────────────────────────
    c.execute(
        """INSERT INTO branches(skill_name, key, active_impl_ref, active_version, retained_impls)
           VALUES (?, ?, ?, ?, ?)""",
        ("doc-to-markdown", "pdf", "./branches/old_pdf.py", 1, "[]"),
    )
    c.execute(
        """INSERT INTO branches(skill_name, key, active_impl_ref, active_version, retained_impls)
           VALUES (?, ?, ?, ?, ?)""",
        ("doc-to-markdown", "docx", "./branches/docx.py", 2,
         json.dumps([{"impl_ref": "./branches/docx_v1.py", "version": 1}])),
    )
    # 一个带 retained impls 的复杂 branch
    c.execute(
        """INSERT INTO branches(skill_name, key, active_impl_ref, active_version, retained_impls)
           VALUES (?, ?, ?, ?, ?)""",
        ("doc-to-markdown", "html", "./branches/html.py", 3,
         json.dumps([
             {"impl_ref": "./branches/html_v1.py", "version": 1},
             {"impl_ref": "./branches/html_v2.py", "version": 2},
         ])),
    )

    # ── branch_versions ───────────────────────────────────────────────────
    c.execute(
        """INSERT INTO branch_versions(skill_name, scope, branch_key, version, change, ts)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("doc-to-markdown", "branch", "pdf", 1,
         json.dumps({"change": "initial"}), "2026-06-20T10:00:00Z"),
    )

    # ── quality_rollup ────────────────────────────────────────────────────
    # 低分 skill（不该升级）
    c.execute(
        """INSERT INTO quality_rollup(skill_name, reuse_count, success_rate)
           VALUES (?, ?, ?)""",
        ("doc-to-markdown", 1, 0.5),
    )

    c.commit()
    yield c
    c.close()


# --------------------------------------------------------------------------- #
# pin_path_b
# --------------------------------------------------------------------------- #

class TestPinPathB:
    def test_promotes_candidate(self, conn):
        pin_path_b(conn, "cand-path-b", "人工确认高价值")
        row = conn.execute(
            "SELECT lifecycle FROM candidates WHERE id='cand-path-b'"
        ).fetchone()
        assert row["lifecycle"] == "promoted"

    def test_writes_lineage(self, conn):
        pin_path_b(conn, "cand-path-b", "高价值")
        rows = conn.execute(
            "SELECT kind, subject, detail FROM lineage WHERE kind='promote'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["subject"] == "cand-path-b"
        detail = json.loads(rows[0]["detail"])
        assert detail["reason"] == "高价值"
        assert detail["action"] == "pin_path_b"

    def test_existing_candidate_raises_if_not_found(self, conn):
        with pytest.raises(ValueError, match="not found"):
            pin_path_b(conn, "no-such-candidate", "reason")

    def test_can_pin_any_lifecycle(self, conn):
        pin_path_b(conn, "cand-raw", "从 raw 直接转正")
        row = conn.execute(
            "SELECT lifecycle FROM candidates WHERE id='cand-raw'"
        ).fetchone()
        assert row["lifecycle"] == "promoted"

    def test_multiple_pins_all_write_lineage(self, conn):
        pin_path_b(conn, "cand-raw", "first")
        pin_path_b(conn, "cand-path-b", "second")
        rows = conn.execute(
            "SELECT subject FROM lineage WHERE kind='promote' ORDER BY id"
        ).fetchall()
        subjects = [r["subject"] for r in rows]
        assert subjects == ["cand-raw", "cand-path-b"]

    def test_pin_does_not_affect_other_candidates(self, conn):
        pin_path_b(conn, "cand-path-b", "测试隔离")
        # cand-raw and cand-failed should not be promoted
        for cid in ("cand-raw", "cand-failed"):
            row = conn.execute(
                "SELECT lifecycle FROM candidates WHERE id=?", (cid,)
            ).fetchone()
            assert row["lifecycle"] != "promoted", f"{cid} was wrongly promoted"


# --------------------------------------------------------------------------- #
# resolve_iteration
# --------------------------------------------------------------------------- #

class TestResolveIteration:
    def test_bumps_version(self, conn):
        resolve_iteration(conn, "cand-path-b", "doc-to-markdown", "pdf",
                          "./branches/new_pdf.py")
        branch = conn.execute(
            "SELECT active_version FROM branches WHERE skill_name='doc-to-markdown' AND key='pdf'"
        ).fetchone()
        assert branch["active_version"] == 2  # bumped from 1 to 2

    def test_updates_active_impl_ref(self, conn):
        resolve_iteration(conn, "cand-path-b", "doc-to-markdown", "pdf",
                          "./branches/new_pdf.py")
        branch = conn.execute(
            """SELECT active_impl_ref FROM branches
               WHERE skill_name='doc-to-markdown' AND key='pdf'"""
        ).fetchone()
        assert branch["active_impl_ref"] == "./branches/new_pdf.py"

    def test_moves_old_active_to_retained(self, conn):
        resolve_iteration(conn, "cand-path-b", "doc-to-markdown", "pdf",
                          "./branches/new_pdf.py")
        branch = conn.execute(
            """SELECT retained_impls FROM branches
               WHERE skill_name='doc-to-markdown' AND key='pdf'"""
        ).fetchone()
        retained = json.loads(branch["retained_impls"])
        assert len(retained) == 1
        assert retained[0]["impl_ref"] == "./branches/old_pdf.py"
        assert retained[0]["version"] == 1

    def test_appends_to_existing_retained(self, conn):
        resolve_iteration(conn, "cand-path-b", "doc-to-markdown", "docx",
                          "./branches/new_docx.py")
        branch = conn.execute(
            """SELECT retained_impls, active_version FROM branches
               WHERE skill_name='doc-to-markdown' AND key='docx'"""
        ).fetchone()
        retained = json.loads(branch["retained_impls"])
        assert len(retained) == 2  # original 1 + old active 1
        assert branch["active_version"] == 3  # bumped from 2 to 3

    def test_writes_branch_versions(self, conn):
        resolve_iteration(conn, "cand-path-b", "doc-to-markdown", "pdf",
                          "./branches/new_pdf.py")
        vers = conn.execute(
            """SELECT * FROM branch_versions
               WHERE skill_name='doc-to-markdown' AND branch_key='pdf'
               ORDER BY version"""
        ).fetchall()
        assert len(vers) == 2  # initial (1) + new (2)
        assert vers[1]["version"] == 2
        change = json.loads(vers[1]["change"])
        assert change["change"] == "iteration"
        assert change["candidate_id"] == "cand-path-b"

    def test_writes_lineage(self, conn):
        resolve_iteration(conn, "cand-path-b", "doc-to-markdown", "pdf",
                          "./branches/new_pdf.py")
        rows = conn.execute(
            "SELECT kind, subject, detail FROM lineage WHERE kind='iterate'"
        ).fetchall()
        assert len(rows) == 1
        detail = json.loads(rows[0]["detail"])
        assert detail["candidate_id"] == "cand-path-b"
        assert detail["new_impl"] == "./branches/new_pdf.py"
        assert detail["old_impl"] == "./branches/old_pdf.py"
        assert detail["old_version"] == 1
        assert detail["new_version"] == 2

    def test_raises_if_candidate_not_found(self, conn):
        with pytest.raises(ValueError, match="not found"):
            resolve_iteration(conn, "no-such-cand", "doc-to-markdown", "pdf",
                              "./branches/x.py")

    def test_raises_if_branch_not_found(self, conn):
        with pytest.raises(ValueError, match="not found"):
            resolve_iteration(conn, "cand-path-b", "doc-to-markdown", "no-such-branch",
                              "./branches/x.py")


# --------------------------------------------------------------------------- #
# resolve_keep_both
# --------------------------------------------------------------------------- #

class TestResolveKeepBoth:
    def test_adds_to_retained_without_changing_active(self, conn):
        resolve_keep_both(
            conn, "cand-path-b", "doc-to-markdown", "pdf",
            "./branches/alternative_pdf.py",
        )
        branch = conn.execute(
            """SELECT active_impl_ref, active_version, retained_impls FROM branches
               WHERE skill_name='doc-to-markdown' AND key='pdf'"""
        ).fetchone()
        # active 不变
        assert branch["active_impl_ref"] == "./branches/old_pdf.py"
        assert branch["active_version"] == 1
        # retained 加了新实现
        retained = json.loads(branch["retained_impls"])
        assert len(retained) == 1
        assert retained[0]["impl_ref"] == "./branches/alternative_pdf.py"

    def test_appends_to_existing_retained(self, conn):
        resolve_keep_both(
            conn, "cand-path-b", "doc-to-markdown", "html",
            "./branches/html_v3.py",
        )
        branch = conn.execute(
            "SELECT retained_impls FROM branches WHERE skill_name='doc-to-markdown' AND key='html'"
        ).fetchone()
        retained = json.loads(branch["retained_impls"])
        assert len(retained) == 3
        refs = [r["impl_ref"] for r in retained]
        assert "./branches/html_v3.py" in refs

    def test_does_not_duplicate_same_impl_ref(self, conn):
        resolve_keep_both(
            conn, "cand-path-b", "doc-to-markdown", "html",
            "./branches/html_v1.py",  # already in retained
        )
        branch = conn.execute(
            "SELECT retained_impls FROM branches WHERE skill_name='doc-to-markdown' AND key='html'"
        ).fetchone()
        retained = json.loads(branch["retained_impls"])
        assert len(retained) == 2  # no duplicate

    def test_writes_branch_versions(self, conn):
        resolve_keep_both(
            conn, "cand-path-b", "doc-to-markdown", "pdf",
            "./branches/alt.py",
        )
        vers = conn.execute(
            """SELECT * FROM branch_versions
               WHERE skill_name='doc-to-markdown' AND branch_key='pdf'
               AND scope='branch' ORDER BY id"""
        ).fetchall()
        assert len(vers) == 2  # initial 1 + keep_both
        change = json.loads(vers[1]["change"])
        assert change["change"] == "keep_both"
        assert change["new_impl"] == "./branches/alt.py"

    def test_writes_lineage(self, conn):
        resolve_keep_both(
            conn, "cand-path-b", "doc-to-markdown", "pdf",
            "./branches/alt.py",
        )
        rows = conn.execute(
            "SELECT kind, subject, detail FROM lineage WHERE kind='retain_impl'"
        ).fetchall()
        assert len(rows) == 1
        detail = json.loads(rows[0]["detail"])
        assert detail["action"] == "keep_both"
        assert detail["new_impl"] == "./branches/alt.py"

    def test_raises_if_branch_not_found(self, conn):
        with pytest.raises(ValueError, match="not found"):
            resolve_keep_both(
                conn, "cand-path-b", "doc-to-markdown", "no-such-branch",
                "./branches/x.py",
            )


# --------------------------------------------------------------------------- #
# deprecate
# --------------------------------------------------------------------------- #

class TestDeprecate:
    def test_sets_status_deprecated(self, conn):
        deprecate(conn, "bad-skill", "质量太差")
        row = conn.execute(
            "SELECT status FROM skills WHERE name='bad-skill'"
        ).fetchone()
        assert row["status"] == "deprecated"

    def test_sets_visibility_hidden(self, conn):
        deprecate(conn, "bad-skill", "质量太差")
        row = conn.execute(
            "SELECT visibility FROM skills WHERE name='bad-skill'"
        ).fetchone()
        assert row["visibility"] == "hidden"

    def test_writes_lineage(self, conn):
        deprecate(conn, "bad-skill", "不再维护")
        rows = conn.execute(
            "SELECT kind, subject, detail FROM lineage WHERE kind='deprecate'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["subject"] == "bad-skill"
        detail = json.loads(rows[0]["detail"])
        assert detail["reason"] == "不再维护"
        assert detail["old_status"] == "promoted"
        assert detail["old_visibility"] == "invokable_by_id"

    def test_raises_if_skill_not_found(self, conn):
        with pytest.raises(ValueError, match="not found"):
            deprecate(conn, "no-such-skill", "不存在")

    def test_deprecate_good_skill(self, conn):
        deprecate(conn, "doc-to-markdown", "准备重写")
        row = conn.execute(
            "SELECT status, visibility FROM skills WHERE name='doc-to-markdown'"
        ).fetchone()
        assert row["status"] == "deprecated"
        assert row["visibility"] == "hidden"


# --------------------------------------------------------------------------- #
# auto_upgrade_quality
# --------------------------------------------------------------------------- #

class TestAutoUpgradeQuality:
    def test_low_score_not_upgraded(self, conn):
        # doc-to-markdown has reuse=1, success=0.5 -- below threshold
        upgraded = auto_upgrade_quality(conn)
        assert "doc-to-markdown" not in upgraded
        row = conn.execute(
            "SELECT visibility FROM skills WHERE name='doc-to-markdown'"
        ).fetchone()
        assert row["visibility"] == "hidden"

    def test_upgrades_to_searchable_at_3_reuse_08(self, conn):
        conn.execute(
            "UPDATE quality_rollup SET reuse_count=3, success_rate=0.85 WHERE skill_name='doc-to-markdown'"
        )
        upgraded = auto_upgrade_quality(conn)
        assert "doc-to-markdown" in upgraded
        row = conn.execute(
            "SELECT visibility FROM skills WHERE name='doc-to-markdown'"
        ).fetchone()
        assert row["visibility"] == "searchable"

    def test_upgrades_to_invokable_at_5_reuse_09(self, conn):
        conn.execute(
            "UPDATE quality_rollup SET reuse_count=5, success_rate=0.95 WHERE skill_name='doc-to-markdown'"
        )
        upgraded = auto_upgrade_quality(conn)
        assert "doc-to-markdown" in upgraded
        row = conn.execute(
            "SELECT visibility FROM skills WHERE name='doc-to-markdown'"
        ).fetchone()
        assert row["visibility"] == "invokable_by_id"

    def test_never_upgrades_to_mcp_exposed(self, conn):
        # Even with very high quality, should never auto-upgrade to mcp_exposed
        conn.execute(
            "UPDATE quality_rollup SET reuse_count=100, success_rate=1.0 WHERE skill_name='doc-to-markdown'"
        )
        upgraded = auto_upgrade_quality(conn)
        assert "doc-to-markdown" in upgraded
        row = conn.execute(
            "SELECT visibility FROM skills WHERE name='doc-to-markdown'"
        ).fetchone()
        # Should only reach invokable_by_id, never mcp_exposed
        assert row["visibility"] == "invokable_by_id"
        assert row["visibility"] != "mcp_exposed"

    def test_invokable_stays_invokable(self, conn):
        """Already invokable skill should not be downgraded or changed."""
        conn.execute(
            "UPDATE skills SET visibility='invokable_by_id' WHERE name='doc-to-markdown'"
        )
        conn.execute(
            "UPDATE quality_rollup SET reuse_count=5, success_rate=0.95 WHERE skill_name='doc-to-markdown'"
        )
        upgraded = auto_upgrade_quality(conn)
        assert "doc-to-markdown" not in upgraded
        row = conn.execute(
            "SELECT visibility FROM skills WHERE name='doc-to-markdown'"
        ).fetchone()
        assert row["visibility"] == "invokable_by_id"

    def test_mcp_exposed_stays_mcp_exposed(self, conn):
        """Already mcp_exposed should not be touched."""
        conn.execute(
            "UPDATE skills SET visibility='mcp_exposed' WHERE name='doc-to-markdown'"
        )
        conn.execute(
            "UPDATE quality_rollup SET reuse_count=5, success_rate=0.95 WHERE skill_name='doc-to-markdown'"
        )
        upgraded = auto_upgrade_quality(conn)
        assert "doc-to-markdown" not in upgraded
        row = conn.execute(
            "SELECT visibility FROM skills WHERE name='doc-to-markdown'"
        ).fetchone()
        assert row["visibility"] == "mcp_exposed"

    def test_no_quality_row_skipped(self, conn):
        """Skills without quality_rollup row are not upgraded."""
        conn.execute(
            """INSERT INTO skills(name, purpose, status, visibility)
               VALUES ('no-quality-skill', '无质量数据', 'promoted', 'hidden')"""
        )
        upgraded = auto_upgrade_quality(conn)
        assert "no-quality-skill" not in upgraded

    def test_returns_empty_list_when_none_upgraded(self, conn):
        upgraded = auto_upgrade_quality(conn)
        assert isinstance(upgraded, list)
        assert len(upgraded) == 0

    def test_returns_list_of_upgraded_names(self, conn):
        conn.execute(
            "UPDATE quality_rollup SET reuse_count=5, success_rate=0.95 WHERE skill_name='doc-to-markdown'"
        )
        upgraded = auto_upgrade_quality(conn)
        assert upgraded == ["doc-to-markdown"]

    def test_writes_lineage_for_upgrade(self, conn):
        conn.execute(
            "UPDATE quality_rollup SET reuse_count=5, success_rate=0.95 WHERE skill_name='doc-to-markdown'"
        )
        auto_upgrade_quality(conn)
        rows = conn.execute(
            "SELECT kind, subject, detail FROM lineage WHERE kind='auto_upgrade'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["subject"] == "doc-to-markdown"
        detail = json.loads(rows[0]["detail"])
        assert detail["from"] == "hidden"
        assert detail["to"] == "invokable_by_id"
        assert detail["reuse_count"] == 5
        assert abs(detail["success_rate"] - 0.95) < 0.001

    def test_barely_below_threshold_not_upgraded(self, conn):
        conn.execute(
            "UPDATE quality_rollup SET reuse_count=2, success_rate=0.79 WHERE skill_name='doc-to-markdown'"
        )
        upgraded = auto_upgrade_quality(conn)
        assert len(upgraded) == 0

    def test_exact_threshold_upgrades(self, conn):
        conn.execute(
            "UPDATE quality_rollup SET reuse_count=3, success_rate=0.8 WHERE skill_name='doc-to-markdown'"
        )
        upgraded = auto_upgrade_quality(conn)
        assert "doc-to-markdown" in upgraded
        row = conn.execute(
            "SELECT visibility FROM skills WHERE name='doc-to-markdown'"
        ).fetchone()
        assert row["visibility"] == "searchable"

    def test_multiple_skills_upgrade_independently(self, conn):
        """Multiple skills at different levels should each upgrade correctly."""
        # Add second skill with high quality
        conn.execute(
            """INSERT INTO skills(name, purpose, status, visibility)
               VALUES ('another-good', '好工具', 'promoted', 'hidden')"""
        )
        conn.execute(
            """INSERT INTO quality_rollup(skill_name, reuse_count, success_rate)
               VALUES ('another-good', 6, 0.92)"""
        )
        # Original skill at low quality
        conn.execute(
            "UPDATE quality_rollup SET reuse_count=1, success_rate=0.5 WHERE skill_name='doc-to-markdown'"
        )
        upgraded = auto_upgrade_quality(conn)
        assert "another-good" in upgraded
        assert "doc-to-markdown" not in upgraded


# --------------------------------------------------------------------------- #
# list_pending（cli_pending）
# --------------------------------------------------------------------------- #

class TestListPending:
    def test_returns_verified_success_candidates(self, conn):
        result = list_pending(conn)
        ids = [r["id"] for r in result]
        assert "cand-path-b" in ids

    def test_excludes_non_verified_lifecycle(self, conn):
        result = list_pending(conn)
        ids = [r["id"] for r in result]
        assert "cand-raw" not in ids
        assert "cand-promoted-already" not in ids

    def test_excludes_failed_result_status(self, conn):
        result = list_pending(conn)
        ids = [r["id"] for r in result]
        assert "cand-failed" not in ids

    def test_returns_required_fields(self, conn):
        result = list_pending(conn)
        assert len(result) >= 1
        required = {
            "id", "purpose_guess", "input_profile",
            "stage", "lifecycle", "result_status", "determinism",
            "created_at", "updated_at",
        }
        for row in result:
            for field in required:
                assert field in row, f"missing field: {field}"

    def test_returns_list_of_dicts(self, conn):
        result = list_pending(conn)
        assert isinstance(result, list)
        assert all(isinstance(r, dict) for r in result)

    def test_empty_when_no_verified_success(self, conn):
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        db.apply_schema(c)
        result = list_pending(c)
        assert result == []
        c.close()

    def test_excludes_rejected_pipeline_status(self, conn):
        """复审四次 P2-2：verified+success 但 pipeline_status='rejected'（中后段失败）
        不得进入 pending。"""
        conn.execute(
            """INSERT INTO candidates
                   (id, purpose_guess, stage, stage_rank, lifecycle,
                    result_status, pipeline_status, determinism, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("cand-rejected-verified", "doc-to-markdown", "output_gated", 40,
             "verified", "success", "rejected", "deterministic", "2026-07-04T00:00:00Z"),
        )
        conn.commit()
        ids = {r["id"] for r in list_pending(conn)}
        assert "cand-rejected-verified" not in ids

    def test_includes_deferred_ambiguous(self, conn):
        """deferred（ambiguous 待人工 pin）仍应进入 pending。"""
        conn.execute(
            """INSERT INTO candidates
                   (id, purpose_guess, stage, stage_rank, lifecycle,
                    result_status, pipeline_status, deferred_reason, determinism, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("cand-ambiguous", "doc-to-markdown", "composed", 80,
             "verified", "success", "deferred", "ambiguous", "deterministic", "2026-07-04T00:00:01Z"),
        )
        conn.commit()
        ids = {r["id"] for r in list_pending(conn)}
        assert "cand-ambiguous" in ids


# --------------------------------------------------------------------------- #
# get_review（cli_pending）
# --------------------------------------------------------------------------- #

class TestGetReview:
    def test_returns_candidate_fields(self, conn):
        result = get_review(conn, "cand-path-b")
        assert result["id"] == "cand-path-b"
        assert result["purpose_guess"] == "doc-to-markdown"
        assert result["lifecycle"] == "verified"
        assert result["result_status"] == "success"

    def test_returns_related_skills(self, conn):
        result = get_review(conn, "cand-path-b")
        assert "related_skills" in result
        assert isinstance(result["related_skills"], list)
        # purpose_guess == "doc-to-markdown" matches the skill name
        assert len(result["related_skills"]) >= 1
        assert result["related_skills"][0]["name"] == "doc-to-markdown"

    def test_returns_contract_signatures(self, conn):
        result = get_review(conn, "cand-path-b")
        assert "contract_signatures" in result
        assert isinstance(result["contract_signatures"], list)

    def test_returns_empty_dict_for_nonexistent(self, conn):
        result = get_review(conn, "no-such-candidate")
        assert result == {}

    def test_returns_dict_type(self, conn):
        result = get_review(conn, "cand-path-b")
        assert isinstance(result, dict)

    def test_contract_signatures_has_expected_fields(self, conn):
        result = get_review(conn, "cand-path-b")
        expected = {
            "id", "signature_hash", "contract_json",
            "branch_identity_json", "schema_version", "created_at",
        }
        for sig in result.get("contract_signatures", []):
            for field in expected:
                assert field in sig, f"missing field: {field}"
