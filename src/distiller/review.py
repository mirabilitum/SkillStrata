"""M7b — 审查动作 + 质量门控（改状态，不是只读）。

所有操作带 SQLite 事务 + 写 lineage（人工干预也可追溯）。
conn 由调用方传入（db.connect 产出，row_factory=sqlite3.Row）。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# 高价值候选转正（Path-B）
# --------------------------------------------------------------------------- #

def pin_path_b(conn: sqlite3.Connection, candidate_id: str, reason: str) -> None:
    """高价值候选转正(Path-B)：UPDATE lifecycle='promoted' + 写 lineage 'promote'。

    Args:
        conn: SQLite 连接。
        candidate_id: 候选 ID。
        reason: 转正原因（人工备注）。

    Raises:
        ValueError: 候选不存在。
    """
    with conn:
        row = conn.execute(
            "SELECT lifecycle FROM candidates WHERE id=?", (candidate_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Candidate not found: {candidate_id}")

        conn.execute(
            "UPDATE candidates SET lifecycle='promoted', updated_at=? WHERE id=?",
            (_now(), candidate_id),
        )
        conn.execute(
            "INSERT INTO lineage(kind, subject, detail, ts) VALUES (?, ?, ?, ?)",
            ("promote", candidate_id,
             json.dumps({"reason": reason, "action": "pin_path_b"}), _now()),
        )


# --------------------------------------------------------------------------- #
# ambiguous -> iteration
# --------------------------------------------------------------------------- #

def resolve_iteration(
    conn: sqlite3.Connection,
    candidate_id: str,
    skill_name: str,
    branch_key: str,
    new_impl_ref: str = "",
) -> None:
    """ambiguous 定为迭代：用新实现替换 branch 的 active_impl_ref，
    旧 active 移入 retained_impls，bump active_version，
    写 branch_versions 新记录 + lineage。

    Args:
        conn: SQLite 连接。
        candidate_id: 候选 ID（仅用于追溯）。
        skill_name: 所属 skill。
        branch_key: 所属 branch key。
        new_impl_ref: 新实现引用路径。

    Raises:
        ValueError: 候选或 branch 不存在。
    """
    with conn:
        cand = conn.execute(
            "SELECT id FROM candidates WHERE id=?", (candidate_id,)
        ).fetchone()
        if cand is None:
            raise ValueError(f"Candidate not found: {candidate_id}")

        new_impl = new_impl_ref

        branch = conn.execute(
            "SELECT * FROM branches WHERE skill_name=? AND key=?",
            (skill_name, branch_key),
        ).fetchone()
        if branch is None:
            raise ValueError(
                f"Branch not found: {skill_name}/{branch_key}"
            )

        old_active = branch["active_impl_ref"] or ""
        old_version = branch["active_version"] or 0
        new_version = old_version + 1

        # 旧 active 入 retained
        retained = json.loads(branch["retained_impls"]) if branch["retained_impls"] else []
        if old_active:
            retained.append({"impl_ref": old_active, "version": old_version})

        conn.execute(
            """UPDATE branches
               SET active_impl_ref=?, active_version=?, retained_impls=?
               WHERE skill_name=? AND key=?""",
            (new_impl, new_version, json.dumps(retained), skill_name, branch_key),
        )

        conn.execute(
            """INSERT INTO branch_versions
                   (skill_name, scope, branch_key, version, change, ts)
               VALUES (?, 'branch', ?, ?, ?, ?)""",
            (skill_name, branch_key, new_version,
             json.dumps({"candidate_id": candidate_id, "change": "iteration"}),
             _now()),
        )

        conn.execute(
            "INSERT INTO lineage(kind, subject, detail, ts) VALUES (?, ?, ?, ?)",
            ("iterate", f"{skill_name}/{branch_key}",
             json.dumps({
                 "candidate_id": candidate_id,
                 "new_impl": new_impl,
                 "old_impl": old_active,
                 "old_version": old_version,
                 "new_version": new_version,
             }), _now()),
        )


# --------------------------------------------------------------------------- #
# ambiguous -> keep_both（并列保留，不替换 active）
# --------------------------------------------------------------------------- #

def resolve_keep_both(
    conn: sqlite3.Connection,
    candidate_id: str,
    skill_name: str,
    branch_key: str,
    new_impl_ref: str,
) -> None:
    """ambiguous 定为并列保留：新实现进 retained_impls 不替换 active，
    记 branch_versions scope='branch' + lineage。

    Args:
        conn: SQLite 连接。
        candidate_id: 候选 ID（仅用于追溯）。
        skill_name: 所属 skill。
        branch_key: 所属 branch key。
        new_impl_ref: 新实现引用路径。

    Raises:
        ValueError: branch 不存在。
    """
    with conn:
        branch = conn.execute(
            "SELECT * FROM branches WHERE skill_name=? AND key=?",
            (skill_name, branch_key),
        ).fetchone()
        if branch is None:
            raise ValueError(
                f"Branch not found: {skill_name}/{branch_key}"
            )

        retained = json.loads(branch["retained_impls"]) if branch["retained_impls"] else []
        if not any(r.get("impl_ref") == new_impl_ref for r in retained):
            retained.append({"impl_ref": new_impl_ref, "version": 1})

        conn.execute(
            "UPDATE branches SET retained_impls=? WHERE skill_name=? AND key=?",
            (json.dumps(retained), skill_name, branch_key),
        )

        conn.execute(
            """INSERT INTO branch_versions
                   (skill_name, scope, branch_key, version, change, ts)
               VALUES (?, 'branch', ?, ?, ?, ?)""",
            (skill_name, branch_key, 0,
             json.dumps({
                 "candidate_id": candidate_id,
                 "change": "keep_both",
                 "new_impl": new_impl_ref,
             }), _now()),
        )

        conn.execute(
            "INSERT INTO lineage(kind, subject, detail, ts) VALUES (?, ?, ?, ?)",
            ("retain_impl", f"{skill_name}/{branch_key}",
             json.dumps({
                 "candidate_id": candidate_id,
                 "new_impl": new_impl_ref,
                 "action": "keep_both",
             }), _now()),
        )


# --------------------------------------------------------------------------- #
# 手动降级
# --------------------------------------------------------------------------- #

def deprecate(conn: sqlite3.Connection, skill_name: str, reason: str) -> None:
    """手动降级 skill：UPDATE status='deprecated', visibility='hidden', 写 lineage。

    Args:
        conn: SQLite 连接。
        skill_name: 要降级的 skill 名。
        reason: 降级原因（人工备注）。

    Raises:
        ValueError: skill 不存在。
    """
    with conn:
        skill = conn.execute(
            "SELECT name, status, visibility FROM skills WHERE name=?",
            (skill_name,),
        ).fetchone()
        if skill is None:
            raise ValueError(f"Skill not found: {skill_name}")

        old_status = skill["status"]
        old_visibility = skill["visibility"]

        conn.execute(
            "UPDATE skills SET status='deprecated', visibility='hidden' WHERE name=?",
            (skill_name,),
        )
        conn.execute(
            "INSERT INTO lineage(kind, subject, detail, ts) VALUES (?, ?, ?, ?)",
            ("deprecate", skill_name,
             json.dumps({
                 "reason": reason,
                 "old_status": old_status,
                 "old_visibility": old_visibility,
             }), _now()),
        )


# --------------------------------------------------------------------------- #
# 质量门控自动升级
# --------------------------------------------------------------------------- #

def auto_upgrade_quality(conn: sqlite3.Connection) -> list[str]:
    """质量门控：扫描 promoted skill 的 quality_rollup，按阈值自动升级 visibility。

    规则：
        reuse_count >= 3 且 success_rate >= 0.8 → hidden → searchable
        reuse_count >= 5 且 success_rate >= 0.9 → searchable → invokable_by_id
        绝不自动升到 mcp_exposed（需人审）。

    Returns:
        被升级的 skill 名字列表（升多少记多少）。
    """
    upgraded: list[str] = []

    rows = conn.execute("""
        SELECT s.name, s.visibility, q.reuse_count, q.success_rate
        FROM skills s
        JOIN quality_rollup q ON q.skill_name = s.name
        WHERE s.status = 'promoted'
    """).fetchall()

    # 收集升级，最后统一提交
    updates: list[tuple[str, str, str, int, float]] = []  # (name, from_vis, to_vis, reuse, success)

    for row in rows:
        name = row["name"]
        current = row["visibility"]
        reuse = row["reuse_count"] or 0
        success = row["success_rate"] or 0.0

        new_visibility: str | None = None

        # 高分升 invokable_by_id（不管当前是 hidden 还是 searchable）
        if reuse >= 5 and success >= 0.9:
            if current in ("hidden", "searchable"):
                new_visibility = "invokable_by_id"
        # 中分升 searchable（仅 hidden 起步）
        elif reuse >= 3 and success >= 0.8:
            if current == "hidden":
                new_visibility = "searchable"

        if new_visibility is not None:
            updates.append((name, current, new_visibility, reuse, success))

    if not updates:
        return upgraded

    with conn:
        for name, from_vis, to_vis, reuse, success in updates:
            conn.execute(
                "UPDATE skills SET visibility=? WHERE name=?",
                (to_vis, name),
            )
            conn.execute(
                "INSERT INTO lineage(kind, subject, detail, ts) VALUES (?, ?, ?, ?)",
                ("auto_upgrade", name,
                 json.dumps({
                     "from": from_vis,
                     "to": to_vis,
                     "reuse_count": reuse,
                     "success_rate": success,
                 }), _now()),
            )
            upgraded.append(name)

    return upgraded
