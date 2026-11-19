import pytest

from src.data.sample_tickets import TICKETS
from src.pipeline.orchestrator import SistemaMultiagente, procesar_ticket
from src.schemas.outputs import BorradorRespuesta, ClasificacionTicket, EvaluacionQA


class Stub:
    def __init__(self, responses, name):
        self._responses = responses if isinstance(responses, list) else [responses]
        self.name = name
        self.calls = 0
        self.prompts: list[str] = []

    def invoke(self, payload, **_k):
        self.prompts.append(payload["messages"][0]["content"])
        idx = min(self.calls, len(self._responses) - 1)
        self.calls += 1
        return {"structured_response": self._responses[idx]}


def _sistema(categoria, borradores=None, qas=None):
    clasif = ClasificacionTicket(
        categoria=categoria, prioridad="media", segmento_cliente="VIP", resumen="r", justificacion="j"
    )
    borr = borradores or BorradorRespuesta(respuesta_cliente="borrador")
    qa = qas or EvaluacionQA(
        precision=5, politica=5, tono=5, completitud=5, veredicto="aprobado", respuesta_final="final", observaciones="ok"
    )
    return SistemaMultiagente(
        Stub(clasif, "t"), Stub(borr, "d"), Stub(borr, "s"), Stub(borr, "c"), Stub(qa, "qa")
    )


@pytest.mark.parametrize("categoria,attr,esperado", [
    ("devolucion", "devoluciones", "devoluciones"),
    ("soporte_tecnico", "soporte", "soporte_tecnico"),
    ("consulta", "consultas", "consultas"),
    ("queja_grave", "consultas", "consultas"),
])
def test_enrutado(categoria, attr, esperado):
    sistema = _sistema(categoria)
    r = procesar_ticket(TICKETS[0], sistema)
    assert r.especialista == esperado
    assert getattr(sistema, attr).calls == 1
    assert sistema.qa.calls == 1
    assert r.intentos_qa == 1
    assert r.escalado_humano is False
    assert r.respuesta_final == "final"


def test_qa_rechaza_y_especialista_corrige_en_reintento():
    borr_1 = BorradorRespuesta(respuesta_cliente="borrador con dato inventado")
    borr_2 = BorradorRespuesta(respuesta_cliente="borrador corregido con tool")
    qa_1 = EvaluacionQA(
        precision=1, politica=3, tono=4, completitud=3, veredicto="rechazado",
        respuesta_final="temporal", observaciones="Inventó el RMA sin llamar a la tool"
    )
    qa_2 = EvaluacionQA(
        precision=5, politica=5, tono=5, completitud=5, veredicto="aprobado",
        respuesta_final="respuesta corregida y aprobada", observaciones="ok"
    )
    sistema = _sistema("devolucion", borradores=[borr_1, borr_2], qas=[qa_1, qa_2])
    r = procesar_ticket(TICKETS[0], sistema, max_qa_retries=1)

    assert sistema.devoluciones.calls == 2
    assert sistema.qa.calls == 2
    assert r.intentos_qa == 2
    assert "CORRECCIÓN REQUERIDA POR QA" in sistema.devoluciones.prompts[1]
    assert r.qa.veredicto == "aprobado"
    assert r.escalado_humano is False
    assert r.respuesta_final == "respuesta corregida y aprobada"


def test_qa_rechaza_tras_reintentos_escala_a_humano():
    qa_rechazo = EvaluacionQA(
        precision=1, politica=1, tono=2, completitud=2, veredicto="rechazado",
        respuesta_final="No podemos confirmar los datos en este momento.",
        observaciones="Sigue sin verificar el pedido",
    )
    sistema = _sistema("devolucion", qas=[qa_rechazo, qa_rechazo])
    r = procesar_ticket(TICKETS[0], sistema, max_qa_retries=1)

    assert sistema.devoluciones.calls == 2
    assert sistema.qa.calls == 2
    assert r.intentos_qa == 2
    assert r.escalado_humano is True
    assert "QA rechazó la respuesta tras 2 intento(s)" in r.motivo_escalado
    assert "especialista humano" in r.respuesta_final


def test_especialista_solicita_escalado_a_humano():
    borr_escalado = BorradorRespuesta(
        respuesta_cliente="El fallo requiere revisión física en taller.",
        requiere_escalado=True,
    )
    sistema = _sistema("soporte_tecnico", borradores=borr_escalado)
    r = procesar_ticket(TICKETS[2], sistema)

    assert r.escalado_humano is True
    assert "Especialista solicitó escalado a humano" in r.motivo_escalado


def test_fallback_si_falla_triaje_marca_escalado():
    sistema = _sistema("devolucion")

    def boom(*_a, **_k):
        raise RuntimeError("fallo")

    sistema.triaje.invoke = boom
    r = procesar_ticket(TICKETS[0], sistema)
    assert r.clasificacion.categoria == "consulta" and r.especialista == "consultas"
    assert r.escalado_humano is True
    assert "Fallo en agente de triaje" in r.motivo_escalado
