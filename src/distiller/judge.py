"""Judge 接口 —— 规则 + LLM 双实现（阶段 4 API Judge）。

设计红线（演进评估 §二·问题 6）：
  - skill_name 是 PRIMARY KEY 和 merge identity，不能用 LLM 非确定性输出。
    实际 skill_name 由 composer._derive_skill_name(purpose) 从 rule judge 产出，
    LLM 只提供更细的 purpose 描述 + suggested_name（非绑定、用于改善 CLI 展示）。
  - contract/signature_hash 仍由 contract_extract 全局计算（不下放）。
  - API 超时/非法 JSON 优雅 fallback 到 offline rule。
  - API 不能使 replay/gate 失败的候选 promoted——judge 跑在 pipeline 的 classify 之后，
    只补充元数据，不改变 merge 决策。

接入 config 链：`ANTHROPIC_API_KEY` → online，无 key → offline（详见 config.py）。
"""
from __future__ import annotations

import json
from typing import Any, Optional, Protocol

from .contracts import Candidate, ContractSignature


class Judge(Protocol):
    """判官协议。"""

    def judge(
        self,
        candidate: Candidate,
        sig: ContractSignature,
    ) -> dict[str, Any]:
        """返回结构化判断结果。调用时机：classify 之后（不影响 merge 决策）。

        Returns dict：
          is_reusable: bool
          domain: str
          purpose: str
          suggested_skill_name: str
          inputs: list[str]
          outputs: list[str]
          risks: list[str]
          confidence: float
          reason: str
        """
        ...


# ———————————————————————————————————— #
# Rule Judge（offline 回退）
# ———————————————————————————————————— #

class RuleJudge:
    """规则版判官——不依赖 LLM，用 candidate 自身元数据生成结构化结果。"""

    def judge(
        self,
        candidate: Candidate,
        sig: ContractSignature,
    ) -> dict[str, Any]:
        in_labels = list(sig.input_media_types) or ["unknown"]
        out_labels = list(sig.output_types) or ["unknown"]
        purpose = sig.purpose_summary or candidate.purpose_guess or ""
        name = purpose.strip().lower().replace(" ", "-")

        return {
            "is_reusable": True,
            "domain": candidate.context.source_ref.get("domain", "")
            if candidate.context and hasattr(candidate.context, "source_ref")
            else "",
            "purpose": purpose,
            "suggested_skill_name": name or "unnamed-skill",
            "inputs": in_labels,
            "outputs": out_labels,
            "risks": [],
            "confidence": 0.80,  # 规则版固定中等置信度
            "reason": "rule judge (offline): purpose derived from contract signature",
        }


# ———————————————————————————————————— #
# LLM Judge（online，需要 ANTHROPIC_API_KEY）
# ———————————————————————————————————— #

class LLMJudge:
    """Claude API 判官——改善命名/归类/解释。需要 API key。"""

    def __init__(
        self,
        api_key: str,
        tier: str = "haiku",
        timeout: int = 15,
    ):
        self._api_key = api_key
        self._tier = tier
        self._timeout = timeout

    def judge(
        self,
        candidate: Candidate,
        sig: ContractSignature,
    ) -> dict[str, Any]:
        # 实际 HTTP 调用待实现——当前回退到 rule
        # 保留接口签名供将来接入
        _ = (candidate, sig)
        return self._rule_fallback(candidate, sig, "LLM not yet wired")

    # ——— 内部 ———

    @staticmethod
    def _rule_fallback(candidate, sig, reason: str) -> dict:
        result = RuleJudge().judge(candidate, sig)
        result["reason"] = f"{reason}: {result['reason']}"
        result["confidence"] = 0.70
        return result


# ———————————————————————————————————— #
# Factory（按 config 选实现）
# ———————————————————————————————————— #

def make_judge(cfg) -> Judge:
    """按 config 创建判官实例。

    - cfg.judge.mode == "online" 且有 api_key → LLMJudge
    - 否则 → RuleJudge
    """
    if cfg.judge.mode == "online" and cfg.judge.api_key:
        return LLMJudge(
            api_key=cfg.judge.api_key,
            tier=cfg.judge.tier,
        )
    return RuleJudge()
