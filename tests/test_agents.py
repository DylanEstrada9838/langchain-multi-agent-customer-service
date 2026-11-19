"""Tests del registro de agentes, versionado YAML y factoría de LLM."""
import pytest

from src.agents import AGENT_BINDINGS, AgentSpec, list_versions, load_spec
from src.llm import LLMFactory, ModelConfig


def test_carga_specs_v1():
    for ver in ("v1", "v2", "v3"):
        for name in AGENT_BINDINGS:
            spec = load_spec(name, version=ver)
            assert isinstance(spec, AgentSpec)
            assert spec.name == name
            assert spec.version == ver
            assert "TechStore" in spec.system_prompt


def test_versionado_triaje_v1_vs_v2():
    versions = list_versions("triaje")
    assert "v1" in versions and "v2" in versions and "v3" in versions
    v1 = load_spec("triaje", "v1")
    v2 = load_spec("triaje", "v2")
    assert v1.system_prompt != v2.system_prompt
    assert v2.model_config.temperature == 0.0
    assert "múltiples intenciones" in v1.system_prompt
    assert "Precedencia en mensajes con varias intenciones" in v2.system_prompt


def test_version_inexistente_lanza_error():
    with pytest.raises(FileNotFoundError, match="v99"):
        load_spec("triaje", "v99")


def test_override_de_proveedor_y_modelo():
    spec = load_spec("qa", "v1", provider="anthropic", model_name="claude-sonnet-4-5")
    assert spec.model_config.provider == "anthropic"
    assert spec.model_config.model_name == "claude-sonnet-4-5"


def test_llm_factory_valida_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        LLMFactory.create(ModelConfig(provider="anthropic", model_name="claude-sonnet-4-5"))
