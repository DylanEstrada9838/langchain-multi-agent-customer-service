"""Paquete LLM: Strategy + Factory para instanciar modelos de cualquier proveedor en LangChain."""
from src.llm.factory import LLMFactory, ModelConfig

__all__ = ["LLMFactory", "ModelConfig"]
