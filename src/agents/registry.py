"""Registro y factoría de agentes con versionado YAML y soporte multi-proveedor."""
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Type

import yaml
from langchain.agents import create_agent
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from src import config
from src.llm import LLMFactory, ModelConfig
from src.pipeline.context import TicketContext
from src.schemas.outputs import BorradorRespuesta, ClasificacionTicket, EvaluacionQA
from src.tools import CONSULTAS_TOOLS, DEVOLUCIONES_TOOLS, QA_TOOLS, SOPORTE_TOOLS, TRIAJE_TOOLS

SPECS_DIR = Path(__file__).resolve().parent / "specs"
ACTIVE_VERSIONS_PATH = Path(__file__).resolve().parent / "active_versions.yaml"

# Mapa central: nombre_agente -> (herramientas, esquema_salida)
AGENT_BINDINGS: dict[str, tuple[list[BaseTool], Type[BaseModel]]] = {
    "triaje": (TRIAJE_TOOLS, ClasificacionTicket),
    "devoluciones": (DEVOLUCIONES_TOOLS, BorradorRespuesta),
    "soporte_tecnico": (SOPORTE_TOOLS, BorradorRespuesta),
    "consultas": (CONSULTAS_TOOLS, BorradorRespuesta),
    "qa": (QA_TOOLS, EvaluacionQA),
}


@dataclass(frozen=True)
class AgentSpec:
    name: str
    version: str
    system_prompt: str
    tools: list[BaseTool]
    response_format: Type[BaseModel]
    model_config: ModelConfig


def get_active_versions() -> dict[str, str]:
    """Lee `active_versions.yaml` (versión en producción de cada agente) y valida que esté completo."""
    data = yaml.safe_load(ACTIVE_VERSIONS_PATH.read_text(encoding="utf-8")) or {}
    missing = [n for n in AGENT_BINDINGS if n not in data]
    unknown = [n for n in data if n not in AGENT_BINDINGS]
    if missing or unknown:
        raise ValueError(
            f"active_versions.yaml inválido (faltan: {missing or '-'}, desconocidos: {unknown or '-'})."
        )
    return {name: str(data[name]) for name in AGENT_BINDINGS}


def active_version(name: str) -> str:
    """Versión activa del agente `name` según `active_versions.yaml`."""
    return get_active_versions()[name]


def load_spec(
    name: str,
    version: str | None = None,
    *,
    provider: str | None = None,
    model_name: str | None = None,
) -> AgentSpec:
    """Carga la versión YAML del agente y la combina con sus tools, schema y configuración LLM."""
    if name not in AGENT_BINDINGS:
        raise KeyError(f"Agente '{name}' desconocido. Disponibles: {list(AGENT_BINDINGS)}")

    ver = version or active_version(name)
    path = SPECS_DIR / name / f"{ver}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No existe '{path}'. Versiones disponibles: {list_versions(name)}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    tools, schema = AGENT_BINDINGS[name]
    model_cfg = ModelConfig().with_overrides(
        **(raw.get("model") or {}),
        provider=provider,
        model_name=model_name,
    )
    prompt = raw["system_prompt"].replace("{empresa_nombre}", config.EMPRESA_NOMBRE).strip()

    return AgentSpec(
        name=name,
        version=ver,
        system_prompt=prompt,
        tools=tools,
        response_format=schema,
        model_config=model_cfg,
    )


def build_agent(
    name: str,
    *,
    version: str | None = None,
    llm: Any = None,
    provider: str | None = None,
    model_name: str | None = None,
):
    """Construye un agente de LangChain (`create_agent`) listo para invocarse."""
    spec = load_spec(name, version, provider=provider, model_name=model_name)
    model = llm or LLMFactory.create(spec.model_config)
    return create_agent(
        model=model,
        tools=spec.tools,
        system_prompt=spec.system_prompt,
        response_format=spec.response_format,
        context_schema=TicketContext,
        name=f"{spec.name}_{spec.version}",
    )


def list_versions(name: str) -> list[str]:
    """Lista las versiones YAML disponibles para un agente (p. ej. ['v1', 'v2', 'v3'])."""
    agent_dir = SPECS_DIR / name
    if not agent_dir.is_dir():
        return []
    return sorted(p.stem for p in agent_dir.glob("*.yaml"))
