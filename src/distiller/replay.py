"""M3 · Replay Gate — 隔离沙箱重放候选脚本。

对照：技术栈与运行时-canonical §3.2 / 落地实现规划 T3.1。

职责：
  - replay() 在 temp 目录（拷贝输入）中通过 subprocess 运行候选 Python 脚本。
  - 绝不碰工作区（Sandbox Workspace Touch=0）。
  - 返回结构化结果（exit_code / stdout / stderr / duration_ms），不解析输出内容。
  - 只用标准库（subprocess + tempfile）。

使用示例：
    result = replay("./script.py", "/path/to/input.pdf", timeout=30)
    # -> {"exit_code": 0, "stdout_md": "...", "stderr": "...", "duration_ms": 1234}
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# 重放沙箱
# ---------------------------------------------------------------------------

_REPLAY_TIMEOUT_SEC = 30


def replay(
    impl_path: str,
    input_path: str,
    *,
    timeout: int = _REPLAY_TIMEOUT_SEC,
    cwd: str | None = None,
) -> dict:
    """在隔离 temp 目录中重放候选实现。

    Parameters
    ----------
    impl_path : str
        候选 Python 脚本的路径（将被复制到沙箱中执行）。
    input_path : str
        输入文件的路径（将被复制到沙箱中供脚本读取）。
    timeout : int
        子进程超时秒数（默认 30）。
    cwd : str | None
        可选的工作目录（用于定位依赖，默认 None=使用 impl_path 所在目录；
        MVP 暂不使用，保留供将来 uv venv 隔离场景使用）。

    Returns
    -------
    dict
        {
            "exit_code": int | None,   # 进程退出码；超时为 None
            "stdout_md": str,          # 标准输出（预期为 markdown）
            "stderr": str,             # 标准错误
            "duration_ms": int,        # 实际执行耗时（毫秒）
        }

    Notes
    -----
    - 沙箱目录与工作区完全隔离，绝不触及项目工作区文件。
    - timeout 到期后 kill 整个进程组，exit_code 返回 None。
    """
    impl_path = Path(impl_path).resolve()
    input_path = Path(input_path).resolve()

    if not impl_path.is_file():
        raise FileNotFoundError(f"impl_path not found: {impl_path}")
    if not input_path.is_file():
        raise FileNotFoundError(f"input_path not found: {input_path}")

    # 1. 在 temp 中创建工作沙箱
    sandbox_root = Path(tempfile.mkdtemp(prefix="distiller-replay-"))
    try:
        impl_copy = sandbox_root / impl_path.name
        input_copy = sandbox_root / input_path.name

        shutil.copy2(str(impl_path), str(impl_copy))
        shutil.copy2(str(input_path), str(input_copy))

        # 2. 运行脚本
        start = time.perf_counter()
        try:
            proc = subprocess.run(
                [sys.executable, str(impl_copy), str(input_copy)],
                cwd=str(sandbox_root) if cwd is None else str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            exit_code = proc.returncode
            stdout_md = proc.stdout
            stderr = proc.stderr
        except subprocess.TimeoutExpired:
            exit_code = None
            stdout_md = ""
            stderr = f"TIMEOUT after {timeout}s"
        except Exception as exc:  # noqa: BLE001
            exit_code = -1
            stdout_md = ""
            stderr = f"REPLAY_CRASH: {exc}"

        duration_ms = int((time.perf_counter() - start) * 1000)

        return {
            "exit_code": exit_code,
            "stdout_md": stdout_md,
            "stderr": stderr,
            "duration_ms": duration_ms,
        }
    finally:
        # 3. 清理沙箱
        shutil.rmtree(sandbox_root, ignore_errors=True)
