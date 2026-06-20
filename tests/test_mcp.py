"""M6 — MCP server + warm-start 集成测试。

用内存 SQLite + apply_schema 构建隔离环境，覆盖：
  - list_promoted_skills：visibility 过滤
  - search_capability：purpose/tags/name 匹配
  - describe_capability：含 contract 详情
  - warmstart_lookup：排除 R_miss 坏项
  - record_usage：写 usage + 更新 quality_rollup
  - check_r_miss：全 scope 复合命中（不宽匹配）
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from src.distiller.db import apply_schema
from src.distiller.mcp_server import (
    describe_capability,
    list_promoted_skills,
    run_capability,
    search_capability,
)
from src.distiller.warmstart import (
    check_r_miss,
    record_usage,
    warmstart_lookup,
)


# =================================================================== #
# Fixtures
# =================================================================== #

@pytest.fixture
def conn() -> sqlite3.Connection:
    """内存 SQLite，apply_schema 后插入样本数据。"""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    apply_schema(c)

    _seed(c)
    return c


def _seed(c: sqlite3.Connection) -> None:
    """插入跨测试样本数据。"""
    # --- skills ---
    skills = [
        (
            "doc-to-markdown",
            "文档转 Markdown",
            "需要把文档转成 Markdown 时",
            json.dumps({"input": {"file": "path"}, "output": {"markdown": "string"}}),
            json.dumps(["convert", "markdown", "document"]),
            "promoted",
            "mcp_exposed",
            json.dumps({"reuse_count": 5, "success_rate": 0.95}),
        ),
        (
            "code-analyzer",
            "代码结构分析",
            "需要分析代码结构时",
            json.dumps({"input": {"code": "string"}, "output": {"analysis": "object"}}),
            json.dumps(["analyze", "code"]),
            "promoted",
            "invokable_by_id",
            json.dumps({"reuse_count": 3, "success_rate": 0.80}),
        ),
        (
            "hidden-skill",
            "隐藏内部技能",
            "内部使用",
            json.dumps({"input": {}, "output": {}}),
            json.dumps(["internal"]),
            "promoted",
            "hidden",
            None,
        ),
        (
            "deprecated-skill",
            "已废弃技能",
            "不再使用",
            json.dumps({"input": {}, "output": {}}),
            json.dumps(["deprecated"]),
            "deprecated",
            "mcp_exposed",
            None,
        ),
    ]
    for row in skills:
        name, purpose, when_to_use, contract, tags, status, visibility, quality = row
        c.execute(
            """
            INSERT INTO skills
                (name, purpose, when_to_use, contract, tags, status, visibility, quality, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, '2026-06-20T12:00:00Z')
            """,
            (name, purpose, when_to_use, contract, tags, status, visibility, quality),
        )

    # --- branches ---
    branches = [
        ("doc-to-markdown", "pdf", "impl/pdf.py"),
        ("doc-to-markdown", "docx", "impl/docx.py"),
        ("code-analyzer", "python", "impl/py_analyzer.py"),
        ("hidden-skill", "main", "impl/hidden.py"),
        ("deprecated-skill", "legacy", "impl/legacy.py"),
    ]
    for skill_name, key, impl_ref in branches:
        c.execute(
            """
            INSERT INTO branches (skill_name, key, active_impl_ref, active_version,
                                  retained_impls, is_thin_wrapper)
            VALUES (?, ?, ?, 1, ?, 0)
            """,
            (skill_name, key, impl_ref,
             json.dumps([{"impl_ref": impl_ref, "version": 1}])),
        )

    # --- contract_signatures ---
    sigs = [
        (
            "skill", "doc-to-markdown", "doc-to-markdown", "pdf",
            json.dumps({
                "purpose_summary": "PDF 文档转 Markdown",
                "input_media_types": ["application/pdf"],
            }),
        ),
        (
            "skill", "doc-to-markdown", "doc-to-markdown", "docx",
            json.dumps({
                "purpose_summary": "Word 文档转 Markdown",
                "input_media_types": [
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ],
            }),
        ),
        (
            "skill", "code-analyzer", "code-analyzer", "python",
            json.dumps({
                "purpose_summary": "Python 代码结构分析",
                "input_media_types": ["text/x-python"],
            }),
        ),
        (
            "skill", "hidden-skill", "hidden-skill", "main",
            json.dumps({"purpose_summary": "内部隐藏处理", "input_media_types": []}),
        ),
    ]
    for ent_type, ent_id, sname, bkey, cjson in sigs:
        c.execute(
            """
            INSERT INTO contract_signatures
                (entity_type, entity_id, skill_name, branch_key, contract_json, schema_version, created_at)
            VALUES (?, ?, ?, ?, ?, 1, '2026-06-20T12:00:00Z')
            """,
            (ent_type, ent_id, sname, bkey, cjson),
        )

    # --- r_miss：doc-to-markdown/pdf 有坏记录 ---
    c.execute(
        """
        INSERT INTO r_miss (skill_name, branch_key, contract_slice, version,
                            env_fingerprint, failure_class, ts)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("doc-to-markdown", "pdf", "default", 1, "env-a", "timeout",
         "2026-06-20T13:00:00Z"),
    )

    # --- quality_rollup ---
    for sname, reuse, rate in [
        ("doc-to-markdown", 5, 0.95),
        ("code-analyzer", 3, 0.80),
    ]:
        c.execute(
            """
            INSERT INTO quality_rollup (skill_name, reuse_count, success_rate, last_used)
            VALUES (?, ?, ?, '2026-06-20T12:00:00Z')
            """,
            (sname, reuse, rate),
        )

    c.commit()


