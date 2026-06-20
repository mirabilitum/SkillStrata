"""M4+M5 契约引擎集成测试。

覆盖:
  - extract_contract 产出合法 ContractSignature（含 behavior_signature）
  - store_contract 正确写入 contract_signatures 表
  - find_nearest SQLite 穷举近邻检索
  - judge_purpose 对同 input_type 判 same_purpose，不同判 different_purpose
  - classify 对 different_purpose 判 new_skill，对 same_branch 判 iteration/duplicate
  - compose_new_skill 产出含 active_impl_ref + retained_impls 的 SkillManifest
  - add_branch 添加第二个分支
  - apply_iteration 版本 +1 且旧入 retained
  - promote_shared 简化检测
"""
from __future__ import annotations

import sqlite3

from distiller.contracts import (
    Artifact,
    BehaviorSignature,
    Candidate,
    ContractSignature,
    ExecContext,
    ImplRef,
)
from distiller.contract_extract import extract_contract, find_nearest, store_contract
from distiller.classify import classify, judge_purpose
from distiller.composer import (
    add_branch,
    apply_iteration,
    compose_new_skill,
    promote_shared,
)
from distiller.db import apply_schema


# ------------------------------------------------------------------ #
# helpers
# ------------------------------------------------------------------ #


def _memory_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    apply_schema(conn)
    return conn


def _make_candidate(purpose: str = "document-to-markdown") -> Candidate:
    return Candidate(
        id="cand-1",
        purpose_guess=purpose,
        entry_ref="conv.py",
        input_artifacts=[
            Artifact(path="a.pdf", media_type="application/pdf"),
        ],
        output_artifacts=[
            Artifact(path="a.md", media_type="text/markdown"),
        ],
        branch_identity={
            "normalized_input_family": "pdf_text",
            "input_mode": "single_file",
        },
        input_profile="pdf_text",
        determinism="deterministic",
        code_snapshot_ref="artifacts/cand-1/snapshot.py",
        context=ExecContext(task_id="t-1", cwd="/proj/A", session_id="s-1"),
    )


def _make_behavior() -> BehaviorSignature:
    return BehaviorSignature(
        markdown_valid=True,
        assets_emitted=True,
        image_ref_coverage=1.0,
        heading_preservation=1.0,
        content_coverage_grade="A",
        table_render_mode="kv_list",
        key_value_rendering=True,
        is_thin_wrapper=False,
    )


# ================================================================== #
# M4 — 契约抽取
# ================================================================== #


class TestExtractContract:
    """契约签名抽取（契约引擎设计 §3）。"""

    def test_extract_contract_produces_valid_signature(self):
        """基础：输入输出 + purpose + behavior + signature_hash 齐全。"""
        candidate = _make_candidate()
        behavior = _make_behavior()

        sig = extract_contract(candidate, behavior)

        assert isinstance(sig, ContractSignature)
        assert "application/pdf" in sig.input_media_types
        assert "text/markdown" in sig.output_types
        assert sig.purpose_summary == "document-to-markdown"
        assert sig.branch_identity.get("normalized_input_family") == "pdf_text"

        # behavior_signature 连带
        assert sig.behavior_signature is not None
        assert sig.behavior_signature.markdown_valid is True
        assert sig.behavior_signature.content_coverage_grade == "A"

        # signature_hash = sha256 hex（64 字符）
        assert sig.signature_hash != ""
        assert len(sig.signature_hash) == 64

    def test_extract_contract_without_artifacts(self):
        """无 input/output artifacts → 空列表，不报错。"""
        cand = Candidate(id="cand-empty", purpose_guess="test")
        sig = extract_contract(cand, BehaviorSignature())
        assert sig.input_media_types == []
        assert sig.output_types == []
        assert sig.signature_hash != ""

    def test_extract_contract_deterministic_hash(self):
        """相同输入 → 相同 signature_hash。"""
        candidate = _make_candidate()
        behavior = _make_behavior()

        sig1 = extract_contract(candidate, behavior)
        sig2 = extract_contract(candidate, behavior)

        assert sig1.signature_hash == sig2.signature_hash


