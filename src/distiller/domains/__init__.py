"""Domain adapter 层 —— 能力域的可插拔封装（个人通用版演进 阶段 1）。

设计红线（见 `docs/个人通用版演进-实现评估与推进.md` 问题 1/2）：
  domain adapter 只吃"发现期 + gate 策略"，**绝不碰合并主轴**——
  contract 抽取 / signature_hash / BehaviorSignature 比较语义留在全局唯一实现，
  跨域一致，否则判同/去重/三选一崩坏。

本阶段行为零变化：doc 规则仍以 discovery.py / pipeline.py 为事实来源，
document_to_markdown 域是对它们的**注册封装**（薄委托），只把"能力域"这个
接缝显式化。真正的代码搬迁等第二个域出现、逼出共性时再做。
"""
from __future__ import annotations

from .base import CapabilityDomain
from .document_to_markdown import DocumentToMarkdownDomain
from .generic_file_transform import GenericFileTransformDomain

# 注册表：按注册顺序匹配，第一个 shape_match 命中的域胜出。
_REGISTRY: list[CapabilityDomain] = []


def register(domain: CapabilityDomain) -> None:
    """注册一个能力域（重复 name 覆盖旧的）。"""
    global _REGISTRY
    _REGISTRY = [d for d in _REGISTRY if d.name != domain.name]
    _REGISTRY.append(domain)


def registered() -> list[CapabilityDomain]:
    """返回当前已注册的域（副本）。"""
    return list(_REGISTRY)


def get(name: str) -> CapabilityDomain | None:
    """按 name 取域，未注册返回 None。"""
    for d in _REGISTRY:
        if d.name == name:
            return d
    return None


def match_domain(record: dict) -> CapabilityDomain | None:
    """按注册顺序返回第一个 shape_match 命中的域；都不中返回 None。"""
    for d in _REGISTRY:
        if d.shape_match(record):
            return d
    return None


# --- 默认注册：document-to-markdown 先（更精确的 shape_match），generic 兜底 ---
register(DocumentToMarkdownDomain())
register(GenericFileTransformDomain())

__all__ = [
    "CapabilityDomain",
    "DocumentToMarkdownDomain",
    "register",
    "registered",
    "get",
    "match_domain",
]
