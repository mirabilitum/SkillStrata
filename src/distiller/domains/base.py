"""CapabilityDomain 抽象接口（收窄版，见实现评估文档 §三）。

对比原路线图砍掉了 extract_contract / 完整 output_gate 实现——那些属于
合并主轴，跨域必须统一，不下放。domain 只负责：
  - 发现期：shape_match / input_profile / purpose_guess
  - gate 策略：gate（产物仍是全局 BehaviorSignature）/ coverage_unmeasurable / read_input_text
  - branch_key 的语义输入
"""
from __future__ import annotations

from typing import Any, Protocol

from ..contracts import Artifact, BehaviorSignature, Candidate, ContractSignature


class CapabilityDomain(Protocol):
    """能力域协议。实现类需提供 name/version 与下列方法。"""

    name: str
    version: int

    # --- 发现期 ---
    def shape_match(self, record: dict[str, Any]) -> bool:
        """判断一条 correlate 记录是否属于本域的形状。"""
        ...

    def guess_input_profile(self, input_artifacts: list[Artifact]) -> str:
        """粗判 input_profile（gate 分支化用）。"""
        ...

    def purpose_guess(self, record: dict[str, Any]) -> str:
        """本域给候选的初始 purpose_guess。"""
        ...

    # --- gate 策略（产物是全局 BehaviorSignature，比较语义不下放）---
    def read_input_text(self, cand: Candidate) -> str:
        """取输入文本供 gate 独立测量覆盖率；不可读返回空串。"""
        ...

    def coverage_unmeasurable(self, cand: Candidate, input_text: str) -> bool:
        """本域是否判定"覆盖率不可测"（→ deferred 而非 fail）。"""
        ...

    def gate(
        self, cand: Candidate, output_text: str, input_text: str
    ) -> tuple[bool, BehaviorSignature]:
        """域 gate：返回 (pass, BehaviorSignature)。BehaviorSignature 结构全局统一。"""
        ...

    # --- branch_key 语义输入（组装/hash 仍在全局）---
    def branch_key(self, cand: Candidate, sig: ContractSignature) -> str:
        """本域的分支 key（归一化输入族）。"""
        ...