class TestStoreContract:
    """contract_signatures 表写入。"""

    def test_store_and_retrieve(self):
        conn = _memory_db()
        candidate = _make_candidate()
        behavior = _make_behavior()
        sig = extract_contract(candidate, behavior)

        row_id = store_contract(conn, "candidate", candidate.id, sig)
        assert row_id > 0

        row = conn.execute(
            "SELECT * FROM contract_signatures WHERE id = ?", (row_id,)
        ).fetchone()
        assert row is not None
        assert row["entity_type"] == "candidate"
        assert row["entity_id"] == "cand-1"
        assert row["signature_hash"] == sig.signature_hash
        assert row["contract_json"] is not None
        assert row["behavior_signature_json"] is not None

    def test_store_with_skill_context(self):
        """写入时带 skill_name / branch_key。"""
        conn = _memory_db()
        sig = ContractSignature(
            input_media_types=["application/pdf"],
            purpose_summary="test",
            signature_hash="h1",
        )
        row_id = store_contract(
            conn, "skill", "doc-to-markdown", sig,
            skill_name="doc-to-markdown", branch_key="pdf",
        )
        assert row_id > 0
        row = conn.execute(
            "SELECT skill_name, branch_key FROM contract_signatures WHERE id = ?",
            (row_id,),
        ).fetchone()
        assert row["skill_name"] == "doc-to-markdown"
        assert row["branch_key"] == "pdf"


class TestFindNearest:
    """SQLite 穷举近邻检索（MVP 回退）。"""

    def test_find_nearest_returns_matching(self):
        conn = _memory_db()

        # 已有的 skill 级契约
        existing_sig = ContractSignature(
            input_media_types=["application/pdf"],
            purpose_summary="document to markdown conversion",
            signature_hash="existing-hash",
        )
        store_contract(
            conn, "skill", "doc-to-markdown", existing_sig,
            skill_name="doc-to-markdown", branch_key="pdf",
        )

        # 新 candidate
        candidate = _make_candidate()
        sig = extract_contract(candidate, _make_behavior())

        nearest = find_nearest(conn, sig)
        assert len(nearest) >= 1
        assert nearest[0]["skill_name"] == "doc-to-markdown"
        assert nearest[0]["branch_key"] == "pdf"

    def test_find_nearest_empty_when_no_match(self):
        conn = _memory_db()

        # 不同 input type 的契约
        sig = ContractSignature(
            input_media_types=["image/png"],
            purpose_summary="image resize",
            signature_hash="img-hash",
        )
        store_contract(conn, "skill", "image-resize", sig,
                       skill_name="image-resize")

        # 新 candidate（pdf）
        candidate = _make_candidate()
        new_sig = extract_contract(candidate, _make_behavior())

        nearest = find_nearest(conn, new_sig)
        assert len(nearest) == 0

    def test_find_nearest_returns_empty_for_no_input_media(self):
        conn = _memory_db()
        sig = ContractSignature(
            input_media_types=[],
            purpose_summary="test",
        )
        nearest = find_nearest(conn, sig)
        assert nearest == []


# ================================================================== #
# M4+M5 — 目的判同 + 三选一
# ================================================================== #


