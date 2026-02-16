"""Tests for setup and enhanced API functions."""

import os
from pathlib import Path

import pytest
import yaml

from opencontext.core.config import Config


@pytest.fixture
def config_env(tmp_path, monkeypatch):
    """Isolated config environment."""
    config_path = tmp_path / "config.yaml"
    db_path = tmp_path / "db" / "test.db"
    monkeypatch.setenv("OPENCONTEXT_CONFIG", str(config_path))
    monkeypatch.setenv("OPENCONTEXT_DB_PATH", str(db_path))
    # Clear provider API keys to isolate tests
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY",
                "GEMINI_API_KEY", "OPENCONTEXT_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path, config_path, db_path


class TestSetConfig:
    def test_set_new_key(self, config_env):
        _, config_path, _ = config_env
        Config.set_config("api_key", "sk-test-123")
        data = yaml.safe_load(config_path.read_text())
        assert data["api_key"] == "sk-test-123"

    def test_set_overwrites_existing(self, config_env):
        _, config_path, _ = config_env
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(yaml.dump({"api_key": "old", "llm_model": "x/y"}))
        Config.set_config("api_key", "new-key")
        data = yaml.safe_load(config_path.read_text())
        assert data["api_key"] == "new-key"
        assert data["llm_model"] == "x/y"  # preserved

    def test_set_creates_parent_dirs(self, tmp_path, monkeypatch):
        deep_path = tmp_path / "a" / "b" / "config.yaml"
        monkeypatch.setenv("OPENCONTEXT_CONFIG", str(deep_path))
        Config.set_config("llm_model", "deepseek/deepseek-chat")
        assert deep_path.exists()
        data = yaml.safe_load(deep_path.read_text())
        assert data["llm_model"] == "deepseek/deepseek-chat"


class TestSetupCheck:
    def test_not_initialized(self, config_env):
        from opencontext.api import setup_check
        result = setup_check()
        assert result["initialized"] is False
        assert result["has_api_key"] is False
        assert result["project_count"] == 0

    def test_initialized_no_key(self, config_env):
        from opencontext.api import setup_check, init
        _, config_path, _ = config_env
        init()
        result = setup_check()
        assert result["initialized"] is True
        assert result["db_exists"] is True
        assert result["has_api_key"] is False

    def test_initialized_with_key(self, config_env):
        from opencontext.api import setup_check, init
        init()
        Config.set_config("api_key", "sk-test")
        result = setup_check()
        assert result["has_api_key"] is True


class TestSetupConfig:
    def test_set_and_verify(self, config_env):
        from opencontext.api import setup_config
        result = setup_config("llm_model", "openai/gpt-4o-mini")
        assert result["status"] == "ok"
        cfg = Config.load()
        assert cfg.llm_model == "openai/gpt-4o-mini"


class TestSetupDiscover:
    def test_returns_list(self, config_env):
        from opencontext.api import setup_discover
        # May return empty list in test env, but should not error
        result = setup_discover()
        assert isinstance(result, list)


class TestSyncProjectsUpdated:
    def test_sync_returns_projects_updated_key(self, config_env):
        from opencontext.api import init, sync
        init()
        result = sync(summarize=False)
        assert "projects_updated" in result
        assert isinstance(result["projects_updated"], list)
