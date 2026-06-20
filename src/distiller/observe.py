"""M7a — 只读观测模块（pull 模式）。

纯 SELECT，不改任何状态。
conn 由调用方传入（db.connect 产出，row_factory=sqlite3.Row）。
"""
from __future__ import annotations

import sqlite3


def _row(row: sqlite3.Row) -> dict:
    """sqlite3.Row → 普通 dict（列名为 key）。"""
    return dict(row)


# --------------------------------------------------------------------------- #

def list_skills(conn: sqlite3.Connection) -> list[dict]:
    """列所有 skill：name / branch_count / reuse_count / success_rate / visibility / status。

    LEFT JOIN branches 计分支数，LEFT JOIN quality_rollup 取复用指标。
    无 quality 行时 reuse_count=0, success_rate=0.0。
    """
    rows = conn.execute("""
        SELECT
            s.name,
            s.visibility,
            s.status,
            COUNT(b.id)                    AS branch_count,
            COALESCE(q.reuse_count,  0)    AS reuse_count,
            COALESCE(q.success_rate, 0.0)  AS success_rate
        FROM skills s
        LEFT JOIN branches       b ON b.skill_name = s.name
        LEFT JOIN quality_rollup q ON q.skill_name = s.name
        GROUP BY s.name
        ORDER BY s.name
    """).fetchall()
    return [_row(r) for r in rows]


def show_skill(conn: sqlite3.Connection, name: str) -> dict:
    """单 skill 详情：基本字段 + branches 列表 + quality 指标 + contract_signatures 列表。

    未找到时返回 {}。
    """
    skill_row = conn.execute(
        "SELECT * FROM skills WHERE name = ?", (name,)
    ).fetchone()
    if skill_row is None:
        return {}

    result = _row(skill_row)

    # branches（active_impl_ref / retained_impls 等）
    branch_rows = conn.execute(
        "SELECT * FROM branches WHERE skill_name = ? ORDER BY id", (name,)
    ).fetchall()
    result["branches"] = [_row(r) for r in branch_rows]

    # quality_rollup
    q_row = conn.execute(
        "SELECT * FROM quality_rollup WHERE skill_name = ?", (name,)
    ).fetchone()
    result["quality"] = _row(q_row) if q_row else {}

    # contract_signatures（契约哈希 / behavior_signature / branch_identity 等）
    cs_rows = conn.execute(
        "SELECT * FROM contract_signatures WHERE skill_name = ? ORDER BY id", (name,)
    ).fetchall()
    result["contract_signatures"] = [_row(r) for r in cs_rows]

    return result


def usage(conn: sqlite3.Connection, name: str) -> list[dict]:
    """从 usage_events 看调用历史（成功/失败、warmstart_hit）。

    按主键升序，最早的事件在前。
    """
    rows = conn.execute(
        """
        SELECT id, skill_name, branch_key, host_agent, status,
               input_summary, warmstart_hit, ts
        FROM   usage_events
        WHERE  skill_name = ?
        ORDER BY id
        """,
        (name,),
    ).fetchall()
    return [_row(r) for r in rows]


def failures(conn: sqlite3.Connection, name: str) -> list[dict]:
    """从 r_miss 看在什么输入上栽过（failure_class / contract_slice / env_fingerprint）。

    按主键升序。
    """
    rows = conn.execute(
        """
        SELECT id, skill_name, branch_key, contract_slice, version,
               env_fingerprint, failure_class, ts
        FROM   r_miss
        WHERE  skill_name = ?
        ORDER BY id
        """,
        (name,),
    ).fetchall()
    return [_row(r) for r in rows]


def quality_of(conn: sqlite3.Connection, name: str) -> dict:
    """从 quality_rollup 取 reuse_count / success_rate / last_used。

    未找到时返回 {}。
    """
    row = conn.execute(
        "SELECT reuse_count, success_rate, last_used FROM quality_rollup WHERE skill_name = ?",
        (name,),
    ).fetchone()
    return _row(row) if row else {}
