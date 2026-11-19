"""Cálculo de coste financiero (USD) basado en tokens de entrada y salida por modelo."""

# Precios oficiales por 1 millón de tokens (USD)
MODEL_PRICING_PER_1M: dict[str, dict[str, float]] = {
    # OpenAI
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    # Anthropic
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
    # Fallback por defecto (asume gpt-4o-mini)
    "default": {"input": 0.15, "output": 0.60},
}


def calculate_cost(model_name: str | None, input_tokens: int, output_tokens: int) -> float:
    """Calcula el coste en USD para una llamada con input y output tokens."""
    rates = MODEL_PRICING_PER_1M.get(model_name or "", MODEL_PRICING_PER_1M["default"])
    cost = (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000.0
    return round(cost, 6)