class TestJudgePurpose:
    """规则版目的判同（无 LLM 回退）。"""

    def test_judge_purpose_same_purpose(self):
        """同 input_media_type + 同目的关键词 → same_purpose_new_branch。"""
        conn = _memory_db()

        existing_sig = ContractSignature(
            input_media_types=["application/pdf"],
            purpose_summary="document to markdown conversion",
            signature_hash="hash-1",
        )
        store_contract(conn, "skill", "doc-to-markdown", existing_sig,
                       skill_name="doc-to-markdown", branch_key="pdf")

        candidate = _make_candidate()
        sig = extract_contract(candidate, _make_behavior())
        nearest = find_nearest(conn, sig)
        result = judge_purpose(candidate, sig, nearest)

        assert result["relation"] == "same_purpose_new_branch"
        assert result["target_skill"] == "doc-to-markdown"

    def test_judge_purpose_new_skill(self):
        """无重叠 input_media_type → different_purpose。"""
        conn = _memory_db()

        existing_sig = ContractSignature(
            input_media_types=["image/png"],
            purpose_summary="image resize and compress",
            signature_hash="hash-img",
        )
        store_contract(conn, "skill", "image-resize", existing_sig,
                       skill_name="image-resize", branch_key="main")

        candidate = _make_candidate()
        sig = extract_contract(candidate, _make_behavior())
        nearest = find_nearest(conn, sig)
        result = judge_purpose(candidate, sig, nearest)

        assert result["relation"] == "different_purpose"
        assert result["target_skill"] == ""

    def test_judge_purpose_empty_nearest(self):
        """nearest 为空 → different_purpose。"""
        candidate = _make_candidate()
        sig = extract_contract(candidate, _make_behavior())
        result = judge_purpose(candidate, sig, [])
        assert result["relation"] == "different_purpose"

    def test_judge_purpose_same_branch_exact_hash(self):
        """exact signature_hash 匹配 → same_branch。"""
        conn = _memory_db()

        # 先存入一个契约
        candidate = _make_candidate()
        sig = extract_contract(candidate, _make_behavior())
        store_contract(conn, "skill", "doc-to-markdown", sig,
                       skill_name="doc-to-markdown", branch_key="pdf")

        # 相同 candidate → 相同 hash
        nearest = find_nearest(conn, sig)
        result = judge_purpose(candidate, sig, nearest)

        assert result["relation"] == "same_branch"
        assert result["target_skill"] == "doc-to-markdown"
        assert result["target_branch"] == "pdf"


class TestClassify:
    """三选一分类（契约引擎设计 §5）。"""

    def test_classify_new_skill(self):
        """different_purpose → new_skill。"""
        candidate = _make_candidate()
        sig = extract_contract(candidate, _make_behavior())
        result = classify(candidate, sig, {"relation": "different_purpose"})
        assert result == "new_skill"

    def test_classify_new_branch(self):
        """same_purpose_new_branch → new_branch。"""
        candidate = _make_candidate()
        sig = extract_contract(candidate, _make_behavior())
        result = classify(candidate, sig, {
            "relation": "same_purpose_new_branch",
            "target_skill": "doc-to-markdown",
        })
        assert result == "new_branch"

    def test_classify_iteration(self):
        """同上分支 + C 支配 B → iteration。"""
        candidate = _make_candidate()

        # C 的 behavior 在多个轴优于 B
        c_behavior = BehaviorSignature(
            markdown_valid=True, assets_emitted=True, image_ref_coverage=1.0,
            heading_preservation=0.9, content_coverage_grade="A",
            table_render_mode="kv_list", key_value_rendering=True,
            is_thin_wrapper=False,
        )
        sig = extract_contract(candidate, c_behavior)

        b_behavior = BehaviorSignature(
            markdown_valid=True, assets_emitted=False, image_ref_coverage=0.8,
            heading_preservation=0.7, content_coverage_grade="B",
            table_render_mode="kv_list", key_value_rendering=True,
            is_thin_wrapper=False,
        )

        result = classify(candidate, sig, {
            "relation": "same_branch",
            "target_skill": "doc-to-markdown",
            "target_branch": "pdf",
        }, target_behavior=b_behavior)

        assert result == "iteration"

    def test_classify_duplicate_equal(self):
        """behavior 相等 → duplicate。"""
        candidate = _make_candidate()
        behavior = _make_behavior()
        sig = extract_contract(candidate, behavior)

        result = classify(candidate, sig, {
            "relation": "same_branch",
            "target_skill": "doc-to-markdown",
            "target_branch": "pdf",
        }, target_behavior=behavior)

        assert result == "duplicate"

    def test_classify_duplicate_b_dominates(self):
        """B 支配 C → duplicate（丢 C 留 B）。"""
        candidate = _make_candidate()

        # C 的 behavior 弱于 B
        c_behavior = BehaviorSignature(
            markdown_valid=True, assets_emitted=False, image_ref_coverage=0.5,
            heading_preservation=0.6, content_coverage_grade="C",
            is_thin_wrapper=False,
        )
        sig = extract_contract(candidate, c_behavior)

        b_behavior = BehaviorSignature(
            markdown_valid=True, assets_emitted=True, image_ref_coverage=1.0,
            heading_preservation=1.0, content_coverage_grade="A",
            is_thin_wrapper=False,
        )

        result = classify(candidate, sig, {
            "relation": "same_branch",
        }, target_behavior=b_behavior)

        assert result == "duplicate"

    def test_classify_ambiguous(self):
        """不可比 → ambiguous。"""
        candidate = _make_candidate()

        # C: 覆盖率更高, B: 等级更高 → 不可比
        c_behavior = BehaviorSignature(
            image_ref_coverage=1.0, content_coverage_grade="B",
            is_thin_wrapper=False,
        )
        sig = extract_contract(candidate, c_behavior)

        b_behavior = BehaviorSignature(
            image_ref_coverage=0.5, content_coverage_grade="A",
            is_thin_wrapper=False,
        )

        result = classify(candidate, sig, {
            "relation": "same_branch",
        }, target_behavior=b_behavior)

        assert result == "ambiguous"

    def test_classify_ambiguous_no_target_behavior(self):
        """same_branch 但无 target_behavior → ambiguous（保守出口）。"""
        candidate = _make_candidate()
        sig = extract_contract(candidate, _make_behavior())

        result = classify(candidate, sig, {
            "relation": "same_branch",
        }, target_behavior=None)

        assert result == "ambiguous"


