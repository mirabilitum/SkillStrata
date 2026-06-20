"""T0.3 config 解析链测试（含 env>file、judge 凭证 offline/secret-store）。"""
from pathlib import Path

from distiller import config


def test_judge_offline_when_no_key():
    cfg = config.load(env={})
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


def test_provider_secret_store_tier():
    cfg = config.load(env={}, secret_resolver=lambda p: "from-store")
    assert cfg.judge.mode == "online"
    assert cfg.judge.api_key == "from-store"


def test_env_beats_file_for_normal_options(tmp_path):
    f = tmp_path / "c.env"
    f.write_text("batch_size=8\n", encoding="utf-8")
    cfg = config.load(env={"DISTILLER_BATCH_SIZE": "32"}, config_file=f)
    assert cfg.batch_size == 32  # env 赢 file


def test_override_beats_env_and_file(tmp_path):
    f = tmp_path / "c.env"
    f.write_text("data_dir=from_file\n", encoding="utf-8")
    cfg = config.load(overrides={"data_dir": "from_override"},
                      env={"DISTILLER_DATA_DIR": "from_env"}, config_file=f)
    assert cfg.data_dir == Path("from_override")


def test_defaults():
    cfg = config.load(env={})
    assert cfg.reuse_frequency_n == 3
    assert cfg.batch_size == 16
