"""Registro y factoría de agentes con versionado YAML y soporte multi-proveedor."""
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Type

import yaml
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ModelResponse
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from openai import LengthFinishReasonError
from pydantic import BaseModel

from src import config
from src.data import POLITICAS
from src.llm import LLMFactory, ModelConfig
from src.pipeline.context import TicketContext
from src.schemas.outputs import BorradorRespuesta, ClasificacionTicket, EvaluacionQA, EvaluacionQACompacta
from src.tools import CONSULTAS_TOOLS, DEVOLUCIONES_TOOLS, QA_TOOLS, SOPORTE_TOOLS, TRIAJE_TOOLS
from src.tools.crm import consultar_ultimo_pedido

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
    reuse_customer_snapshot: bool = False
    scoped_order_tools: bool = False
    verified_return_handoff: bool = False


class ScopedOrderTools(AgentMiddleware):
    """Apply ticket conditions to both the tool schema and actual dispatch."""

    @staticmethod
    def _allowed(name: str, context: TicketContext | None) -> bool:
        if name == "consultar_ultimo_pedido":
            return isinstance(context, TicketContext) and context.latest_order_allowed
        if name in {"consultar_pedido", "verificar_devolucion", "crear_etiqueta_devolucion"}:
            return isinstance(context, TicketContext) and not context.latest_order_missing
        return True

    def wrap_model_call(self, request, handler):
        tools = [
            tool for tool in request.tools
            if self._allowed(tool.name if isinstance(tool, BaseTool) else tool.get("name", ""), request.runtime.context)
        ]
        return handler(request.override(tools=tools))

    def wrap_tool_call(self, request, handler):
        if not self._allowed(request.tool_call["name"], request.runtime.context):
            return ToolMessage("La solicitud no permite esta búsqueda.", tool_call_id=request.tool_call["id"], status="error")
        return handler(request)


class RecoverReturnLabel(AgentMiddleware):
    """Build a QA draft from the tool result if the next model response is truncated."""

    def wrap_model_call(self, request, handler):
        try:
            return handler(request)
        except LengthFinishReasonError:
            if not request.messages:
                raise
            message = request.messages[-1]
            if not isinstance(message, ToolMessage) or message.name != "crear_etiqueta_devolucion" or message.status == "error":
                raise
            draft = self._draft(message)
            if draft is None:
                raise
            return ModelResponse(result=[], structured_response=draft)

    @staticmethod
    def _draft(message: ToolMessage) -> BorradorRespuesta | None:
        if not isinstance(message.content, str):
            return None
        try:
            label = json.loads(message.content)
        except ValueError:
            return None
        fields = ("pedido_id", "sku", "rma_id", "etiqueta_url", "transportista")
        if not isinstance(label, dict) or "error" in label or not all(
            isinstance(label.get(field), str) and label[field].strip() for field in fields
        ):
            return None
        return BorradorRespuesta(
            respuesta_cliente=(
                f"Hola,\n\nSu devolución del pedido {label['pedido_id']} se ha autorizado. "
                f"Su código RMA es {label['rma_id']}. Descargue la etiqueta en {label['etiqueta_url']} "
                f"y utilícela para enviar el paquete con {label['transportista']}.\n\n"
                f"{POLITICAS['devoluciones']['reembolso']}\n\nAtentamente,\nEl equipo de {config.EMPRESA_NOMBRE}"
            ),
            acciones_realizadas=["crear_etiqueta_devolucion"],
            datos_verificados=[f"{field}: {label[field]}" for field in fields],
        )


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
    reuse_customer_snapshot = name in {"triaje", "consultas"} and raw.get("reuse_customer_snapshot") is True
    if reuse_customer_snapshot:
        tools = [tool for tool in tools if tool.name != "consultar_cliente"]
        if name == "triaje":
            tools.append(consultar_ultimo_pedido)
    if name == "qa" and raw.get("reuse_approved_draft") is True:
        schema = EvaluacionQACompacta
    model_overrides = dict(raw.get("model") or {})
    model_overrides.update({key: value for key, value in {"provider": provider, "model_name": model_name}.items() if value is not None})
    model_cfg = ModelConfig().with_overrides(**model_overrides)
    prompt = raw["system_prompt"].replace("{empresa_nombre}", config.EMPRESA_NOMBRE).strip()

    return AgentSpec(
        name=name,
        version=ver,
        system_prompt=prompt,
        tools=tools,
        response_format=schema,
        model_config=model_cfg,
        reuse_customer_snapshot=reuse_customer_snapshot,
        scoped_order_tools=raw.get("scoped_order_tools") is True,
        verified_return_handoff=name == "devoluciones" and raw.get("verified_return_handoff") is True,
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
    middleware = []
    if spec.scoped_order_tools:
        middleware.append(ScopedOrderTools())
    if spec.verified_return_handoff:
        middleware.append(RecoverReturnLabel())
    return create_agent(
        model=model,
        tools=spec.tools,
        system_prompt=spec.system_prompt,
        response_format=spec.response_format,
        context_schema=TicketContext,
        middleware=middleware,
        name=f"{spec.name}_{spec.version}",
    )


def list_versions(name: str) -> list[str]:
    """Lista las versiones YAML disponibles para un agente (p. ej. ['v1', 'v2', 'v3'])."""
    agent_dir = SPECS_DIR / name
    if not agent_dir.is_dir():
        return []
    return sorted(p.stem for p in agent_dir.glob("*.yaml"))
