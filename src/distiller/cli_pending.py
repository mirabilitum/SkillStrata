"""M7b — 审查队列（纯读，不改状态）。

供 CLI 使用的只读查询：列出待审查的候选、获取单个候选详情。
conn 由调用方传入（db.connect 产出，row_factory=sqlite3.Row）。
"""
from __future__ import annotations

import sqlite3


def list_pending(conn: sqlite3.Connection) -> list[dict]:
    """列出所有待审查的候选（已过验证但未 promoted，且未被 rejected）。

    返回 candidates WHERE lifecycle='verified' AND result_status='success'
    AND pipeline_status IN ('active','deferred')。

    pending 是审查层语义，须显式排除 rejected（复审四次 P2-2）：中后段异常后
    candidate 可能停在 verified/success/rejected（stage/lifecycle 不倒退），
    若不过滤 pipeline_status，这类失败候选会污染待审队列。
    保留 duplicate（active，可复核）与 ambiguous（deferred，待人工 pin）。

    Returns:
        list[dict]: 每个 dict 含候选基本字段。
    """
    rows = conn.execute("""
        SELECT id, purpose_guess, input_profile,
               stage, lifecycle, result_status, determinism,
               created_at, updated_at
        FROM candidates
        WHERE lifecycle = 'verified'
          AND result_status = 'success'
          AND pipeline_status IN ('active', 'deferred')
        ORDER BY created_at
    """).fetchall()
    return [dict(r) for r in rows]


def get_review(conn: sqlite3.Connection, candidate_id: str) -> dict:
    """返回单个候选的审查详情，包括候选信息 + 关联 skill/branch + contract_signatures。

    未找到时返回 {}。

    Returns:
        dict: 包含 candidate、related_skills、contract_signatures 的嵌套 dict。
    """
    cand = conn.execute(
        "SELECT * FROM candidates WHERE id=?", (candidate_id,)
    ).fetchone()
    if cand is None:
        return {}

    result = dict(cand)

    # 关联 skill（通过 purpose_guess 名称匹配）
    purpose = result.get("purpose_guess", "")
    rel_skills = conn.execute(
        "SELECT name, purpose, status, visibility FROM skills WHERE name = ?",
        (purpose,),
    ).fetchall()
    result["related_skills"] = [dict(r) for r in rel_skills]

    # 非精确匹配也查一下
    if not rel_skills:
        rel_skills = conn.execute(
            "SELECT name, purpose, status, visibility FROM skills WHERE purpose LIKE ?",
            (f"%{purpose}%",),
        ).fetchall()
        result["related_skills"] = [dict(r) for r in rel_skills]

    # contract_signatures（关联该候选的契约签名）
    cs = conn.execute(
        """SELECT id, signature_hash, contract_json,
                  branch_identity_json, schema_version, created_at
           FROM contract_signatures
           WHERE entity_type = 'candidate' AND entity_id = ?
           ORDER BY id""",
        (candidate_id,),
    ).fetchall()
    result["contract_signatures"] = [dict(r) for r in cs]

    return result
