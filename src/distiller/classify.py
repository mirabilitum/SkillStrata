"""M4+M5 — 目的判同 + 三选一分类（规则版，无 LLM 时的 MVP 回退）。

设计对应契约引擎设计 §4（目的判同：两段式召回+裁决）与
§5（三选一分类：新工具 / 同目的新分支 / 迭代|重复|ambiguous）。

当 LLM judge 不可用时，本模块走规则判同，不阻塞纯 Python 主链。
"""
from __future__ import annotations

import re
from typing import Any

from .contracts import (
    BehaviorSignature,
    Candidate,
    Classification,
    ContractSignature,
    compare_behavior,
)


def _extract_keywords(text: str) -> set[str]:
    """从文本中提取长度 >= 4 的字母数字词作为关键词。"""
    words = re.findall(r"[a-zA-Z_]\w{3,}", text.lower())
    return set(words)


def judge_purpose(
    candidate: Candidate,
    sig: ContractSignature,
    nearest: list[dict[str, Any]],
) -> dict[str, str]:
    """规则版目的判同（契约引擎设计 §4，无 LLM 裁决的 MVP 回退）。

    判定逻辑（按优先级）:
      1. 有 exact signature_hash 匹配 → same_branch
      2. 同 input_media_type + purpose 关键词重叠 → same_purpose_new_branch
      3. 以上都不满足 → different_purpose

    返回 dict:
      relation: "same_branch" | "same_purpose_new_branch" | "different_purpose"
      target_skill: 匹配技能名（无匹配时为空串）
      target_branch: 匹配分支 key（无匹配时为空串）
    """
    if nearest is None:
        nearest = []

    input_set = set(sig.input_media_types)
    purpose_keywords = _extract_keywords(sig.purpose_summary)

    best_match: tuple[str, str, str] | None = None  # (skill_name, branch_key, relation)

    for entry in nearest:
        contract_data = entry.get("contract_data", {}) or {}
        row_input_set = set(contract_data.get("input_media_types", []))
        row_purpose = contract_data.get("purpose_summary", "") or ""
        row_keywords = _extract_keywords(row_purpose)

        # 条件 1: exact signature_hash 匹配 → same_branch
        if entry.get("signature_hash") and entry["signature_hash"] == sig.signature_hash:
            best_match = (
                entry.get("skill_name", "") or "",
                entry.get("branch_key", "") or "",
                "same_branch",
            )
            break

        # 条件 2: 同 input_media_type + 目的关键词重叠 → same_purpose
        if input_set & row_input_set and purpose_keywords & row_keywords:
            best_match = (
                entry.get("skill_name", "") or "",
                entry.get("branch_key", "") or "",
                "same_purpose_new_branch",
            )
            # 不 break，继续找可能更精确的 same_branch 匹配

    if best_match:
        target_skill, target_branch, relation = best_match
    else:
        relation = "different_purpose"
        target_skill = ""
        target_branch = ""

    return {
        "relation": relation,
        "target_skill": target_skill,
        "target_branch": target_branch,
    }


def classify(
    candidate: Candidate,
    sig: ContractSignature,
    relation_info: dict[str, str],
    target_behavior: BehaviorSignature | None = None,
) -> Classification:
    """三选一分类（契约引擎设计 §5）。

    根据 judge_purpose 输出的关系标签 + behavior_signature 偏序，决定最终分类：

    different_purpose          → new_skill（建新能力）
    same_purpose_new_branch    → new_branch（同目的新分支）
    same_branch:
      - C 支配 B               → iteration（C 变 active, B 进 retained）
      - B 支配 C / 相等        → duplicate（丢 C 留 B）
      - 不可比                 → ambiguous（需人工 pin）

    Args:
        candidate: 当前候选碎片。
        sig: 候选的契约签名。
        relation_info: judge_purpose 的返回 dict。
        target_behavior: 匹配分支的 BehaviorSignature（same_branch 时必需）。

    Returns:
        Classification Literal 值。
    """
    relation = relation_info.get("relation", "different_purpose")

    if relation == "different_purpose":
        return "new_skill"

    if relation == "same_purpose_new_branch":
        return "new_branch"

    # relation == "same_branch": 需要 behavior 偏序判定
    if sig.behavior_signature is None or target_behavior is None:
        return "ambiguous"

    cmp = compare_behavior(sig.behavior_signature, target_behavior)

    if cmp == "a_dominates":
        return "iteration"
    elif cmp in ("b_dominates", "equal"):
        return "duplicate"
    else:  # incomparable
        return "ambiguous"