# =================================================================== #
# Tests: list_promoted_skills
# =================================================================== #

class TestListPromotedSkills:
    def test_returns_only_promoted_visible_skills(self, conn):
        """只返回 promoted + mcp_exposed/invokable_by_id，不出 hidden / deprecated。"""
        result = list_promoted_skills(conn)
        names = {r["name"] for r in result}
        assert "doc-to-markdown" in names
        assert "code-analyzer" in names
        assert "hidden-skill" not in names
        assert "deprecated-skill" not in names

    def test_returns_required_fields(self, conn):
        """每条记录含 name/purpose/contract/when_to_use。"""
        result = list_promoted_skills(conn)
        for r in result:
            assert "name" in r
            assert "purpose" in r
            assert "contract" in r
            assert "when_to_use" in r

    def test_contract_is_dict(self, conn):
        """contract 字段已被解析为 dict。"""
        for r in list_promoted_skills(conn):
            assert isinstance(r["contract"], dict)

    def test_empty_when_no_promoted(self, conn):
        """没有 promoted skill 时返回空列表。"""
        conn.execute("UPDATE skills SET status = 'deprecated'")
        conn.commit()
        assert list_promoted_skills(conn) == []


# =================================================================== #
# Tests: search_capability
# =================================================================== #

class TestSearchCapability:
    def test_search_by_purpose_summary(self, conn):
        """按 purpose_summary 命中。"""
        result = search_capability(conn, "PDF")
        names = {r["name"] for r in result}
        assert "doc-to-markdown" in names

    def test_search_by_tags(self, conn):
        """按 tags 命中。"""
        result = search_capability(conn, "analyze")
        names = {r["name"] for r in result}
        assert "code-analyzer" in names

    def test_search_by_name(self, conn):
        """按 name 命中。"""
        result = search_capability(conn, "code")
        names = {r["name"] for r in result}
        assert "code-analyzer" in names

    def test_excludes_hidden(self, conn):
        """visibility=hidden 不出现在搜索结果中。"""
        result = search_capability(conn, "hidden")
        names = {r["name"] for r in result}
        assert "hidden-skill" not in names

    def test_excludes_deprecated(self, conn):
        """status=deprecated 不出现在搜索结果中。"""
        result = search_capability(conn, "deprecated")
        names = {r["name"] for r in result}
        assert "deprecated-skill" not in names

    def test_no_match_returns_empty(self, conn):
        """搜索无匹配词时返回空列表。"""
        assert search_capability(conn, "xyznonexistent") == []


