"""Orquestación: Triaje -> Especialista (con bucle de reintento ante rechazo de QA) -> QA / Escalado a humano."""
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from src import config
from src.agents import AGENT_BINDINGS, build_agent
from src.pipeline import steps
from src.pipeline.context import generar_contexto
from src.schemas.outputs import BorradorRespuesta, ClasificacionTicket, EvaluacionQA

RECURSION_LIMIT = 15

_CATEGORIA_A_ESPECIALISTA = {
    "devolucion": "devoluciones",
    "soporte_tecnico": "soporte_tecnico",
    "consulta": "consultas",
    "queja_grave": "consultas",
}


class ToolCallTrace(BaseModel):
    agent: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class AgentStepMetrics(BaseModel):
    agent: str
    version: str
    segundos: float
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    tool_calls: list[ToolCallTrace] = Field(default_factory=list)


@dataclass
class SistemaMultiagente:
    triaje: Any
    devoluciones: Any
    soporte: Any
    consultas: Any
    qa: Any
    versiones: dict[str, str] = field(default_factory=dict)

    def especialista(self, categoria: str):
        return {
            "devolucion": self.devoluciones,
            "soporte_tecnico": self.soporte,
            "consulta": self.consultas,
            "queja_grave": self.consultas,
        }[categoria]


class ResultadoTicket(BaseModel):
    ticket_id: str
    clasificacion: ClasificacionTicket
    especialista: str
    borrador: BorradorRespuesta
    qa: EvaluacionQA
    respuesta_final: str
    intentos_qa: int = 1
    escalado_humano: bool = False
    motivo_escalado: str | None = None
    versiones_agentes: dict[str, str] = Field(default_factory=dict)
    metricas_agentes: list[AgentStepMetrics] = Field(default_factory=list)
    tool_calls: list[ToolCallTrace] = Field(default_factory=list)
    total_tokens: int = 0
    segundos: float


def construir_sistema(
    llm: Any = None,
    *,
    versions: dict[str, str] | None = None,
    provider: str | None = None,
    model_name: str | None = None,
) -> SistemaMultiagente:
    """Crea los 5 agentes aplicando las versiones y proveedor indicados (o los valores por defecto de .env)."""
    ver_map = {name: (versions or {}).get(name, config.DEFAULT_AGENT_VERSION) for name in AGENT_BINDINGS}
    make = lambda name: build_agent(
        name, version=ver_map[name], llm=llm, provider=provider, model_name=model_name
    )
    return SistemaMultiagente(
        triaje=make("triaje"),
        devoluciones=make("devoluciones"),
        soporte=make("soporte_tecnico"),
        consultas=make("consultas"),
        qa=make("qa"),
        versiones=ver_map,
    )


def _extract_telemetry(agent_name: str, version: str, out: dict[str, Any], elapsed: float) -> AgentStepMetrics:
    """Extrae tool_calls reales y tokens consumidos del historial de mensajes de LangChain."""
    tool_calls: list[ToolCallTrace] = []
    in_tok = out_tok = tot_tok = 0
    response_format_name = None
    if "structured_response" in out and out["structured_response"] is not None:
        response_format_name = type(out["structured_response"]).__name__

    for msg in out.get("messages") or []:
        usage = getattr(msg, "usage_metadata", None) or (msg.get("usage_metadata") if isinstance(msg, dict) else None)
        if isinstance(usage, dict):
            in_tok += int(usage.get("input_tokens", 0) or 0)
            out_tok += int(usage.get("output_tokens", 0) or 0)
            tot_tok += int(usage.get("total_tokens", 0) or 0)

        raw_calls = getattr(msg, "tool_calls", None) or (msg.get("tool_calls") if isinstance(msg, dict) else None) or []
        for tc in raw_calls:
            t_name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
            # Ignorar la tool interna de structured output si el proveedor usa ToolStrategy
            if not t_name or t_name == response_format_name:
                continue
            t_args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
            tool_calls.append(
                ToolCallTrace(agent=agent_name, tool=t_name, args=t_args if isinstance(t_args, dict) else {})
            )

    return AgentStepMetrics(
        agent=agent_name,
        version=version,
        segundos=round(elapsed, 2),
        input_tokens=in_tok,
        output_tokens=out_tok,
        total_tokens=tot_tok or (in_tok + out_tok),
        tool_calls=tool_calls,
    )


def _run(agent, prompt: str, *, agent_name: str = "agent", version: str = "v1") -> tuple[Any, AgentStepMetrics]:
    t0 = time.time()
    out = agent.invoke(
        {"messages": [{"role": "user", "content": prompt}]},
        config={"recursion_limit": RECURSION_LIMIT},
    )
    metrics = _extract_telemetry(agent_name, version, out, time.time() - t0)
    return out["structured_response"], metrics


