from langchain_core.messages import AIMessage
import pytest
from pydantic import ValidationError

from src.data.sample_tickets import TICKETS
from src.pipeline.evaluator import evaluate_pipeline, load_eval_dataset
from src.pipeline.langsmith_eval import scenario_to_langsmith_example, sync_dataset_to_langsmith
from src.pipeline.orchestrator import SistemaMultiagente, procesar_ticket
from src.schemas.outputs import BorradorRespuesta, ClasificacionTicket, EvaluacionQA


class Stub:
    def __init__(self, responses, name, tool_calls=None, tokens=(50, 20)):
        self._responses = responses if isinstance(responses, list) else [responses]
        self.name = name
        self.calls = 0
        self.prompts: list[str] = []
        self.customer_ids: list[str] = []
        self._tool_calls = tool_calls or []
        self._tokens = tokens

    def invoke(self, payload, **_k):
        self.customer_ids.append(_k["context"].cliente_id)
        self.prompts.append(payload["messages"][0]["content"])
        idx = min(self.calls, len(self._responses) - 1)
        self.calls += 1
        ai_msg = AIMessage(
            content="ok",
            tool_calls=self._tool_calls,
            usage_metadata={
                "input_tokens": self._tokens[0],
                "output_tokens": self._tokens[1],
                "total_tokens": self._tokens[0] + self._tokens[1],
            },
        )
        return {"structured_response": self._responses[idx], "messages": [ai_msg]}


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
    assert sistema.triaje.customer_ids == [TICKETS[0]["cliente_id"]]
    assert sistema.devoluciones.customer_ids == sistema.qa.customer_ids == [TICKETS[0]["cliente_id"]] * 2
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
    assert qa_rechazo.respuesta_final not in r.respuesta_final


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


def test_telemetria_por_agente_y_evaluador():
    clasif = ClasificacionTicket(
        categoria="devolucion", prioridad="media", segmento_cliente="VIP", pedido_id="P9001", sku="SKU-002", resumen="r", justificacion="j"
    )
    borr = BorradorRespuesta(respuesta_cliente="RMA-00001 generado")
    qa = EvaluacionQA(
        precision=5, politica=5, tono=5, completitud=5, veredicto="aprobado", respuesta_final="final", observaciones="ok"
    )
    t_stub = Stub(
        clasif, "triaje",
        tool_calls=[{"name": "consultar_cliente", "args": {"cliente_id": "C900"}, "id": "tc1"}],
        tokens=(100, 30),
    )
    d_stub = Stub(
        borr, "devoluciones",
        tool_calls=[
            {"name": "consultar_pedido", "args": {"pedido_id": "P9001", "cliente_id": "C900"}, "id": "tc2"},
            {"name": "verificar_devolucion", "args": {"pedido_id": "P9001", "sku": "SKU-002", "cliente_id": "C900"}, "id": "tc3"},
            {"name": "crear_etiqueta_devolucion", "args": {"pedido_id": "P9001", "sku": "SKU-002", "motivo": "x", "cliente_id": "C900"}, "id": "tc4"},
        ],
        tokens=(200, 50),
    )
    qa_stub = Stub(qa, "qa", tool_calls=[], tokens=(150, 40))
    sistema = SistemaMultiagente(t_stub, d_stub, d_stub, d_stub, qa_stub, versiones={"triaje": "v2", "devoluciones": "v1", "qa": "v1"})

    r = procesar_ticket(TICKETS[0], sistema)
    assert len(r.metricas_agentes) == 3
    assert [m.agent for m in r.metricas_agentes] == ["triaje", "devoluciones", "qa"]
    assert r.metricas_agentes[0].version == "v2"
    assert [tc.tool for tc in r.tool_calls] == [
        "consultar_cliente", "consultar_pedido", "verificar_devolucion", "crear_etiqueta_devolucion"
    ]
    assert r.total_tokens == (130 + 250 + 190)

    # Verifica evaluate_pipeline sobre EVAL-001 con el sistema stub
    eval_001 = load_eval_dataset(limit=1)
    report = evaluate_pipeline(eval_001, sistema=sistema)
    assert report.total_scenarios == 1
    assert report.passed_scenarios == 1
    assert report.pass_rate == 1.0
    assert report.quality_gate_passed is True
    assert all(qt.passed for qt in report.quality_targets)
    assert report.diagnostics["tool_trajectory_recall"] == 1.0
    assert report.diagnostics["category_accuracy"] == 1.0


def test_sync_dataset_to_langsmith_idempotente():
    class FakeObj:
        def __init__(self, id_val):
            self.id = id_val

    class FakeLangSmithClient:
        def __init__(self):
            self.datasets = {}
            self.examples = {}
            self.created_calls = 0
            self.updated_calls = 0

        def has_dataset(self, *, dataset_name):
            return dataset_name in self.datasets

        def read_dataset(self, *, dataset_name):
            return self.datasets[dataset_name]

        def create_dataset(self, *, dataset_name, description=""):
            ds = FakeObj("ds-123")
            self.datasets[dataset_name] = ds
            return ds

        def list_examples(self, *, dataset_id):
            return list(self.examples.values())

        def create_example(self, *, inputs, outputs, metadata, dataset_id, example_id):
            self.created_calls += 1
            self.examples[str(example_id)] = FakeObj(str(example_id))

        def update_example(self, *, example_id, inputs, outputs, metadata):
            self.updated_calls += 1

    fake_client = FakeLangSmithClient()
    res1 = sync_dataset_to_langsmith("test-golden-v1", client=fake_client)
    assert res1.created is True
    assert res1.total_examples == 23
    assert fake_client.created_calls == 23
    assert fake_client.updated_calls == 0

    # Segunda ejecución sobre el mismo dataset: actualiza de forma idempotente sin duplicar
    res2 = sync_dataset_to_langsmith("test-golden-v1", client=fake_client)
    assert res2.created is False
    assert res2.total_examples == 23
    assert fake_client.created_calls == 23
    assert fake_client.updated_calls == 23

    sample_row = load_eval_dataset(limit=1)[0]
    ex = scenario_to_langsmith_example(sample_row, "test-golden-v1")
    assert ex["inputs"]["id"] == "EVAL-001"
    assert ex["outputs"]["expected_routing"]["categoria"] == "devolucion"
    assert ex["metadata"]["scenario_id"] == "EVAL-001"


