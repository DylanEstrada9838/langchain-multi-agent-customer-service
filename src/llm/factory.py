"""Factory Pattern para instanciar modelos de cualquier proveedor en LangChain."""
import os
from dataclasses import dataclass, replace

from langchain.chat_models import init_chat_model

from src import config

_API_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google_genai": "GOOGLE_API_KEY",
}


@dataclass(frozen=True)
class ModelConfig:
    provider: str = config.DEFAULT_LLM_PROVIDER
    model_name: str = config.DEFAULT_LLM_MODEL
    temperature: float = config.DEFAULT_LLM_TEMPERATURE
    max_tokens: int = config.DEFAULT_LLM_MAX_TOKENS
    timeout: int = config.DEFAULT_LLM_TIMEOUT

    def with_overrides(self, **kwargs) -> "ModelConfig":
        return replace(self, **{k: v for k, v in kwargs.items() if v is not None})


class LLMFactory:
    @staticmethod
    def create(cfg: ModelConfig | None = None):
        cfg = cfg or ModelConfig()
        env_var = _API_KEYS.get(cfg.provider)
        if env_var and not os.getenv(env_var):
            raise RuntimeError(f"Falta '{env_var}' en .env para el proveedor '{cfg.provider}'.")
        return init_chat_model(
            model=cfg.model_name,
            model_provider=cfg.provider,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            timeout=cfg.timeout,
        )
