"""Paquete LLM: Strategy + Factory para instanciar modelos de cualquier proveedor en LangChain."""
from src.llm.factory import LLMFactory, ModelConfig
from src.llm.pricing import MODEL_PRICING_PER_1M, calculate_cost

__all__ = ["LLMFactory", "ModelConfig", "MODEL_PRICING_PER_1M", "calculate_cost"]
