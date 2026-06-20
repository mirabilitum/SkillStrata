"""T0.1 — distiller 数据目录布局。

运行时数据目录（全部 gitignore）。索引层 = indexes/（向量库 vectors/ 只是其一种实现，
不替代索引层，见 Codex 审核）。
"""
from __future__ import annotations

from pathlib import Path

DATA_DIRS = (
    "traces",      # RawToolEvent / EnrichedToolEvent
    "artifacts",   # 输入输出样本、代码快照、stdout/stderr（重放只用拷贝）
    "candidates",  # 未转正候选
    "skills",      # 已转正能力（每能力含 branches/ fixtures/）
    "indexes",     # 契约签名索引等
    "vectors",     # 向量库（indexes 的一种实现）
    "reports",     # 指标与批处理报告
)
DB_FILENAME = "meta.sqlite"


def default_data_dir() -> Path:
    return Path(".distiller-data")


def ensure_layout(root: Path | str) -> Path:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    for d in DATA_DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)
    return root


def db_path(root: Path | str) -> Path:
    return Path(root) / DB_FILENAME