def _evaluar_escalado(
    triaje_fallido: bool,
    borrador: BorradorRespuesta,
    qa: EvaluacionQA,
    intentos_qa: int,
) -> tuple[bool, str | None]:
    """Determina si el ticket debe escalarse a un agente humano y por qué motivo."""
    motivos: list[str] = []
    if triaje_fallido:
        motivos.append("Fallo en agente de triaje")
    if borrador.requiere_escalado:
        motivos.append("Especialista solicitó escalado a humano")
    if qa.veredicto == "rechazado":
        motivos.append(f"QA rechazó la respuesta tras {intentos_qa} intento(s): {qa.observaciones}")
    return (bool(motivos), "; ".join(motivos) if motivos else None)


def procesar_ticket(
    ticket: dict,
    sistema: SistemaMultiagente,
    *,
    max_qa_retries: int | None = None,
) -> ResultadoTicket:
    t0 = time.time()
    retries = config.MAX_QA_RETRIES if max_qa_retries is None else max_qa_retries
    ctx = generar_contexto(ticket)
    metricas: list[AgentStepMetrics] = []

    triaje_ver = sistema.versiones.get("triaje", config.DEFAULT_AGENT_VERSION)
    qa_ver = sistema.versiones.get("qa", config.DEFAULT_AGENT_VERSION)

    # Paso 1: Triaje
    triaje_fallido = False
    try:
        clasif, m_triaje = _run(
            sistema.triaje, steps.paso_triaje(ctx), agent_name="triaje", version=triaje_ver
        )
        metricas.append(m_triaje)
    except Exception:
        triaje_fallido = True
        clasif = ClasificacionTicket(
            categoria="consulta",
            prioridad="media",
            segmento_cliente="Desconocido",
            resumen="Triaje fallido; se deriva a Consultas por defecto.",
            pedido_id=ticket.get("pedido_id"),
            justificacion="fallback",
        )

    # Paso 2 + Paso 3: Especialista -> QA (con bucle de reintento si QA rechaza)
    nombre_esp = _CATEGORIA_A_ESPECIALISTA[clasif.categoria]
    esp_ver = sistema.versiones.get(nombre_esp, config.DEFAULT_AGENT_VERSION)
    agente = sistema.especialista(clasif.categoria)

    borrador, m_esp = _run(
        agente, steps.paso_resolucion(ctx, clasif), agent_name=nombre_esp, version=esp_ver
    )
    metricas.append(m_esp)

    qa, m_qa = _run(
        sistema.qa, steps.paso_qa(ctx, clasif, borrador), agent_name="qa", version=qa_ver
    )
    metricas.append(m_qa)
    intentos_qa = 1

    while qa.veredicto == "rechazado" and intentos_qa <= retries and not borrador.requiere_escalado:
        borrador, m_esp_retry = _run(
            agente,
            steps.paso_correccion(ctx, clasif, borrador, qa.observaciones),
            agent_name=nombre_esp,
            version=esp_ver,
        )
        metricas.append(m_esp_retry)
        qa, m_qa_retry = _run(
            sistema.qa, steps.paso_qa(ctx, clasif, borrador), agent_name="qa", version=qa_ver
        )
        metricas.append(m_qa_retry)
        intentos_qa += 1

    # Evaluación de escalado a humano
    escalado, motivo_escalado = _evaluar_escalado(triaje_fallido, borrador, qa, intentos_qa)
    respuesta_final = qa.respuesta_final
    if qa.veredicto == "rechazado":
        respuesta_final = (
            f"{qa.respuesta_final}\n\n[Aviso: Tu caso ha sido derivado a un especialista humano "
            f"de {config.EMPRESA_NOMBRE} para revisión prioritaria.]"
        )

    usados = {"triaje": triaje_ver, nombre_esp: esp_ver, "qa": qa_ver}
    all_tools = [tc for m in metricas for tc in m.tool_calls]
    total_tokens = sum(m.total_tokens for m in metricas)

    return ResultadoTicket(
        ticket_id=ticket.get("id", "N/A"),
        clasificacion=clasif,
        especialista=nombre_esp,
        borrador=borrador,
        qa=qa,
        respuesta_final=respuesta_final,
        intentos_qa=intentos_qa,
        escalado_humano=escalado,
        motivo_escalado=motivo_escalado,
        versiones_agentes=usados,
        metricas_agentes=metricas,
        tool_calls=all_tools,
        total_tokens=total_tokens,
        segundos=round(time.time() - t0, 2),
    )


def ticket_personalizado(mensaje: str, cliente_id: str, pedido_id: str | None = None) -> dict:
    return {
        "id": "CUSTOM",
        "cliente_id": cliente_id,
        "pedido_id": pedido_id,
        "asunto": "Mensaje personalizado",
        "mensaje": mensaje,
    }
