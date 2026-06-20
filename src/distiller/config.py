"""T0.3 — 配置加载。

解析链：CLI flag > env > config 文件 > 内置默认。
judge 凭证解析链：显式 key/config > env ANTHROPIC_API_KEY > offline 模式（不假设能继承 CC 会话凭证）。
配置文件用极简 key=value（.env 风格），MVP 不引入 toml 依赖。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class JudgeConfig:
    tier: str = "haiku"          # 默认便宜档
    escalate_tier: str = "sonnet"  # 仅 ambiguous 疑难升档
    provider: str = "anthropic"
    api_key: str = ""            # 解析后填入；空 = offline
    mode: str = "online"         # online | offline


@dataclass
class Config:
    data_dir: Path = field(default_factory=lambda: Path(".distiller-data"))
    judge: JudgeConfig = field(default_factory=JudgeConfig)
    batch_size: int = 16
    reuse_frequency_n: int = 3       # N≥3 统计晋升
    # 注：Output Gate 文本覆盖阈值按 input_profile 分支化，此处仅默认兜底值
    text_coverage_min_default: float = 0.9


def _resolve_api_key(explicit: Optional[str], env: dict) -> tuple[str, str]:
    """凭证解析链。CC 登录态/订阅 ≠ 可复用 API key，故 offline 是合法终态。"""
    if explicit:
        return explicit, "online"
    key = env.get("ANTHROPIC_API_KEY", "")
    if key:
        return key, "online"
    return "", "offline"


def _read_config_file(path: Optional[Path]) -> dict:
    result: dict = {}
    if not path:
        return result
    p = Path(path)
    if not p.exists():
        return result
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        result[k.strip()] = v.strip()
    return result


def load(
    overrides: Optional[dict] = None,
    env: Optional[dict] = None,
    config_file: Optional[Path] = None,
) -> Config:
    env = env if env is not None else dict(os.environ)
    overrides = overrides or {}
    file_cfg = _read_config_file(config_file)

    def pick(key: str, default):
        if key in overrides and overrides[key] is not None:
            return overrides[key]
        if key in file_cfg:
            return file_cfg[key]
        return default

    cfg = Config()
    cfg.data_dir = Path(pick("data_dir", cfg.data_dir))
    cfg.batch_size = int(pick("batch_size", cfg.batch_size))
    cfg.reuse_frequency_n = int(pick("reuse_frequency_n", cfg.reuse_frequency_n))

    explicit_key = overrides.get("api_key") or file_cfg.get("api_key")
    key, mode = _resolve_api_key(explicit_key, env)
    cfg.judge.api_key = key
    cfg.judge.mode = mode
    cfg.judge.tier = pick("judge_tier", cfg.judge.tier)
    cfg.judge.escalate_tier = pick("judge_escalate_tier", cfg.judge.escalate_tier)
    return cfg
