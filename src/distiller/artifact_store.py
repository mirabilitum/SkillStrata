"""Artifact Store — 把 promoted skill 的实现与 fixture 快照到数据目录。

阶段 2（个人通用版演进）：当前 promoted skill 的 `active_impl_ref` 指向原工作区
（如 `.cc-smoke/tools/html_to_md.py`），删掉工作区后 skill 元数据还在但不可复用。
本模块在 promote 时把实现脚本 + 最小 fixture 复制到数据目录内，并更新引用为
data-dir 相对路径，实现"promoted skill 不依赖原工作区"。

目标结构（data-dir 根）：
  skills/<name>/<branch>/v<version>/
    impl.py
    manifest.json
    fixtures/
      input.<ext>
      output.<ext>

只依赖标准库，不引入第三方包。
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_skill_dir(
    data_root: Path | str,
    skill_name: str,
    branch_key: str,
    version: int,
) -> Path:
    return Path(data_root) / "skills" / skill_name / branch_key / f"v{version}"


def snapshot_promoted(
    data_root: Path | str,
    skill_name: str,
    branch_key: str,
    version: int,
    *,
    impl_path: Path | str,
    input_fixture_path: Optional[Path | str] = None,
    output_text: Optional[str] = None,
    output_ext: str = "md",
) -> tuple[str, str]:
    """把 promoted skill 快照到数据目录，返回 (impl_ref, fixtures_ref)——均为 data-dir 相对路径。

    Parameters
    ----------
    data_root : Path | str
        数据目录根（如 `.distiller-data` 或 `.demo-smoke-data`）。
    skill_name : str
        skill 名（如 `document-to-markdown`）。
    branch_key : str
        分支 key（如 `html`）。
    version : int
        版本号（new_skill=1，iteration 递增）。
    impl_path : Path | str
        要快照的实现脚本**绝对路径**（如 `.cc-smoke/tools/html_to_md.py`）。
    input_fixture_path : Path | str, optional
        输入 fixture 的绝对路径（用于 replay 验证），不传则跳过。
    output_text : str, optional
        重放产出的文本内容（写入 `fixtures/output.<ext>`），不传则跳过。
    output_ext : str
        输出 fixture 扩展名（默认 `md`）。

    Returns
    -------
    tuple[str, str]
        (active_impl_ref, fixtures_ref) 为 data-dir 相对路径，可直接写回
        branches 表对应列。不覆盖 fixture 时 fixtures_ref 为空串。
    """
    root = Path(data_root)
    skill_dir = _resolve_skill_dir(root, skill_name, branch_key, version)
    fixtures_dir = skill_dir / "fixtures"

    # 幂等：目录已存在 → 先清（避免残余旧 fixture 污染）。
    if skill_dir.exists():
        shutil.rmtree(skill_dir)
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    # --- 复制实现脚本 ---
    src = Path(impl_path)
    dest_impl = skill_dir / "impl.py"
    shutil.copy2(str(src), str(dest_impl))

    # --- 输入 fixture ---
    fixture_input_name = ""
    if input_fixture_path is not None:
        ip = Path(input_fixture_path)
        fixture_input_name = f"input{ip.suffix}" if ip.suffix else "input"
        shutil.copy2(str(ip), str(fixtures_dir / fixture_input_name))

    # --- 输出 fixture（从 replay stdout 写入）---
    fixture_output_name = ""
    if output_text is not None:
        fixture_output_name = f"output.{output_ext.lstrip('.')}"
        (fixtures_dir / fixture_output_name).write_text(
            output_text, encoding="utf-8"
        )

    # --- manifest.json ---
    manifest = {
        "skill_name": skill_name,
        "branch_key": branch_key,
        "version": version,
        "snapshot_at": _now(),
        "impl": "impl.py",
        "fixtures": {
            "input": fixture_input_name or None,
            "output": fixture_output_name or None,
        },
    }
    (skill_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # --- 计算 data-dir 相对路径 ---
    # impl_ref: skills/<name>/<branch>/v<version>/impl.py
    impl_rel = skill_dir.relative_to(root).as_posix() + "/impl.py"
    fix_rel = ""
    if fixture_input_name:
        fix_rel = (fixtures_dir / fixture_input_name).relative_to(root).as_posix()
    elif fixture_output_name:
        fix_rel = (fixtures_dir / fixture_output_name).relative_to(root).as_posix()

    return impl_rel, fix_rel
