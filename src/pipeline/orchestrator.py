"""Orquestación: Triaje -> Especialista (con bucle de reintento ante rechazo de QA) -> QA / Escalado a humano."""
import json
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.messages import AIMessage, ToolMessage
from pydantic import BaseModel, Field

from src import config
from src.agents import active_version, build_agent, get_active_versions
from src.llm import calculate_cost
from src.pipeline import steps
from src.pipeline.context import TicketContext, generar_contexto
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
    result: dict[str, Any] | None = None


class AgentStepMetrics(BaseModel):
    agent: str
    version: str
    segundos: float
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float | None = None
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


FailureStage = Literal["context", "specialist", "specialist_retry", "qa"]


class ResultadoTicket(BaseModel):
    ticket_id: str
    clasificacion: ClasificacionTicket | None
    especialista: str | None
    borrador: BorradorRespuesta | None
    qa: EvaluacionQA | None
    respuesta_final: str
    intentos_qa: int = 1
    escalado_humano: bool = False
    motivo_escalado: str | None = None
    failed_stage: FailureStage | None = None
    versiones_agentes: dict[str, str] = Field(default_factory=dict)
    metricas_agentes: list[AgentStepMetrics] = Field(default_factory=list)
    tool_calls: list[ToolCallTrace] = Field(default_factory=list)
    total_tokens: int = 0
    cost_usd: float | None = None
    ttft_seconds: float | None = None
    segundos: float


def construir_sistema(
    llm: Any = None,
    *,
    versions: dict[str, str] | None = None,
    provider: str | None = None,
    model_name: str | None = None,
) -> SistemaMultiagente:
    """Crea los 5 agentes con las versiones indicadas; las omitidas usan `active_versions.yaml`."""
    ver_map = {**get_active_versions(), **(versions or {})}
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


def _tool_evidence(message: ToolMessage) -> dict[str, Any] | None:
    fields = {
        "consultar_pedido": ("estado_envio", "transportista", "tracking", "error"),
        "verificar_devolucion": ("elegible", "motivo", "estado_envio", "dias_desde_entrega", "plazo_dias"),
        "crear_etiqueta_devolucion": ("rma_id", "etiqueta_url", "pedido_id", "sku"),
        "buscar_knowledge_base": ("resultados",),
        "verificar_incidencias": ("incidencias_activas",),
        "consultar_cliente": ("segmento",),
    }.get(message.name)
    if not fields or message.status == "error" or not isinstance(message.content, str):
        return None
    try:
        payload = json.loads(message.content)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    evidence = {key: payload[key] for key in fields if key in payload}
    for key in ("resultados", "incidencias_activas"):
        if isinstance(evidence.get(key), list):
            evidence[key] = [item["id"] for item in evidence[key] if isinstance(item, dict) and "id" in item]
    return evidence


def _extract_telemetry(agent_name: str, version: str, out: dict[str, Any], elapsed: float) -> AgentStepMetrics:
    """Extrae tool_calls reales y tokens consumidos del historial de mensajes de LangChain."""
    tool_calls: list[ToolCallTrace] = []
    in_tok = out_tok = tot_tok = 0
    response_format_name = None
    costs: list[float | None] = []
    if "structured_response" in out and out["structured_response"] is not None:
        response_format_name = type(out["structured_response"]).__name__

    messages = out.get("messages") or []
    results = {msg.tool_call_id: _tool_evidence(msg) for msg in messages if isinstance(msg, ToolMessage)}
    for msg in messages:
        usage = getattr(msg, "usage_metadata", None) or (msg.get("usage_metadata") if isinstance(msg, dict) else None)
        if isinstance(usage, dict):
            input_count = usage.get("input_tokens")
            output_count = usage.get("output_tokens")
            in_tok += int(input_count or 0)
            out_tok += int(output_count or 0)
            tot_tok += int(usage.get("total_tokens") or 0)
            metadata = (msg.get("response_metadata") if isinstance(msg, dict) else getattr(msg, "response_metadata", None)) or {}
            model = metadata.get("model_name") or metadata.get("model")
            costs.append(
                calculate_cost(model, int(input_count), int(output_count))
                if input_count is not None and output_count is not None else None
            )
        elif isinstance(msg, AIMessage):
            costs.append(None)

        raw_calls = getattr(msg, "tool_calls", None) or (msg.get("tool_calls") if isinstance(msg, dict) else None) or []
        for tc in raw_calls:
            t_name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
            # Ignorar la tool interna de structured output si el proveedor usa ToolStrategy
            if not t_name or t_name == response_format_name:
                continue
            t_args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
            call_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
            tool_calls.append(ToolCallTrace(
                agent=agent_name, tool=t_name,
                args=t_args if isinstance(t_args, dict) else {},
                result=results.get(call_id),
            ))

    cost = round(sum(value for value in costs if value is not None), 6) if costs and None not in costs else None
    return AgentStepMetrics(
        agent=agent_name,
        version=version,
        segundos=round(elapsed, 2),
        input_tokens=in_tok,
        output_tokens=out_tok,
        total_tokens=tot_tok or (in_tok + out_tok),
        cost_usd=cost,
        tool_calls=tool_calls,
    )