# ================================================================== #
# M5 — Composer
# ================================================================== #


class TestComposeNewSkill:
    """新 Skill + 第一条分支。"""

    def test_compose_new_skill_has_active_and_retained(self):
        """manifest 含 active_impl_ref + retained_impls。"""
        candidate = _make_candidate()
        sig = extract_contract(candidate, _make_behavior())

        manifest = compose_new_skill(candidate, sig, branch_key="main")

        assert manifest.name == "document-to-markdown"
        assert len(manifest.branches) == 1

        branch = manifest.branches[0]
        assert branch.key == "main"
        assert branch.active_impl_ref == "artifacts/cand-1/snapshot.py"
        assert branch.active_version == 1

        # retained_impls 含初始版本
        assert len(branch.retained_impls) == 1
        assert branch.retained_impls[0].impl_ref == branch.active_impl_ref
        assert branch.retained_impls[0].version == 1

    def test_compose_new_skill_contract_snapshot(self):
        """manifest.contract 记录 input/output 类型。"""
        candidate = _make_candidate()
        sig = extract_contract(candidate, _make_behavior())
        manifest = compose_new_skill(candidate, sig, branch_key="main")

        assert isinstance(manifest.contract, dict)
        assert "application/pdf" in manifest.contract.get("input_media_types", [])
        assert "text/markdown" in manifest.contract.get("output_types", [])

    def test_compose_unnamed_skill(self):
        """空 purpose → 'unnamed-skill'。"""
        candidate = Candidate(id="cand-no-purpose", purpose_guess="")
        sig = extract_contract(candidate, BehaviorSignature())
        manifest = compose_new_skill(candidate, sig, branch_key="default")
        assert manifest.name == "unnamed-skill"


class TestAddBranch:
    """向 manifest 添加第二个分支。"""

    def test_add_branch_adds_second_branch(self):
        candidate = _make_candidate()
        sig = extract_contract(candidate, _make_behavior())
        manifest = compose_new_skill(candidate, sig, branch_key="pdf")

        assert len(manifest.branches) == 1

        # docx 分支
        docx_candidate = Candidate(
            id="cand-docx",
            purpose_guess="document-to-markdown",
            input_artifacts=[
                Artifact(
                    path="b.docx",
                    media_type="application/vnd.openxmlformats-officedocument"
                              ".wordprocessingml.document",
                ),
            ],
            output_artifacts=[Artifact(path="b.md", media_type="text/markdown")],
            branch_identity={
                "normalized_input_family": "office_docx",
                "input_mode": "single_file",
            },
            input_profile="office_docx",
            code_snapshot_ref="artifacts/docx-handler.py",
            context=ExecContext(task_id="t-2", cwd="/proj/A", session_id="s-1"),
        )
        docx_sig = extract_contract(docx_candidate, _make_behavior())

        add_branch(manifest, docx_candidate, docx_sig, key="docx")

        assert len(manifest.branches) == 2
        assert manifest.branches[0].key == "pdf"
        assert manifest.branches[1].key == "docx"
        assert manifest.branches[1].active_impl_ref == "artifacts/docx-handler.py"
        assert manifest.branches[1].active_version == 1
        assert len(manifest.branches[1].retained_impls) == 1

    def test_add_branch_rejects_duplicate_key(self):
        candidate = _make_candidate()
        sig = extract_contract(candidate, _make_behavior())
        manifest = compose_new_skill(candidate, sig, branch_key="main")

        import pytest
        with pytest.raises(ValueError, match="already exists"):
            add_branch(manifest, candidate, sig, key="main")


