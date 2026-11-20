"""Tests for harness/config.py - building and validating Config from environment variables."""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness.src.config import Config, ConfigError  # noqa: E402

REQUIRED = {
    "IMAP_HOST": "imap.example.com",
    "IMAP_USER": "biuro@example.com",
    "IMAP_PASSWORD": "tajne",
    "AI_API_KEY": "sk-ant-xyz",
}


def env(**overrides) -> dict:
    merged = dict(REQUIRED)
    merged.update(overrides)
    return merged


def test_from_env_happy_path_full():
    cfg = Config.from_env(env(
        IMAP_PORT="143", IMAP_USE_SSL="false",
        IMAP_DRAFTS_FOLDER="Szkice",
        AI_PROVIDER="claude", AI_MODEL="claude-sonnet-5-5", AI_MAX_TOKENS="500",
        FROM_ADDRESS="info@example.com",
        API_HOST="0.0.0.0", API_PORT="9000",
    ))
    assert cfg.imap_host == "imap.example.com"
    assert cfg.imap_port == 143
    assert cfg.imap_use_ssl is False
    assert cfg.drafts_folder == "Szkice"
    assert cfg.ai_provider == "claude"
    assert cfg.ai_model == "claude-sonnet-5-5"
    assert cfg.ai_max_tokens == 500
    assert cfg.from_address == "info@example.com"
    assert cfg.api_host == "0.0.0.0"
    assert cfg.api_port == 9000


def test_from_env_happy_path_defaults():
    cfg = Config.from_env(env())
    assert cfg.imap_port == 993
    assert cfg.imap_use_ssl is True
    assert cfg.drafts_folder == "Drafts"
    assert cfg.ai_provider == "claude"
    assert cfg.ai_model == "claude-sonnet-5-5"
    assert cfg.ai_max_tokens == 3000
    assert cfg.from_address == REQUIRED["IMAP_USER"]
    assert cfg.api_host == "127.0.0.1"
    assert cfg.api_port == 8765


@pytest.mark.parametrize("missing", ["IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD", "AI_API_KEY"])
def test_from_env_missing_required_raises(missing):
    bad = dict(REQUIRED)
    bad.pop(missing)
    with pytest.raises(ConfigError):
        Config.from_env(bad)


@pytest.mark.parametrize("blank", ["", "   "])
def test_from_env_blank_required_raises(blank):
    with pytest.raises(ConfigError):
        Config.from_env(env(IMAP_HOST=blank))


def test_from_env_empty_mapping_raises():
    with pytest.raises(ConfigError):
        Config.from_env({})


@pytest.mark.parametrize("raw", ["not-a-number", "12.5"])
def test_from_env_bad_imap_port_type(raw):
    with pytest.raises(ConfigError):
        Config.from_env(env(IMAP_PORT=raw))


def test_from_env_blank_imap_port_uses_default():
    cfg = Config.from_env(env(IMAP_PORT="   "))
    assert cfg.imap_port == 993


@pytest.mark.parametrize("raw", ["0", "-1"])
def test_from_env_non_positive_imap_port_raises(raw):
    with pytest.raises(ConfigError):
        Config.from_env(env(IMAP_PORT=raw))


@pytest.mark.parametrize("raw", ["0", "-5", "abc"])
def test_from_env_bad_api_port_raises(raw):
    with pytest.raises(ConfigError):
        Config.from_env(env(API_PORT=raw))


@pytest.mark.parametrize("raw", ["0", "-100", "abc"])
def test_from_env_bad_max_tokens_raises(raw):
    with pytest.raises(ConfigError):
        Config.from_env(env(AI_MAX_TOKENS=raw))


def test_from_env_bad_ai_provider_raises():
    with pytest.raises(ConfigError):
        Config.from_env(env(AI_PROVIDER="mistral"))


def test_from_env_openai_without_model_raises():
    with pytest.raises(ConfigError):
        Config.from_env(env(AI_PROVIDER="openai"))


def test_from_env_openai_with_model_succeeds():
    cfg = Config.from_env(env(AI_PROVIDER="openai", AI_MODEL="gpt-5"))
    assert cfg.ai_provider == "openai"
    assert cfg.ai_model == "gpt-5"


@pytest.mark.parametrize("raw,expected", [
    ("1", True), ("true", True), ("True", True), ("yes", True), ("tak", True),
    ("0", False), ("false", False), ("no", False), ("nonsense", False),
])
def test_from_env_bool_parsing_truth_table(raw, expected):
    cfg = Config.from_env(env(IMAP_USE_SSL=raw))
    assert cfg.imap_use_ssl is expected


def test_from_env_bool_empty_uses_default():
    cfg = Config.from_env(env(IMAP_USE_SSL=""))
    assert cfg.imap_use_ssl is True


def test_from_env_strips_whitespace():
    cfg = Config.from_env(env(IMAP_HOST="  imap.example.com  "))
    assert cfg.imap_host == "imap.example.com"


def test_from_env_works_with_real_os_environ(monkeypatch):
    for key, value in REQUIRED.items():
        monkeypatch.setenv(key, value)
    cfg = Config.from_env(os.environ)
    assert cfg.imap_host == REQUIRED["IMAP_HOST"]


def test_config_is_frozen():
    cfg = Config.from_env(env())
    with pytest.raises(Exception):
        cfg.imap_host = "other.example.com"