# =================================================================== #
# Tests: describe_capability
# =================================================================== #

class TestDescribeCapability:
    def test_returns_full_detail(self, conn):
        """返回含 contract/branches/contract_signatures 的完整详情。"""
        detail = describe_capability(conn, "doc-to-markdown")
        assert detail
        assert detail["name"] == "doc-to-markdown"
        assert isinstance(detail["contract"], dict)
        assert "branches" in detail
        assert "contract_signatures" in detail
        assert len(detail["branches"]) == 2  # pdf + docx
        assert len(detail["contract_signatures"]) == 2

    def test_contract_signatures_parsed(self, conn):
        """contract_signatures 中的 contract_json 被解析为 dict。"""
        detail = describe_capability(conn, "doc-to-markdown")
        for cs in detail["contract_signatures"]:
            assert isinstance(cs["contract_json"], dict)

    def test_not_found_returns_empty(self, conn):
        """不存在的 skill 返回 {}。"""
        assert describe_capability(conn, "does-not-exist") == {}

    def test_contract_is_dict(self, conn):
        """contract 字段为 dict。"""
        detail = describe_capability(conn, "code-analyzer")
        assert isinstance(detail["contract"], dict)


# =================================================================== #
# Tests: run_capability
# =================================================================== #

class TestRunCapability:
    def test_returns_contract_and_active_branch(self, conn):
        """返回 contract + active_branch 含 impl_ref。"""
        result = run_capability(conn, "doc-to-markdown")
        assert result["name"] == "doc-to-markdown"
        assert isinstance(result["contract"], dict)
        assert "active_branch" in result
        assert result["active_branch"]["active_impl_ref"] == "impl/pdf.py"

    def test_not_found_returns_empty(self, conn):
        """不存在的 skill 返回 {}。"""
        assert run_capability(conn, "does-not-exist") == {}

    def test_passes_inputs_through(self, conn):
        """传入的 inputs 保留在返回中。"""
        result = run_capability(conn, "doc-to-markdown", file="test.pdf")
        assert result["inputs"] == {"file": "test.pdf"}


# =================================================================== #
# Tests: warmstart_lookup
# =================================================================== #

class TestWarmstartLookup:
    def test_excludes_r_miss_items(self, conn):
        """doc-to-markdown/pdf 有 r_miss 记录，搜索相关词时应当被排除。"""
        result = warmstart_lookup(conn, "PDF", [])
        names = {r["skill_name"] for r in result}
        # "PDF" would match doc-to-markdown, but it has r_miss
        assert "doc-to-markdown" not in names

    def test_returns_clean_items(self, conn):
        """code-analyzer 无 r_miss，应当返回。"""
        result = warmstart_lookup(conn, "代码", [])
        names = {r["skill_name"] for r in result}
        assert "code-analyzer" in names

    def test_matches_by_input_media_types(self, conn):
        """按 input_media_types 匹配。"""
        # code-analyzer's contract has input_media_types=["text/x-python"]
        result = warmstart_lookup(conn, "", ["text/x-python"], top_n=10)
        names = {r["skill_name"] for r in result}
        assert "code-analyzer" in names

    def test_returns_top_n(self, conn):
        """top_n 参数生效。"""
        result = warmstart_lookup(conn, "", [], top_n=0)
        assert len(result) == 0

    def test_empty_when_no_promoted(self, conn):
        """无 promoted skill 时返回空列表。"""
        conn.execute("UPDATE skills SET status = 'deprecated'")
        conn.commit()
        assert warmstart_lookup(conn, "PDF", []) == []

    def test_sorts_by_quality(self, conn):
        """按 quality 降序排列。"""
        # Insert a promoted skill with high quality
        conn.execute(
            """
            INSERT INTO skills (name, purpose, status, visibility, created_at)
            VALUES ('high-quality', '高质量转换', 'promoted', 'mcp_exposed', '2026-06-20T12:00:00Z')
            """,
        )
        conn.execute(
            """
            INSERT INTO contract_signatures
                (entity_type, entity_id, skill_name, branch_key, contract_json, schema_version, created_at)
            VALUES ('skill', 'high-quality', 'high-quality', 'main',
                    '{"purpose_summary": "高质量的文档转换", "input_media_types": ["application/pdf"]}',
                    1, '2026-06-20T12:00:00Z')
            """,
        )
        conn.execute(
            """
            INSERT INTO quality_rollup (skill_name, reuse_count, success_rate, last_used)
            VALUES ('high-quality', 10, 0.99, '2026-06-20T12:00:00Z')
            """,
        )
        conn.commit()

        result = warmstart_lookup(conn, "文档", [])
        assert len(result) >= 1
        # highest quality should be first
        assert result[0]["skill_name"] == "high-quality"