class TestApplyIteration:
    """分支迭代：版本 +1 / 旧入 retained。"""

    def test_apply_iteration_increments_version(self):
        candidate = _make_candidate()
        sig = extract_contract(candidate, _make_behavior())
        manifest = compose_new_skill(candidate, sig, branch_key="main")

        branch = manifest.branches[0]
        old_ref = branch.active_impl_ref
        old_version = branch.active_version

        apply_iteration(manifest, "main", "artifacts/cand-2/snapshot_v2.py")

        branch = manifest.branches[0]
        assert branch.active_version == old_version + 1
        assert branch.active_impl_ref == "artifacts/cand-2/snapshot_v2.py"

        # 旧实现在 retained 中
        refs = [r.impl_ref for r in branch.retained_impls]
        assert old_ref in refs
        assert "artifacts/cand-2/snapshot_v2.py" in refs

    def test_apply_iteration_twice(self):
        """两次迭代：v1→v2→v3, retained 含全部版本。"""
        candidate = _make_candidate()
        sig = extract_contract(candidate, _make_behavior())
        manifest = compose_new_skill(candidate, sig, branch_key="main")

        apply_iteration(manifest, "main", "v2.py")
        apply_iteration(manifest, "main", "v3.py")

        branch = manifest.branches[0]
        assert branch.active_version == 3
        assert branch.active_impl_ref == "v3.py"
        all_refs = [r.impl_ref for r in branch.retained_impls]
        assert "artifacts/cand-1/snapshot.py" in all_refs
        assert "v2.py" in all_refs
        assert "v3.py" in all_refs

    def test_apply_iteration_explicit_version(self):
        """显式指定 version。"""
        candidate = _make_candidate()
        sig = extract_contract(candidate, _make_behavior())
        manifest = compose_new_skill(candidate, sig, branch_key="main")

        apply_iteration(manifest, "main", "v2.py", version=5)
        branch = manifest.branches[0]
        assert branch.active_version == 5

    def test_apply_iteration_unknown_branch(self):
        """不存在分支 → KeyError。"""
        candidate = _make_candidate()
        sig = extract_contract(candidate, _make_behavior())
        manifest = compose_new_skill(candidate, sig, branch_key="main")

        import pytest
        with pytest.raises(KeyError, match="not found"):
            apply_iteration(manifest, "nonexistent", "v2.py")


class TestPromoteShared:
    """简化版 shared_promotion 检测。"""

    def test_promote_shared_true_when_in_list(self):
        candidate = _make_candidate()
        sig = extract_contract(candidate, _make_behavior())
        manifest = compose_new_skill(candidate, sig, branch_key="main")
        manifest.shared_post_processing.append("table_to_list")

        assert promote_shared(manifest, "table_to_list") is True

    def test_promote_shared_false_when_not_in_list(self):
        candidate = _make_candidate()
        sig = extract_contract(candidate, _make_behavior())
        manifest = compose_new_skill(candidate, sig, branch_key="main")

        assert promote_shared(manifest, "sanitize_text") is False

    def test_promote_shared_false_all_thin_wrappers(self):
        """全部分支都是 thin_wrapper → False。"""
        candidate = _make_candidate()
        sig = extract_contract(candidate, _make_behavior())
        manifest = compose_new_skill(candidate, sig, branch_key="main")
        manifest.shared_post_processing.append("table_to_list")
        manifest.branches[0].is_thin_wrapper = True

        assert promote_shared(manifest, "table_to_list") is False
