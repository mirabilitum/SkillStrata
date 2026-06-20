"""T0.4 接口契约测试：序列化往返 + 阶段编号 + 字段比较规则。"""
from distiller import contracts as c


def test_stage_rank_monotonic_and_no_string_compare():
    ranks = [c.STAGE_RANK[s] for s in
             ["discovered", "gate0_done", "replayed", "output_gated",
              "contract_extracted", "judged", "classified", "composed"]]
    assert ranks == sorted(ranks)
    assert ranks[-1] == 80
    # 字典序会骗人：'classified' < 'composed' 但管线顺序相反
    assert "classified" < "composed"  # 字符串
    assert c.STAGE_RANK["classified"] < c.STAGE_RANK["composed"]  # 真顺序


def test_candidate_stage_rank_property():
    cand = c.example_candidate()
    assert cand.stage_rank == 10
    cand.stage = "composed"
    assert cand.stage_rank == 80


def test_behavior_field_rules_categorical_has_no_order():
    assert c.BEHAVIOR_FIELD_RULES["table_render_mode"] == "categorical"
    assert c.BEHAVIOR_FIELD_RULES["content_coverage_grade"] == "ordinal"
    assert c.BEHAVIOR_FIELD_RULES["image_ref_coverage"] == "numeric"
    assert c.GRADE_ORDER.index("A") > c.GRADE_ORDER.index("D")


def test_enriched_event_roundtrip():
    ev = c.example_enriched_event()
    d = c.to_dict(ev)
    back = c.EnrichedToolEvent.from_dict(d)
    assert back.raw.event_id == ev.raw.event_id
    assert back.input_artifacts[0].media_type == "application/pdf"
    assert back.determinism_signals.replay_byte_identical is True


def test_skill_manifest_roundtrip_and_team_fields():
    m = c.example_skill_manifest()
    d = c.to_dict(m)
    back = c.SkillManifest.from_dict(d)
    assert back.name == "doc-to-markdown"
    assert back.branches[0].key == "pdf"
    # 团队预留字段在 schema 里
    assert back.visibility == "hidden"
    assert hasattr(back, "created_by")
    assert hasattr(back, "dedup_key")


def test_examples_are_valid_instances():
    assert isinstance(c.example_raw_event(), c.RawToolEvent)
    assert isinstance(c.example_candidate(), c.Candidate)
    assert c.example_behavior_signature().table_render_mode == "kv_list"
