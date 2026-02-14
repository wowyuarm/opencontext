"""Configuration for OpenContext."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


_DEFAULT_DB_PATH = "~/.opencontext/db/opencontext.db"
_DEFAULT_CONFIG_PATH = "~/.opencontext/config.yaml"

# Model prefix → env var name for API key
_MODEL_ENV_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gpt": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "dashscope": "DASHSCOPE_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "moonshot": "MOONSHOT_API_KEY",
    "groq": "GROQ_API_KEY",
    "zhipu": "ZHIPUAI_API_KEY",
    "glm": "ZHIPUAI_API_KEY",
}


@dataclass
class Config:
    # Database
    db_path: str = _DEFAULT_DB_PATH

    # LLM
    llm_model: str = "anthropic/claude-haiku-4-5-20251001"
    llm_timeout: float = 60.0
    api_key: Optional[str] = None

    # Session discovery
    # (currently Claude Code only; Codex/Gemini support planned)

    # Summarization
    summary_max_chars: int = 500

    @classmethod
    def load(cls, path: Optional[str] = None) -> Config:
        """Load config from YAML file, falling back to defaults."""
        config_path = Path(
            path or os.getenv("OPENCONTEXT_CONFIG", _DEFAULT_CONFIG_PATH)
        ).expanduser()

        data: dict = {}
        if config_path.exists():
            try:
                with open(config_path) as f:
                    data = yaml.safe_load(f) or {}
            except Exception:
                pass

        cfg = cls()

        if "db_path" in data:
            cfg.db_path = data["db_path"]
        if "llm_model" in data:
            cfg.llm_model = data["llm_model"]
        if "api_key" in data:
            cfg.api_key = data["api_key"]
        if "llm_timeout" in data:
            cfg.llm_timeout = float(data["llm_timeout"])
        if "summary_max_chars" in data:
            cfg.summary_max_chars = int(data["summary_max_chars"])

        # Environment overrides
        if env_model := os.getenv("OPENCONTEXT_LLM_MODEL"):
            cfg.llm_model = env_model
        if env_db := os.getenv("OPENCONTEXT_DB_PATH"):
            cfg.db_path = env_db
        if env_key := os.getenv("OPENCONTEXT_API_KEY"):
            cfg.api_key = env_key

        return cfg

    @property
    def resolved_db_path(self) -> Path:
        return Path(self.db_path).expanduser()

    def inject_api_key(self) -> None:
        """Inject api_key into the environment variable litellm expects.

        If api_key is set in config, detect the correct env var name
        from the model string and set it. This lets users configure
        a single api_key without knowing litellm internals.
        """
        if not self.api_key:
            return

        env_var = self._env_var_for_model()
        if env_var:
            os.environ.setdefault(env_var, self.api_key.strip())

    def _env_var_for_model(self) -> Optional[str]:
        """Determine the environment variable name for the current model."""
        model_lower = self.llm_model.lower()
        for keyword, env_var in _MODEL_ENV_KEYS.items():
            if keyword in model_lower:
                return env_var
        return None

    def check_api_key(self) -> Optional[str]:
        """Check if the required API key is available.

        Returns None if OK, or an error message string.
        """
        env_var = self._env_var_for_model()
        if not env_var:
            return f"Unknown provider for model '{self.llm_model}'"

        # Config api_key counts
        if self.api_key:
            return None

        # Check environment
        if os.getenv(env_var):
            return None

        return f"Missing API key: set 'api_key' in config.yaml or export {env_var}"
