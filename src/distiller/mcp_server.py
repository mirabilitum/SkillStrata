"""M6a — MCP server 核心逻辑（纯函数，不引入 mcp 包）。

用 stdio JSON-RPC 模拟；所有函数为纯读操作，不改任何状态。
暴露给 MCP transport 层的接口：list_promoted_skills / search_capability /
describe_capability / run_capability。

对照设计：技术栈与运行时 §4（promoted≠exposed）、契约引擎 §3。
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from . import observe


def _try_json(val: Any) -> Any:
    """尝试解析 JSON 字符串，失败则原样返回。"""
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return val
    return val


def _parse_skill_row(d: dict) -> dict:
    """解析 skill 行中的 JSON 字段。"""
    for field in ("contract", "tags", "quality", "host_native"):
        d[field] = _try_json(d.get(field))
    return d


def _parse_branch_rows(branches: list[dict]) -> list[dict]:
    """解析 branches 行中的 JSON 字段。"""
    for b in branches:
        for field in ("retained_impls", "requires_host_capability"):
            b[field] = _try_json(b.get(field))
    return branches


def _parse_contract_signature_rows(css: list[dict]) -> list[dict]:
    """解析 contract_signatures 行中的 JSON 字段。"""
    for cs in css:
        for field in ("contract_json", "behavior_signature_json", "branch_identity_json"):
            cs[field] = _try_json(cs.get(field))
    return css


# --------------------------------------------------------------------------- #
# MCP 基础工具
# --------------------------------------------------------------------------- #

def list_promoted_skills(conn: sqlite3.Connection) -> list[dict]:
    """列出所有 promoted 且 visibility 达标的 skill，供 MCP tool 注册。

    只返回 status='promoted' AND visibility IN ('invokable_by_id','mcp_exposed')。
    每条记录含 name / purpose / contract / when_to_use（L1 渐进披露）。
    """
    rows = conn.execute(
        """
        SELECT name, purpose, contract, when_to_use
        FROM skills
        WHERE status = 'promoted'
          AND visibility IN ('invokable_by_id', 'mcp_exposed')
        ORDER BY name
        """,
    ).fetchall()
    return [_parse_skill_row(dict(r)) for r in rows]


def search_capability(conn: sqlite3.Connection, query: str) -> list[dict]:
    """按 purpose / when_to_use / tags / name / 契约摘要 模糊匹配，返回候选 skill 列表。

    只在 promoted 技能中搜索，排除 visibility='hidden' 的项。
    注意 promoted != exposed：搜到的技能不一定是 MCP 一等 tool。
    """
    like = f"%{query}%"
    rows = conn.execute(
        """
        SELECT DISTINCT s.name, s.purpose, s.contract, s.when_to_use,
                        s.tags, s.visibility, s.quality
        FROM skills s
        LEFT JOIN contract_signatures cs ON cs.skill_name = s.name
        WHERE s.status = 'promoted'
          AND s.visibility != 'hidden'
          AND (
              s.purpose LIKE ?
              OR s.when_to_use LIKE ?
              OR cs.contract_json LIKE ?
              OR s.tags LIKE ?
              OR s.name LIKE ?
          )
        ORDER BY s.name
        """,
        (like, like, like, like, like),
    ).fetchall()
    return [_parse_skill_row(dict(r)) for r in rows]


def describe_capability(conn: sqlite3.Connection, skill_name: str) -> dict:
    """返回 skill 详情：调 observe.show_skill 并解析 JSON 字段。

    未找到时返回 {}。
    """
    detail = observe.show_skill(conn, skill_name)
    if not detail:
        return {}

    detail = _parse_skill_row(detail)
    detail["branches"] = _parse_branch_rows(detail.get("branches", []))
    detail["contract_signatures"] = _parse_contract_signature_rows(
        detail.get("contract_signatures", [])
    )
    return detail


def run_capability(
    conn: sqlite3.Connection, skill_name: str, **inputs: Any
) -> dict:
    """返回调用指令（MVP 不实际执行，仅返回契约 + active branch impl_ref）。

    与 MCP 调用语义一致的可见性过滤（promoted≠exposed，复审 P2）：
    只暴露 status='promoted' 且 visibility IN ('invokable_by_id','mcp_exposed') 的技能。
    hidden / deprecated 一律返回 {}，不泄露内部能力元数据与 impl_ref。
    如将来要 by-id 调用 hidden skill，需显式鉴权入口，而非 MCP 默认 run。

    未找到 / 不可暴露时返回 {}。
    """
    skill = conn.execute(
        """
        SELECT name, purpose, contract, when_to_use
        FROM skills
        WHERE name = ?
          AND status = 'promoted'
          AND visibility IN ('invokable_by_id', 'mcp_exposed')
        """,
        (skill_name,),
    ).fetchone()
    if skill is None:
        return {}

    result = _parse_skill_row(dict(skill))

    # 取 active branch
    branch = conn.execute(
        """
        SELECT key, active_impl_ref, active_version
        FROM branches
        WHERE skill_name = ?
        ORDER BY active_version DESC
        LIMIT 1
        """,
        (skill_name,),
    ).fetchone()
    result["active_branch"] = dict(branch) if branch else {}
    result["inputs"] = inputs
    result[
        "instruction"
    ] = "调用方可按 contract 结构传入参数，impl_ref 指向具体实现文件。"
    return result
