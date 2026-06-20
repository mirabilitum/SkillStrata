"""M6b — warm-start 回灌核心逻辑。

只操作 SQLite，纯读/纯写分离：
- check_r_miss / warmstart_lookup：纯读
- record_usage：写（INSERT + UPDATE，原子事务）

对照设计：技术栈与运行时 §4（warm-start 被动）、运维层 R_miss 收紧作用域。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# R_miss 检查（收紧版：全 scope 复合命中）
# --------------------------------------------------------------------------- #

def check_r_miss(
    conn: sqlite3.Connection,
    skill_name: str,
    branch_key: str,
    contract_slice: str,
    version: int,
    env_fp: str,
) -> bool:
    """查 r_miss 全 scope 复合命中（收紧版，不宽匹配）。

    五个维度必须全部相等才视为命中：
      skill_name + branch_key + contract_slice + version + env_fingerprint
    返回 True = 有坏记录，不应推荐该分支。
    """
    row = conn.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM r_miss
        WHERE skill_name = ?
          AND branch_key = ?
          AND contract_slice = ?
          AND version = ?
          AND env_fingerprint = ?
        """,
        (skill_name, branch_key, contract_slice, version, env_fp),
    ).fetchone()
    return row["cnt"] > 0


# --------------------------------------------------------------------------- #
# Warm-start 查找
# --------------------------------------------------------------------------- #

def _parse_contract_json(raw: Any) -> dict:
    """安全解析 contract_json 字段。"""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def warmstart_lookup(
    conn: sqlite3.Connection,
    task_purpose_summary: str,
    input_media_types: list[str],
    top_n: int = 5,
) -> list[dict]:
    """粗匹配契约表 + 排除 R_miss 坏项 + 按 quality 排序，返回 top-N。

    匹配条件（任一满足即可）：
      1. contract_json.purpose_summary 含查询词（不区分大小写）
      2. contract_json.input_media_types 与提供的 input_media_types 有重叠

    排除条件：
      - 该 skill+branch 在 r_miss 中有任何记录

    排序：success_rate DESC, reuse_count DESC。
    """
    # --- step 1: 取所有 promoted skill ---
    promoted = conn.execute(
        "SELECT name FROM skills WHERE status = 'promoted'"
    ).fetchall()
    if not promoted:
        return []

    promoted_names = [r["name"] for r in promoted]
    placeholders = ",".join("?" * len(promoted_names))

    # --- step 2: 取 contract_signatures + quality_rollup ---
    rows = conn.execute(
        f"""
        SELECT cs.skill_name, cs.branch_key, cs.contract_json,
               q.reuse_count, q.success_rate
        FROM contract_signatures cs
        LEFT JOIN quality_rollup q ON q.skill_name = cs.skill_name
        WHERE cs.skill_name IN ({placeholders})
        ORDER BY cs.skill_name, cs.branch_key
        """,
        promoted_names,
    ).fetchall()

    # --- step 3: Python 端过滤 ---
    query_lower = task_purpose_summary.lower()
    results: list[dict[str, Any]] = []

    for r in rows:
        contract = _parse_contract_json(r["contract_json"])
        purpose = contract.get("purpose_summary", "") or ""
        inputs: list[str] = contract.get("input_media_types", []) or []

        # 匹配条件
        purpose_match = query_lower in purpose.lower() if task_purpose_summary else False
        input_match = (
            bool(set(input_media_types) & set(inputs))
            if input_media_types and inputs
            else False
        )
        if not (purpose_match or input_match):
            continue

        # 排除 R_miss（skill + branch 级别）
        rmiss = conn.execute(
            "SELECT COUNT(*) FROM r_miss WHERE skill_name = ? AND branch_key = ?",
            (r["skill_name"], r["branch_key"]),
        ).fetchone()[0]
        if rmiss > 0:
            continue

        results.append({
            "skill_name": r["skill_name"],
            "branch_key": r["branch_key"],
            "purpose_summary": purpose,
            "reuse_count": r["reuse_count"] or 0,
            "success_rate": r["success_rate"] or 0.0,
        })

    # --- step 4: 按 quality 排序 ---
    results.sort(key=lambda x: (x["success_rate"], x["reuse_count"]), reverse=True)
    return results[:top_n]


# --------------------------------------------------------------------------- #
# 记录使用 & 更新质量
# --------------------------------------------------------------------------- #

def record_usage(
    conn: sqlite3.Connection,
    skill_name: str,
    branch_key: str,
    status: str,
    warmstart_hit: bool = False,
    input_summary: str = "",
    host_agent: str = "",
) -> None:
    """INSERT usage_events + UPSERT quality_rollup（原子事务）。

    成功率和复用计数按实际 usage_events 统计。
    """
    now = _now()
    conn.execute(
        """
        INSERT INTO usage_events
            (skill_name, branch_key, host_agent, status, input_summary, warmstart_hit, ts)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (skill_name, branch_key, host_agent, status, input_summary, int(warmstart_hit), now),
    )

    # 重算 quality 统计
    total = conn.execute(
        "SELECT COUNT(*) FROM usage_events WHERE skill_name = ?",
        (skill_name,),
    ).fetchone()[0]
    success = conn.execute(
        "SELECT COUNT(*) FROM usage_events WHERE skill_name = ? AND status = 'success'",
        (skill_name,),
    ).fetchone()[0]
    rate = success / total if total > 0 else 0.0

    conn.execute(
        """
        INSERT INTO quality_rollup (skill_name, reuse_count, success_rate, last_used)
        VALUES (?, 1, ?, ?)
        ON CONFLICT(skill_name) DO UPDATE SET
            reuse_count = reuse_count + 1,
            success_rate = ?,
            last_used = ?
        """,
        (skill_name, rate, now, rate, now),
    )
    conn.commit()
