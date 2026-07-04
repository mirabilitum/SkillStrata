"""M4 — 契约抽取：从 Candidate + BehaviorSignature 生成 ContractSignature。

三件套 + behavior_signature（契约引擎设计 §3），
含 SQLite 回退近邻检索（无 Qdrant 时的 MVP fallback）。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from .contracts import (
    BehaviorSignature,
    Candidate,
    ContractSignature,
    to_dict,
)


def _compute_signature_hash(sig: ContractSignature) -> str:
    """生成 signature_hash（sha256 hex），排除自身 hash 字段避免循环。

    **不含 behavior_signature**：行为是"价值指纹"，按设计（contracts §275 /
    契约引擎设计 §3.2、§120）只用于"目的内"的重复/迭代/薄壳判定，
    **不参与"是不是同一分支"**。若把它算进 hash，两个行为略不同的成熟实现
    就永远拿不到 same_branch，iteration/ambiguous 路径将不可达。
    """
    d = to_dict(sig)
    d.pop("signature_hash", None)
    d.pop("behavior_signature", None)  # 价值指纹不入合并 key
    raw = json.dumps(d, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def extract_contract(
    candidate: Candidate,
    behavior: BehaviorSignature,
    purpose_embedding_ref: str = "",
) -> ContractSignature:
    """从 Candidate + BehaviorSignature 抽取完整的 ContractSignature。

    契约 = 四件套（契约引擎设计 §3）：
    - 输入契约：input_artifacts.media_type / arity（branch_identity 的 input_mode）
    - 输出契约：output_artifacts 的类型列表
    - 目的摘要：purpose_guess（目的 embedding 引用由调用方传入）
    - behavior_signature：验证层产出的行为指纹

    生成 signature_hash（sha256 hex）作为精确匹配 key。
    """
    input_media_types = list(
        {a.media_type for a in candidate.input_artifacts if a.media_type}
    )
    output_types = list(
        {a.media_type for a in candidate.output_artifacts if a.media_type}
    )

    # input_arity 优先从 branch_identity 取，再 fallback 到默认
    input_arity = "single_file"
    if candidate.branch_identity:
        input_arity = candidate.branch_identity.get("input_mode", "single_file")

    purpose_summary = candidate.purpose_guess or ""

    sig = ContractSignature(
        input_media_types=input_media_types,
        input_arity=input_arity,
        output_types=output_types,
        output_side_artifacts=[],
        purpose_summary=purpose_summary,
        purpose_embedding_ref=purpose_embedding_ref,
        branch_identity=dict(candidate.branch_identity) if candidate.branch_identity else {},
        behavior_signature=behavior,
        code_evidence_ref=candidate.code_snapshot_ref or "",
        structural_fingerprint="",
        signature_hash="",
    )
    sig.signature_hash = _compute_signature_hash(sig)
    return sig


def store_contract(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_id: str,
    sig: ContractSignature,
    skill_name: str = "",
    branch_key: str = "",
) -> int:
    """将 ContractSignature 写入 contract_signatures 表，返回自增 id。

    contract_json / behavior_signature_json / branch_identity_json
    分别序列化为 TEXT（对应 db.py 的列定义）。
    """
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO contract_signatures
           (entity_type, entity_id, skill_name, branch_key, signature_hash,
            contract_json, behavior_signature_json, branch_identity_json,
            purpose_embedding_ref, code_evidence_ref, schema_version, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            entity_type,
            entity_id,
            skill_name,
            branch_key,
            sig.signature_hash,
            json.dumps(to_dict(sig), ensure_ascii=False),
            json.dumps(to_dict(sig.behavior_signature), ensure_ascii=False)
            if sig.behavior_signature
            else None,
            json.dumps(sig.branch_identity, ensure_ascii=False)
            if sig.branch_identity
            else None,
            sig.purpose_embedding_ref,
            sig.code_evidence_ref,
            sig.schema_version,
            now,
        ),
    )
    conn.commit()
    return cur.lastrowid or 0


def find_nearest(
    conn: sqlite3.Connection, sig: ContractSignature
) -> list[dict[str, Any]]:
    """SQLite 穷举近邻检索（MVP 回退，无 Qdrant 时使用）。

    匹配策略：遍历所有 entity_type IN ('skill', 'branch') 的已有契约，
    筛选出 input_media_types 有交集的条目返回。

    返回列表按 id DESC 排序，每条包含:
      - id, entity_type, entity_id, skill_name, branch_key
      - signature_hash, contract_json, behavior_signature_json
      - contract_data（解析后的 contract_json dict）
    """
    input_set = set(sig.input_media_types)
    if not input_set:
        return []

    rows = conn.execute(
        """SELECT id, entity_type, entity_id, skill_name, branch_key,
                  signature_hash, contract_json, behavior_signature_json
           FROM contract_signatures
           WHERE entity_type IN ('skill', 'branch')
           ORDER BY id DESC"""
    ).fetchall()

    nearest: list[dict[str, Any]] = []
    for row in rows:
        try:
            cj = json.loads(row["contract_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        row_media = set(cj.get("input_media_types", []))
        if input_set & row_media:
            entry = dict(row)
            entry["contract_data"] = cj
            nearest.append(entry)

    return nearest
