"""document-to-markdown 能力域（阶段 1：对现有规则的注册封装，行为零变化）。

事实来源仍是 discovery.py / pipeline.py / output_gate.py（它们被现有测试直接
引用，不能物理搬走）。本类只是把散在各处的 doc 规则收拢到一个"域"对象后面，
让 domain adapter 接缝显式化。等第二个域出现、逼出共性时，再做真正的代码搬迁。
"""
from __future__ import annotations

from typing import Any

from .. import discovery, output_gate, pipeline
from ..contracts import Artifact, BehaviorSignature, Candidate, ContractSignature

DOMAIN_NAME = "document_to_markdown"


class DocumentToMarkdownDomain:
    name = DOMAIN_NAME
    version = 1

    def shape_match(self, record: dict[str, Any]) -> bool:
        return discovery.shape_match(record)

    def guess_input_profile(self, input_artifacts: list[Artifact]) -> str:
        return discovery._guess_input_profile(input_artifacts)

    def purpose_guess(self, record: dict[str, Any]) -> str:
        # 现状：doc 域的 purpose 固定；保留在此以便日后各域自定。
        return "document-to-markdown"

    def read_input_text(self, cand: Candidate) -> str:
        return pipeline._input_text(cand)

    def coverage_unmeasurable(self, cand: Candidate, input_text: str) -> bool:
        return pipeline._coverage_unmeasurable(cand, input_text)

    def gate(
        self, cand: Candidate, output_text: str, input_text: str
    ) -> tuple[bool, BehaviorSignature]:
        return output_gate.output_gate(cand, output_text, input_text)

    def branch_key(self, cand: Candidate, sig: ContractSignature) -> str:
        return pipeline._branch_key_for(cand, sig)