def test_make_pipeline_target_envuelve_procesar_ticket(monkeypatch):
    import json

    from src.pipeline import langsmith_eval as le
    from src.pipeline.evaluator import load_eval_dataset
    from src.pipeline.langsmith_eval import make_pipeline_target, scenario_to_langsmith_example
    from src.pipeline.orchestrator import ResultadoTicket, SistemaMultiagente, ToolCallTrace
    from src.schemas.outputs import BorradorRespuesta, ClasificacionTicket, EvaluacionQA

    capturado = {}

    def fake_procesar(ticket, sistema):
        capturado["ticket"] = ticket
        return ResultadoTicket(
            ticket_id=ticket["id"],
            clasificacion=ClasificacionTicket(categoria="consulta"),
            especialista="consultas",
            borrador=BorradorRespuesta(respuesta_cliente="hola"),
            qa=EvaluacionQA(precision=5, politica=5, tono=5, completitud=5, veredicto="aprobado", respuesta_final="hola"),
            respuesta_final="hola",
            tool_calls=[ToolCallTrace(agent="triaje", tool="buscar_cliente", args={"cliente_id": "C001"})],
            total_tokens=10,
            segundos=0.5,
        )

    monkeypatch.setattr(le, "procesar_ticket", fake_procesar)
    sc = next(
        s for s in load_eval_dataset()
        if (s.get("context") or {}).get("stage_under_test") != "qa"
    )
    inputs = scenario_to_langsmith_example(sc, "x")["inputs"]
    target = make_pipeline_target(SistemaMultiagente(None, None, None, None, None))
    out = target(inputs)

    assert capturado["ticket"]["id"] == sc["id"]
    assert capturado["ticket"]["mensaje"] == sc["user_input"]
    assert out["stage"] == "pipeline"
    assert out["categoria"] == "consulta" and out["escalado_humano"] is False
    assert out["tool_calls"][0]["tool"] == "buscar_cliente"
    json.dumps(out)  # debe ser serializable para LangSmith


def test_code_evaluators_replican_checks_locales():
    from src.pipeline.langsmith_eval import CODE_EVALUATORS

    ref = {
        "outputs": {
            "expected_routing": {"categoria": "devolucion", "especialista": "devoluciones", "escalado_humano": False},
            "expected_tool_calls": [{"agent": "triaje", "tool": "buscar_cliente", "args": {"cliente_id": "C001"}}],
        }
    }
    ok_run = {
        "outputs": {
            "stage": "pipeline",
            "categoria": "devolucion",
            "especialista": "devoluciones",
            "escalado_humano": False,
            "qa": {"veredicto": "aprobado"},
            "tool_calls": [{"agent": "triaje", "tool": "buscar_cliente", "args": {"cliente_id": "c001"}}],
        }
    }
    assert {e(ok_run, ref)["key"]: e(ok_run, ref)["score"] for e in CODE_EVALUATORS} == {
        "categoria_match": 1, "especialista_match": 1, "escalado_match": 1,
        "tool_trajectory_match": 1, "qa_quality_gate": 1,
    }

    bad_run = {"outputs": {**ok_run["outputs"], "categoria": "consulta", "tool_calls": [], "qa": {"veredicto": "rechazado"}}}
    scores = {e(bad_run, ref)["key"]: e(bad_run, ref)["score"] for e in CODE_EVALUATORS}
    assert scores["categoria_match"] == 0
    assert scores["tool_trajectory_match"] == 0
    assert scores["qa_quality_gate"] == 0

    qa_run = {"outputs": {"stage": "qa", "stage_checks": {"no_tools_called": True, "rejected_contradictory_draft": True}}}
    qa = {e(qa_run, ref)["key"]: e(qa_run, ref)["score"] for e in CODE_EVALUATORS}
    assert qa["categoria_match"] is None and qa["qa_quality_gate"] == 1 and qa["tool_trajectory_match"] == 1


def test_summarize_experiment_rows():
    from src.pipeline.langsmith_eval import summarize_experiment_rows

    rows = [
        {"scenario_id": "EVAL-001", "scores": {"a": 1, "b": 1}},
        {"scenario_id": "EVAL-002", "scores": {"a": 0, "b": 1}},
        {"scenario_id": "EVAL-020", "scores": {"a": None, "b": 1}},
    ]
    total, passed, means, failed = summarize_experiment_rows(rows)
    assert (total, passed) == (3, 2)
    assert means == {"a": 0.5, "b": 1.0}
    assert failed == {"EVAL-002": ["a"]}


def test_incomplete_qa_escalates_without_releasing_text():
    incomplete = {"respuesta_final": "Mensaje sin una evaluación válida"}
    with pytest.raises(ValidationError):
        EvaluacionQA.model_validate(incomplete)

    sistema = _sistema("consulta", qas=incomplete)
    result = procesar_ticket(TICKETS[0], sistema, max_qa_retries=1)

    assert result.qa is None
    assert result.escalado_humano
    assert "QA no pudo completar" in result.motivo_escalado
    assert result.intentos_qa == sistema.consultas.calls == 1
    assert "especialista humano" in result.respuesta_final
    assert incomplete["respuesta_final"] not in result.respuesta_final
