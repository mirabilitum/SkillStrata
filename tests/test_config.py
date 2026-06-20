"""T0.3 config 解析链测试（含 judge 凭证 offline 兜底）。"""
from pathlib import Path

from distiller import config


def test_judge_offline_when_no_key():
    cfg = config.load(env={})  # 无 ANTHROPIC_API_KEY
    assert cfg.judge.mode == "offline"
    assert cfg.judge.api_key == ""
    assert cfg.judge.tier == "haiku"


def test_judge_online_from_env():
    cfg = config.load(env={"ANTHROPIC_API_KEY": "sk-xxx"})
    assert cfg.judge.mode == "online"
    assert cfg.judge.api_key == "sk-xxx"


def test_explicit_key_beats_env():
    cfg = config.load(overrides={"api_key": "explicit"},
                      env={"ANTHROPIC_API_KEY": "from-env"})
    assert cfg.judge.api_key == "explicit"


def test_precedence_override_beats_file(tmp_path):
    f = tmp_path / "c.env"
    f.write_text("data_dir=from_file\nbatch_size=8\n", encoding="utf-8")
    cfg = config.load(overrides={"data_dir": "from_override"},
                      env={}, config_file=f)
    assert cfg.data_dir == Path("from_override")  # override 赢
    assert cfg.batch_size == 8                     # file 提供，override 没给


def test_defaults():
    cfg = config.load(env={})
    assert cfg.reuse_frequency_n == 3
    assert cfg.batch_size == 16
