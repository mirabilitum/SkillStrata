"""T0.4 接口契约测试：序列化往返 + 阶段编号 + behavior 比较语义 + 显式搁置。"""
from distiller import contracts as c


def test_stage_rank_real_counterexample():
    # 真反例：字典序 'contract_extracted' < 'discovered' 为 True，但 rank 50 > 10
    assert "contract_extracted" < "discovered"  # 字符串字典序
    assert c.STAGE_RANK["contract_extracted"] > c.STAGE_RANK["discovered"]  # 真顺序相反
    ranks = [c.STAGE_RANK[s] for s in c.STAGE_RANK]
    assert ranks == sorted(ranks)
    # 字典序 sorted != 管线顺序
    assert sorted(c.STAGE_RANK, key=str) != list(c.STAGE_RANK)


def test_candidate_stage_rank_property():
    cand = c.example_candidate()
    assert cand.stage_rank == 10
    cand.stage = "composed"
    assert cand.stage_rank == 80


def test_candidate_roundtrip_with_context_and_result():
    cand = c.example_candidate()
    back = c.Candidate.from_dict(c.to_dict(cand))
    assert back.result_status == "success"
    assert back.exit_code == 0
    assert back.context.task_id == "t-1"
    assert back.input_profile == "pdf_text"
    assert back.input_artifacts[0].media_type == "application/pdf"


def test_deferred_candidate_is_explicit_not_silent():
    d = c.example_deferred_candidate()
    assert d.pipeline_status == "deferred"
    assert d.deferred_reason == "dependency"
    assert d.requires_host_capability == ["libreoffice"]


def test_behavior_signature_roundtrip():
    b = c.example_behavior_signature()
    back = c.BehaviorSignature(**c.to_dict(b))
    assert back.table_render_mode == "kv_list"
    assert back.schema_version == c.BEHAVIOR_SCHEMA_VERSION


def test_behavior_field_rules_structured():
    r = c.BEHAVIOR_FIELD_RULES
    assert r["table_render_mode"]["comparable"] is False         # categorical 无序
    assert r["content_coverage_grade"]["kind"] == "ordinal"
    assert r["image_ref_coverage"]["tolerance"] == 0.02
    assert r["is_thin_wrapper"]["better"] is False               # False 更宜作主实现


def test_compare_behavior_dominance():
    a = c.example_behavior_signature()  # grade A, coverage 1.0, thin=False
    b = c.BehaviorSignature(markdown_valid=True, assets_emitted=True,
                            image_ref_coverage=0.8, heading_preservation=1.0,
                            content_coverage_grade="B", table_render_mode="kv_list",
                            key_value_rendering=True, is_thin_wrapper=False)
    assert c.compare_behavior(a, b) == "a_dominates"
    assert c.compare_behavior(b, a) == "b_dominates"
    assert c.compare_behavior(a, a) == "equal"


def test_compare_behavior_incomparable():
    a = c.BehaviorSignature(image_ref_coverage=1.0, content_coverage_grade="B")
    b = c.BehaviorSignature(image_ref_coverage=0.5, content_coverage_grade="A")
    # a 覆盖率更高、b 等级更高 → 不可比
    assert c.compare_behavior(a, b) == "incomparable"


def test_contract_signature_carries_behavior_and_code_evidence():
    cs = c.example_contract_signature()
    back = c.ContractSignature.from_dict(c.to_dict(cs))
    assert back.behavior_signature is not None
    assert back.behavior_signature.table_render_mode == "kv_list"
    assert back.code_evidence_ref != ""
    assert back.signature_hash != ""


def test_skill_manifest_roundtrip_retained_impls_and_team_fields():
    m = c.example_skill_manifest()
    back = c.SkillManifest.from_dict(c.to_dict(m))
    assert back.name == "doc-to-markdown"
    assert back.branches[0].active_impl_ref.endswith("pdf.py")
    assert back.branches[0].retained_impls[0].version == 1
    assert back.host_native["mcp_tool"] == "doc_to_markdown"
    assert back.tags == ["convert", "markdown", "document"]
    # 团队预留
    assert back.visibility == "hidden"
    assert hasattr(back, "created_by") and hasattr(back, "dedup_key")
