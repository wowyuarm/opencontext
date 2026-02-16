"""Tests for opencontext.core.config — Config loading, API key injection."""

import os
from pathlib import Path

import pytest
import yaml

from opencontext.core.config import Config


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """Set up a temp config directory."""
    config_path = tmp_path / "config.yaml"
    monkeypatch.setenv("OPENCONTEXT_CONFIG", str(config_path))
    return tmp_path


def _write_config(path: Path, data: dict):
    config_file = path / "config.yaml"
    config_file.write_text(yaml.dump(data))
    return config_file


class TestConfigLoad:
    def test_defaults(self, config_dir):
        cfg = Config.load()
        assert "anthropic" in cfg.llm_model or "claude" in cfg.llm_model
        assert cfg.api_key is None
        assert cfg.llm_timeout == 60.0

    def test_load_from_yaml(self, config_dir):
        _write_config(config_dir, {
            "llm_model": "deepseek/deepseek-chat",
            "api_key": "sk-test-123",
            "llm_timeout": 30.0,
            "summary_max_chars": 300,
        })
        cfg = Config.load()
        assert cfg.llm_model == "deepseek/deepseek-chat"
        assert cfg.api_key == "sk-test-123"
        assert cfg.llm_timeout == 30.0
        assert cfg.summary_max_chars == 300

    def test_env_overrides_yaml(self, config_dir, monkeypatch):
        _write_config(config_dir, {"llm_model": "deepseek/deepseek-chat"})
        monkeypatch.setenv("OPENCONTEXT_LLM_MODEL", "openai/gpt-4")
        cfg = Config.load()
        assert cfg.llm_model == "openai/gpt-4"

    def test_env_override_db_path(self, config_dir, monkeypatch):
        monkeypatch.setenv("OPENCONTEXT_DB_PATH", "/custom/db.sqlite")
        cfg = Config.load()
        assert cfg.db_path == "/custom/db.sqlite"

    def test_missing_config_file(self, config_dir):
        # No config file created — should use defaults without error
        cfg = Config.load()
        assert cfg.llm_model is not None


class TestResolvedDbPath:
    def test_expands_tilde(self):
        cfg = Config(db_path="~/test.db")
        assert "~" not in str(cfg.resolved_db_path)


class TestApiKeyInjection:
    def test_inject_deepseek_key(self, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        cfg = Config(llm_model="deepseek/deepseek-chat", api_key="sk-deep-123")
        cfg.inject_api_key()
        assert os.environ.get("DEEPSEEK_API_KEY") == "sk-deep-123"

    def test_inject_strips_whitespace(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        cfg = Config(llm_model="anthropic/claude-3", api_key="sk-abc\r\n")
        cfg.inject_api_key()
        assert os.environ.get("ANTHROPIC_API_KEY") == "sk-abc"

    def test_no_inject_when_no_key(self, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        cfg = Config(llm_model="deepseek/deepseek-chat", api_key=None)
        cfg.inject_api_key()
        assert os.environ.get("DEEPSEEK_API_KEY") is None

    def test_setdefault_does_not_overwrite(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "existing-key")
        cfg = Config(llm_model="deepseek/deepseek-chat", api_key="new-key")
        cfg.inject_api_key()
        assert os.environ.get("DEEPSEEK_API_KEY") == "existing-key"


class TestCheckApiKey:
    def test_ok_with_config_key(self):
        cfg = Config(llm_model="deepseek/deepseek-chat", api_key="sk-123")
        assert cfg.check_api_key() is None

    def test_ok_with_env_key(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env")
        cfg = Config(llm_model="deepseek/deepseek-chat")
        assert cfg.check_api_key() is None

    def test_missing_key(self, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        cfg = Config(llm_model="deepseek/deepseek-chat")
        result = cfg.check_api_key()
        assert result is not None
        assert "DEEPSEEK_API_KEY" in result

    def test_unknown_provider(self):
        cfg = Config(llm_model="unknown-provider/model")
        result = cfg.check_api_key()
        assert result is not None
        assert "Unknown" in result


class TestModelEnvMapping:
    @pytest.mark.parametrize("model,expected_env", [
        ("deepseek/deepseek-chat", "DEEPSEEK_API_KEY"),
        ("anthropic/claude-3", "ANTHROPIC_API_KEY"),
        ("openai/gpt-4", "OPENAI_API_KEY"),
        ("gemini/gemini-pro", "GEMINI_API_KEY"),
        ("groq/llama-3", "GROQ_API_KEY"),
    ])
    def test_env_var_mapping(self, model, expected_env):
        cfg = Config(llm_model=model)
        assert cfg._env_var_for_model() == expected_env
