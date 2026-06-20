"""M5 — Composer：结构组合器，不是语义重写器。

操作只改内存中的 SkillManifest 对象，不写 filesystem（M6 接线时再落盘）。
对应契约引擎设计 §6（Composer vs Merger）与 §6.1（shared_promotion）。

关键区别（vs Yunjue Merger）：
  - 原样挂分支（retained_impls 全保留，不删兄弟）
  - best-of-N 只切换 active_impl，记 lineage，可回退
  - shared_promotion 有门槛：结构资格 + 实测实验
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from .contracts import (
    BehaviorSignature,
    Branch,
    Candidate,
    ContractSignature,
    ImplRef,
    SkillManifest,
)


def _derive_skill_name(purpose_summary: str) -> str:
    """从目的摘要派生技能名：小写 + 非字母数字替换为连字符。"""
    name = purpose_summary.strip().lower()
    name = re.sub(r"[^a-z0-9]+", "-", name)
    name = name.strip("-")
    return name or "unnamed-skill"


def compose_new_skill(
    candidate: Candidate,
    sig: ContractSignature,
    branch_key: str,
) -> SkillManifest:
    """创建新 Skill + 第一条分支。

    初始化:
      - skill name 从目的摘要派生
      - 首个 Branch 含 active_impl_ref + retained_impls
      - contract 快照（input/output 类型）
    """
    purpose = sig.purpose_summary or candidate.purpose_guess or ""
    name = _derive_skill_name(purpose)

    # 第一个 ImplRef（当前 active）
    impl_src = candidate.code_snapshot_ref or candidate.entry_ref or ""
    impl = ImplRef(
        impl_ref=impl_src,
        version=1,
    )

    # 创建第一条分支
    branch = Branch(
        key=branch_key,
        active_impl_ref=impl.impl_ref,
        active_version=1,
        retained_impls=[impl],
        is_thin_wrapper=False,
    )

    # 提取 author 信息
    author = ""
    if hasattr(candidate, "context") and candidate.context:
        if hasattr(candidate.context, "host_agent"):
            author = getattr(candidate.context, "host_agent", "")
        if not author and hasattr(candidate.context, "source_ref"):
            src = candidate.context.source_ref
            if isinstance(src, dict):
                author = src.get("author", "") or src.get("host_agent", "") or ""

    manifest = SkillManifest(
        name=name,
        purpose=purpose,
        contract={
            "input_media_types": list(sig.input_media_types),
            "output_types": list(sig.output_types),
        },
        tags=[],
        branches=[branch],
        determinism=candidate.determinism,
        source={"author": author, "origin_host": "trace"},
        created_by="",
        visibility="hidden",
    )

    return manifest


def add_branch(
    manifest: SkillManifest,
    candidate: Candidate,
    sig: ContractSignature,
    key: str,
) -> SkillManifest:
    """向已有 manifest 添加新分支（同目的不同输入类型）。

    Raises:
        ValueError: 分支 key 已存在。
    """
    existing_keys = {b.key for b in manifest.branches}
    if key in existing_keys:
        raise ValueError(
            f"Branch key '{key}' already exists in manifest '{manifest.name}'"
        )

    impl_src = candidate.code_snapshot_ref or candidate.entry_ref or ""
    impl = ImplRef(
        impl_ref=impl_src,
        version=1,
    )

    branch = Branch(
        key=key,
        active_impl_ref=impl.impl_ref,
        active_version=1,
        retained_impls=[impl],
        is_thin_wrapper=False,
    )

    manifest.branches.append(branch)
    return manifest


def apply_iteration(
    manifest: SkillManifest,
    branch_key: str,
    new_impl_ref: str,
    version: int | None = None,
) -> SkillManifest:
    """对指定分支执行迭代（版本 +1 / 旧入 retained）。

    - 旧 active_impl_ref → retained_impls（如不重复）
    - 新 impl_ref → active_impl_ref
    - version 自动 +1（除非显式指定）
    - 新版本同步加入 retained_impls

    Raises:
        KeyError: 分支 key 未找到。
    """
    for branch in manifest.branches:
        if branch.key == branch_key:
            # 旧实现推进 retained（去重）
            old_impl = ImplRef(
                impl_ref=branch.active_impl_ref,
                version=branch.active_version,
            )
            already = any(
                r.impl_ref == old_impl.impl_ref and r.version == old_impl.version
                for r in branch.retained_impls
            )
            if not already:
                branch.retained_impls.append(old_impl)

            # 设置新版本
            new_version = version if version is not None else branch.active_version + 1
            branch.active_impl_ref = new_impl_ref
            branch.active_version = new_version

            # 新版本加入 retained
            new_impl = ImplRef(
                impl_ref=new_impl_ref,
                version=new_version,
            )
            branch.retained_impls.append(new_impl)

            return manifest

    raise KeyError(
        f"Branch '{branch_key}' not found in manifest '{manifest.name}'"
    )


def promote_shared(
    manifest: SkillManifest,
    step_name: str,
    conn: sqlite3.Connection | None = None,
) -> bool:
    """简化版 shared_promotion 检测（MVP）。

    判定条件（契约引擎设计 §6.1，简化）:
      1. step_name 已在 shared_post_processing 列表中
      2. 至少有一个非 thin_wrapper 的分支（行为字段匹配）

    Args:
        manifest: 待检查的 SkillManifest。
        step_name: 要检查的后处理步骤名。
        conn: SQLite 连接（MVP 简化版未使用，保留签名兼容）。

    Returns:
        True 如果 step 已晋升为共享后处理。
    """
    if step_name not in manifest.shared_post_processing:
        return False

    # 行为字段匹配：至少有一个非 thin_wrapper 分支
    for branch in manifest.branches:
        if not branch.is_thin_wrapper:
            return True

    return False
