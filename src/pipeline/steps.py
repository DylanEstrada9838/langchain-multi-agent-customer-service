"""Prompts de los pasos 1 (triaje), 2 (resolución dinámica), 2b (corrección tras rechazo QA) y 3 (QA)."""
import json

from src.data import POLITICAS
from src.schemas.outputs import BorradorRespuesta, ClasificacionTicket

_INSTR = {
    "devolucion": "Gestiona la devolución: consulta el pedido, verifica elegibilidad y, solo si procede, genera la etiqueta. "
                  "Si no procede, explica el motivo y alternativas.",
    "soporte_tecnico": "Investiga el problema: comprueba incidencias activas relacionadas y busca la solución en la base de conocimiento. "
                       "Redacta pasos claros.",
    "consulta": "Responde a la consulta con datos reales: consulta el pedido/cliente/incidencias si aplica. "
                f"Políticas de la empresa: {json.dumps({k: POLITICAS[k] for k in ('devoluciones', 'envios')}, ensure_ascii=False)}",
    "queja_grave": "El cliente está muy molesto. Empatiza, pide disculpas, consulta pedido e incidencias para explicar la causa real y "
                   f"ofrece la compensación según la política: {json.dumps(POLITICAS['compensaciones'], ensure_ascii=False)}. "
                   "Adapta el tono al segmento.",
}


def paso_triaje(ctx: str) -> str:
    return (
        f"{ctx}\n\nPASO 1 (Triaje): consulta al cliente, clasifica el ticket (categoría y prioridad) "
        "y devuelve la clasificación estructurada."
    )


def paso_resolucion(ctx: str, c: ClasificacionTicket) -> str:
    return (
        f"{ctx}\n\nCLASIFICACIÓN DEL TRIAJE: categoría={c.categoria}, prioridad={c.prioridad}, "
        f"segmento={c.segmento_cliente}, pedido={c.pedido_id}, sku={c.sku}\nResumen: {c.resumen}\n\n"
        f"PASO 2 (Resolución, prioridad {c.prioridad}): {_INSTR[c.categoria]}\n"
        "Si el ticket o el resumen del triaje incluye preguntas secundarias (p. ej. sobre políticas de devolución o envíos), "
        "respóndelas todas de forma completa además de la solicitud principal.\n"
        "Redacta el borrador de respuesta al cliente y lista los datos que verificaste con herramientas."
    )


def paso_correccion(ctx: str, c: ClasificacionTicket, borrador_anterior: BorradorRespuesta, observaciones_qa: str) -> str:
    return (
        f"{paso_resolucion(ctx, c)}\n\n"
        f"CORRECCIÓN REQUERIDA POR QA:\n"
        f"- Borrador anterior rechazado: {borrador_anterior.respuesta_cliente}\n"
        f"- Motivo del rechazo de QA: {observaciones_qa}\n"
        "Vuelve a consultar tus herramientas si faltan datos verificados, corrige los errores señalados por QA "
        "y genera un nuevo borrador veraz. Si el caso no puede resolverse con tus herramientas, marca `requiere_escalado=true`."
    )


def paso_qa(ctx: str, c: ClasificacionTicket, b: BorradorRespuesta) -> str:
    return (
        f"{ctx}\n\nCLASIFICACIÓN: {c.model_dump_json()}\n\nBORRADOR DEL ESPECIALISTA:\n{b.respuesta_cliente}\n"
        f"Acciones realizadas: {b.acciones_realizadas}\nDatos verificados: {b.datos_verificados}\n\n"
        f"POLÍTICAS DE LA EMPRESA: {json.dumps(POLITICAS, ensure_ascii=False)}\n\n"
        f"PASO 3 (QA): evalúa el borrador frente al mensaje original del cliente (segmento: {c.segmento_cliente}) y las políticas. "
        "Devuelve la evaluación y la respuesta final aprobada."
    )