# =================================================================== #
# Tests: check_r_miss
# =================================================================== #

class TestCheckRMiss:
    def test_exact_match_returns_true(self, conn):
        """全 scope 匹配时返回 True。"""
        assert check_r_miss(conn, "doc-to-markdown", "pdf", "default", 1, "env-a") is True

    def test_wrong_branch_no_match(self, conn):
        """branch_key 不同则不匹配。"""
        assert check_r_miss(conn, "doc-to-markdown", "docx", "default", 1, "env-a") is False

    def test_wrong_skill_no_match(self, conn):
        """skill_name 不同则不匹配。"""
        assert check_r_miss(conn, "code-analyzer", "pdf", "default", 1, "env-a") is False

    def test_wrong_version_no_match(self, conn):
        """version 不同则不匹配。"""
        assert check_r_miss(conn, "doc-to-markdown", "pdf", "default", 2, "env-a") is False

    def test_wrong_env_no_match(self, conn):
        """env_fingerprint 不同则不匹配。"""
        assert check_r_miss(conn, "doc-to-markdown", "pdf", "default", 1, "env-b") is False

    def test_partial_contract_slice_no_match(self, conn):
        """contract_slice 不同则不匹配。"""
        assert check_r_miss(conn, "doc-to-markdown", "pdf", "other", 1, "env-a") is False


# =================================================================== #
# Tests: record_usage
# =================================================================== #

class TestRecordUsage:
    def test_inserts_usage_event(self, conn):
        """INSERT usage_events 记录。"""
        record_usage(conn, "doc-to-markdown", "pdf", "success", warmstart_hit=True)
        rows = conn.execute(
            "SELECT * FROM usage_events WHERE skill_name = ?", ("doc-to-markdown",),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["status"] == "success"
        assert rows[0]["warmstart_hit"] == 1

    def test_updates_quality_rollup(self, conn):
        """UPSERT quality_rollup 更新计数和成功率。"""
        # 先设一个 quality baseline
        record_usage(conn, "code-analyzer", "python", "success")
        q = conn.execute(
            "SELECT reuse_count, success_rate FROM quality_rollup WHERE skill_name = ?",
            ("code-analyzer",),
        ).fetchone()
        assert q["reuse_count"] == 4  # original 3 + 1
        assert q["success_rate"] > 0  # recalculated

    def test_tracks_failure_rate(self, conn):
        """多次调用正确计算成功率和复用计数。"""
        record_usage(conn, "code-analyzer", "python", "success")
        record_usage(conn, "code-analyzer", "python", "error")
        q = conn.execute(
            "SELECT reuse_count, success_rate FROM quality_rollup WHERE skill_name = ?",
            ("code-analyzer",),
        ).fetchone()
        # original 3 + 2 new = 5 reuse_count
        # original success count unknown from fixtures, but we can check the rate
        assert q["reuse_count"] == 5  # 3 original + 2 new
        # Check success_rate is between 0 and 1
        assert 0 < q["success_rate"] < 1

    def test_first_usage_creates_rollup(self, conn):
        """新 skill 首次调用创建 quality_rollup 行。"""
        # hidden-skill has no quality_rollup
        record_usage(conn, "hidden-skill", "main", "success")
        q = conn.execute(
            "SELECT * FROM quality_rollup WHERE skill_name = ?", ("hidden-skill",),
        ).fetchone()
        assert q is not None
        assert q["reuse_count"] == 1
        assert q["success_rate"] == 1.0
