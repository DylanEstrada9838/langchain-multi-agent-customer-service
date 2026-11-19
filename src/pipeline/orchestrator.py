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


def _run(agent, prompt: str):
    out = agent.invoke(
        {"messages": [{"role": "user", "content": prompt}]},
        config={"recursion_limit": RECURSION_LIMIT},
    )
    return out["structured_response"]


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

    # Paso 1: Triaje
    triaje_fallido = False
    try:
        clasif = _run(sistema.triaje, steps.paso_triaje(ctx))
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
    agente = sistema.especialista(clasif.categoria)
    borrador = _run(agente, steps.paso_resolucion(ctx, clasif))
    qa = _run(sistema.qa, steps.paso_qa(ctx, clasif, borrador))
    intentos_qa = 1

    while qa.veredicto == "rechazado" and intentos_qa <= retries and not borrador.requiere_escalado:
        borrador = _run(agente, steps.paso_correccion(ctx, clasif, borrador, qa.observaciones))
        qa = _run(sistema.qa, steps.paso_qa(ctx, clasif, borrador))
        intentos_qa += 1

    # Evaluación de escalado a humano
    escalado, motivo_escalado = _evaluar_escalado(triaje_fallido, borrador, qa, intentos_qa)
    respuesta_final = qa.respuesta_final
    if qa.veredicto == "rechazado":
        respuesta_final = (
            f"{qa.respuesta_final}\n\n[Aviso: Tu caso ha sido derivado a un especialista humano "
            f"de {config.EMPRESA_NOMBRE} para revisión prioritaria.]"
        )

    nombre = _CATEGORIA_A_ESPECIALISTA[clasif.categoria]
    usados = {
        "triaje": sistema.versiones.get("triaje", config.DEFAULT_AGENT_VERSION),
        nombre: sistema.versiones.get(nombre, config.DEFAULT_AGENT_VERSION),
        "qa": sistema.versiones.get("qa", config.DEFAULT_AGENT_VERSION),
    }
    return ResultadoTicket(
        ticket_id=ticket.get("id", "N/A"),
        clasificacion=clasif,
        especialista=nombre,
        borrador=borrador,
        qa=qa,
        respuesta_final=respuesta_final,
        intentos_qa=intentos_qa,
        escalado_humano=escalado,
        motivo_escalado=motivo_escalado,
        versiones_agentes=usados,
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