def _run(agent, prompt: str, *, context: TicketContext, agent_name: str = "agent", version: str = "v1") -> tuple[Any, AgentStepMetrics]:
    t0 = time.time()
    out = agent.invoke(
        {"messages": [{"role": "user", "content": prompt}]},
        config={"recursion_limit": RECURSION_LIMIT},
        context=context,
    )
    metrics = _extract_telemetry(agent_name, version, out, time.time() - t0)
    return out["structured_response"], metrics


def _evaluar_escalado(
    triaje_fallido: bool,
    borrador: BorradorRespuesta | None,
    qa: EvaluacionQA | None,
    intentos_qa: int,
    failed_stage: FailureStage | None,
) -> tuple[bool, str | None]:
    """Determina si el ticket debe escalarse a un agente humano y por qué motivo."""
    motivos: list[str] = []
    if triaje_fallido:
        motivos.append("Fallo en agente de triaje")
    if borrador is not None and borrador.requiere_escalado:
        motivos.append("Especialista solicitó escalado a humano")
    if failed_stage:
        motivos.append({
            "context": "No se pudo preparar el contexto del ticket",
            "specialist": "No se pudo completar la respuesta del especialista",
            "specialist_retry": "No se pudo completar el reintento del especialista",
            "qa": "QA no pudo completar una evaluación válida",
        }[failed_stage])
    if qa is not None and qa.veredicto == "rechazado":
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
    metricas: list[AgentStepMetrics] = []
    usados: dict[str, str] = {}
    clasif = nombre_esp = borrador = qa = None
    triaje_fallido = False
    intentos_qa = 0

    def finish(failed_stage: FailureStage | None = None) -> ResultadoTicket:
        escalado, motivo_escalado = _evaluar_escalado(triaje_fallido, borrador, qa, intentos_qa, failed_stage)
        if failed_stage or qa is None or qa.veredicto == "rechazado":
            respuesta_final = "Tu caso requiere la revisión de un especialista humano de " + config.EMPRESA_NOMBRE + "."
        else:
            respuesta_final = qa.respuesta_final

        all_tools = [tc for m in metricas for tc in m.tool_calls]
        total_tokens = sum(m.total_tokens for m in metricas)
        costs = [m.cost_usd for m in metricas]
        total_cost = round(sum(value for value in costs if value is not None), 6) if costs and None not in costs else None
        elapsed = round(time.time() - t0, 2)

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
            failed_stage=failed_stage,
            versiones_agentes=usados,
            metricas_agentes=metricas,
            tool_calls=all_tools,
            total_tokens=total_tokens,
            cost_usd=total_cost,
            segundos=elapsed,
        )

    try:
        context = TicketContext(ticket["cliente_id"])
        ctx = generar_contexto(ticket)
    except Exception:
        return finish("context")

    triaje_ver = sistema.versiones.get("triaje", active_version("triaje"))
    qa_ver = sistema.versiones.get("qa", active_version("qa"))

    # Paso 1: Triaje
    usados["triaje"] = triaje_ver
    try:
        clasif, m_triaje = _run(
            sistema.triaje, steps.paso_triaje(ctx), context=context, agent_name="triaje", version=triaje_ver
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
    esp_ver = sistema.versiones.get(nombre_esp, active_version(nombre_esp))
    agente = sistema.especialista(clasif.categoria)

    usados[nombre_esp] = esp_ver
    try:
        draft, m_esp = _run(
            agente, steps.paso_resolucion(ctx, clasif), context=context, agent_name=nombre_esp, version=esp_ver
        )
        metricas.append(m_esp)
        borrador = BorradorRespuesta.model_validate(draft)
    except Exception:
        return finish("specialist")

    usados["qa"] = qa_ver
    while True:
        intentos_qa += 1
        try:
            assessment, m_qa = _run(
                sistema.qa, steps.paso_qa(ctx, clasif, borrador),
                context=context, agent_name="qa", version=qa_ver,
            )
            metricas.append(m_qa)
            qa = EvaluacionQA.model_validate(assessment)
        except Exception:
            qa = None
            return finish("qa")

        if qa.veredicto != "rechazado" or intentos_qa > retries or borrador.requiere_escalado:
            break

        try:
            draft, m_esp_retry = _run(
                agente,
                steps.paso_correccion(ctx, clasif, borrador, qa.observaciones),
                context=context, agent_name=nombre_esp, version=esp_ver,
            )
            metricas.append(m_esp_retry)
            borrador = BorradorRespuesta.model_validate(draft)
        except Exception:
            return finish("specialist_retry")

    return finish()


def ticket_personalizado(mensaje: str, cliente_id: str, pedido_id: str | None = None) -> dict:
    return {
        "id": "CUSTOM",
        "cliente_id": cliente_id,
        "pedido_id": pedido_id,
        "asunto": "Mensaje personalizado",
        "mensaje": mensaje,
    }
