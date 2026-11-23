from langchain_core.messages import AIMessage, ToolMessage
import pytest
from pydantic import ValidationError

from src.data.sample_tickets import TICKETS
from src.pipeline.eval_dataset import load_eval_dataset
from src.pipeline.langsmith_eval import scenario_to_langsmith_example, sync_dataset_to_langsmith
from src.pipeline.orchestrator import SistemaMultiagente, procesar_ticket
from src.schemas.outputs import BorradorRespuesta, ClasificacionTicket, EvaluacionQA


class Stub:
    def __init__(self, responses, name, tool_calls=None, tokens=(50, 20), tool_results=()):
        self._responses = responses if isinstance(responses, list) else [responses]
        self.name = name
        self.calls = 0
        self.prompts: list[str] = []
        self.customer_ids: list[str] = []
        self.contexts = []
        self._tool_calls = tool_calls or []
        self._tokens = tokens
        self._tool_results = tool_results

    def invoke(self, payload, **_k):
        self.customer_ids.append(_k["context"].cliente_id)
        self.contexts.append(_k["context"])
        self.prompts.append(payload["messages"][0]["content"])
        idx = min(self.calls, len(self._responses) - 1)
        self.calls += 1
        ai_msg = AIMessage(
            content="ok",
            response_metadata={"model_name": "gpt-4o"},
            tool_calls=self._tool_calls,
            usage_metadata={
                "input_tokens": self._tokens[0],
                "output_tokens": self._tokens[1],
                "total_tokens": self._tokens[0] + self._tokens[1],
            },
        )
        return {"structured_response": self._responses[idx], "messages": [ai_msg, *self._tool_results]}


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
        precision=5, politica=5, tono=5, completitud=5, veredicto="aprobado", respuesta_final="RMA-00001 https://example.test/label.pdf", observaciones="ok"
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
        tool_results=[ToolMessage(
            name="crear_etiqueta_devolucion", tool_call_id="tc4",
            content='{"rma_id":"RMA-00001","etiqueta_url":"https://example.test/label.pdf","pedido_id":"P9001","sku":"SKU-002"}',
        )],
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

    from src.pipeline.langsmith_eval import CODE_EVALUATORS, make_pipeline_target

    example = scenario_to_langsmith_example(load_eval_dataset()[0], "golden")
    run = {"outputs": make_pipeline_target(sistema)(example["inputs"])}
    assert all(check(run, example)["score"] == 1 for check in CODE_EVALUATORS)
    assert r.cost_usd == 0.002325
    assert r.ttft_seconds is None


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

    sample_row = load_eval_dataset()[0]
    ex = scenario_to_langsmith_example(sample_row, "test-golden-v1")
    assert ex["inputs"]["id"] == "EVAL-001"
    assert ex["outputs"]["expected_routing"]["categoria"] == "devolucion"
    assert ex["metadata"]["scenario_id"] == "EVAL-001"


def test_make_pipeline_target_envuelve_procesar_ticket(monkeypatch):
    import json

    from src.pipeline import langsmith_eval as le
    from src.pipeline.eval_dataset import load_eval_dataset
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
        "tool_trajectory_match": 1, "qa_quality_gate": 1, "scenario_assertions": None,
    }

    bad_run = {"outputs": {**ok_run["outputs"], "categoria": "consulta", "tool_calls": [], "qa": {"veredicto": "rechazado"}}}
    scores = {e(bad_run, ref)["key"]: e(bad_run, ref)["score"] for e in CODE_EVALUATORS}
    assert scores["categoria_match"] == 0
    assert scores["tool_trajectory_match"] == 0
    assert scores["qa_quality_gate"] == 0

    qa_run = {"outputs": {"stage": "qa", "tool_calls": [], "qa": {"veredicto": "rechazado"}}}
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


@pytest.mark.parametrize(
    ("failed_stage", "expected_agents", "qa_attempts"),
    [
        ("context", [], 0),
        ("specialist", ["triaje", "consultas"], 0),
        ("specialist_retry", ["triaje", "consultas", "qa", "consultas"], 1),
    ],
)
def test_processing_failure_retains_ticket(monkeypatch, failed_stage, expected_agents, qa_attempts):
    from src.pipeline import orchestrator
    from src.pipeline.langsmith_eval import qa_quality_gate

    rejected = EvaluacionQA(
        precision=1, politica=1, tono=4, completitud=3, veredicto="rechazado",
        respuesta_final="Rejected text", observaciones="Check the order",
    )
    sistema = _sistema("consulta", qas=rejected)
    original_invoke = sistema.consultas.invoke

    def fail(*args, **kwargs):
        raise RuntimeError("private error details")

    def fail_on_retry(*args, **kwargs):
        if sistema.consultas.calls:
            fail()
        return original_invoke(*args, **kwargs)

    if failed_stage == "context":
        monkeypatch.setattr(orchestrator, "generar_contexto", fail)
    elif failed_stage == "specialist":
        monkeypatch.setattr(sistema.consultas, "invoke", fail)
    else:
        monkeypatch.setattr(sistema.consultas, "invoke", fail_on_retry)

    result = procesar_ticket(TICKETS[0], sistema, max_qa_retries=1)
    assert result.ticket_id == TICKETS[0]["id"]
    assert result.failed_stage == failed_stage
    assert result.escalado_humano
    assert result.intentos_qa == qa_attempts
    assert [metric.agent for metric in result.metricas_agentes] == expected_agents
    assert result.token_usage_complete is (failed_stage == "context")
    assert (result.clasificacion is None) == (failed_stage == "context")
    assert "especialista humano" in result.respuesta_final
    assert "private error details" not in result.respuesta_final
    assert rejected.respuesta_final not in result.respuesta_final
    assert (result.borrador is not None) == (failed_stage == "specialist_retry")
    assert result.qa == (rejected if failed_stage == "specialist_retry" else None)
    assert qa_quality_gate({"outputs": result.model_dump()}, {})["score"] == 0


@pytest.mark.parametrize("qa_only", [False, True])
def test_truncated_agent_counts_earlier_and_failed_model_calls(monkeypatch, qa_only):
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langgraph.graph import START, MessagesState, StateGraph
    from openai import LengthFinishReasonError
    from openai.types.chat import ChatCompletion

    from src.pipeline.context import TicketContext
    from src.pipeline.langsmith_eval import make_pipeline_target, qa_quality_gate

    truncated = LengthFinishReasonError(completion=ChatCompletion(
        id="test", choices=[], created=0, model="gpt-4o-mini", object="chat.completion",
        usage={"prompt_tokens": 1800, "completion_tokens": 1500, "total_tokens": 3300},
    ))
    model = FakeMessagesListChatModel(responses=[], cache=False)
    earlier = AIMessage(content="ok", usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120})

    def generate(_model, messages, **kwargs):
        if messages[0].content == "call that completes":
            return ChatResult(generations=[ChatGeneration(message=earlier)], llm_output={"model_name": "gpt-4o-mini"})
        raise truncated

    monkeypatch.setattr(type(model), "_generate", generate)
    system = _sistema("consulta")

    def call_model(_state):
        model.invoke("call that completes")
        model.invoke("call that truncates")

    graph = StateGraph(MessagesState, context_schema=TicketContext)
    graph.add_node("model", call_model)
    graph.add_edge(START, "model")
    agent = graph.compile()
    if qa_only:
        system.qa = agent
        scenario = next(row for row in load_eval_dataset() if row["context"].get("stage_under_test") == "qa")
        example = scenario_to_langsmith_example(scenario, "test-dataset")
        output = make_pipeline_target(system)(example["inputs"])
        assert output["failed_stage"] == "qa" and output["qa"] is None
        assert output["token_usage_complete"] and output["total_tokens"] == 3420
        assert output["cost_usd"] == pytest.approx(0.001197)
        assert qa_quality_gate({"outputs": output}, example)["score"] == 0
        return

    system.consultas = agent
    result = procesar_ticket(TICKETS[0], system)

    assert result.failed_stage == "specialist" and result.escalado_humano
    assert result.token_usage_complete
    assert result.total_tokens == 70 + 120 + 3300
    specialist = result.metricas_agentes[-1]
    assert specialist.model_calls == 2
    assert specialist.input_tokens == 1900 and specialist.output_tokens == 1520
    assert specialist.cost_usd == pytest.approx(0.001197)


def test_trajectory_matches_agent_arguments_order_and_multiplicity():
    from src.pipeline.orchestrator import ToolCallTrace
    from src.pipeline.scenario_checks import check_tools

    lookup = {"agent": "triaje", "tool": "crm", "args": {"cliente_id": "C900"}}
    verify = {"agent": "devoluciones", "tool": "eligibility", "args": {"sku": "SKU-002"}}
    actual = [ToolCallTrace(**lookup), ToolCallTrace(**verify)]
    assert check_tools([lookup, verify], actual, ordered=True) == (True, 1.0)
    assert not check_tools([lookup, lookup], actual)[0]
    assert not check_tools([verify, lookup], actual, ordered=True)[0]
    assert not check_tools([{**lookup, "agent": "consultas"}], actual)[0]
    assert not check_tools([{**verify, "args": {"sku": "SKU-003"}}], actual)[0]


def test_scenario_checks_reject_inaccurate_rma_reply_and_low_qa():
    from src.pipeline.langsmith_eval import scenario_assertions, tool_trajectory_match
    from src.pipeline.orchestrator import ToolCallTrace
    from src.pipeline.scenario_checks import check_scenario

    scenario = load_eval_dataset()[0]
    calls = [ToolCallTrace(**entry) for entry in scenario["expected_tool_calls"]]
    calls[-1].result = {
        "pedido_id": "P9001", "sku": "SKU-002", "rma_id": "RMA-00001",
        "etiqueta_url": "https://example.test/the-label.pdf",
    }
    ref = {"outputs": scenario}
    outputs = {
        "clasificacion": {"segmento_cliente": "VIP"},
        "qa": {"veredicto": "aprobado", "precision": 3, "politica": 5, "tono": 5, "completitud": 5},
        "respuesta_final": "RMA-00002 https://example.test/another-label.pdf",
        "tool_calls": [call.model_dump() for call in calls],
    }

    checks = check_scenario(
        scenario["assertions"], classification=outputs["clasificacion"], qa=outputs["qa"],
        reply=outputs["respuesta_final"], calls=calls,
    )
    assert not checks["qa_min.precision"]
    assert not checks["tool_result.crear_etiqueta_devolucion.1"]
    assert scenario_assertions({"outputs": outputs}, ref)["score"] == 0
    outputs["qa"]["precision"] = 4
    outputs["respuesta_final"] = "RMA-00001 https://example.test/the-label.pdf"
    assert scenario_assertions({"outputs": outputs}, ref)["score"] == 1
    outputs["tool_calls"].reverse()
    assert tool_trajectory_match({"outputs": outputs}, ref)["score"] == 0


def test_pre_shipment_scenario_fails_if_rma_tool_is_invoked():
    from src.pipeline.orchestrator import ToolCallTrace
    from src.pipeline.scenario_checks import check_scenario

    scenario = next(row for row in load_eval_dataset() if row["id"] == "EVAL-021")
    calls = [ToolCallTrace(agent="devoluciones", tool="crear_etiqueta_devolucion")]
    assert not check_scenario(scenario["assertions"], calls=calls)["forbidden_tools"]


def test_qa_only_target_uses_injected_agent_and_actual_usage():
    from src.pipeline.langsmith_eval import make_pipeline_target, qa_quality_gate, scenario_assertions

    scenario = next(row for row in load_eval_dataset() if row["id"] == "EVAL-020")
    bad_rejection = EvaluacionQA(
        precision=3, politica=2, tono=4, completitud=3,
        veredicto="rechazado", respuesta_final="Needs review",
    )
    sistema = _sistema("consulta", qas=bad_rejection)
    example = scenario_to_langsmith_example(scenario, "test-dataset")
    run = {"outputs": make_pipeline_target(sistema)(example["inputs"])}
    assert sistema.qa.calls == 1 and sistema.triaje.calls == 0
    assert run["outputs"]["cost_usd"] == 0.000325
    assert run["outputs"]["ttft_seconds"] is None
    assert qa_quality_gate(run, example)["score"] == 1
    assert scenario_assertions(run, example)["score"] == 0


def test_golden_scenarios_have_valid_assertion_definitions():
    import re

    from src.pipeline.scenario_checks import ScenarioChecks

    for row in load_eval_dataset():
        rules = ScenarioChecks.model_validate(row["assertions"])
        assert all(1 <= index <= len(row["pass_fail_criteria"]) for index in rules.manual_criteria)
        for pattern in [*rules.reply_requires, *rules.reply_forbids]:
            re.compile(pattern)
        for result in rules.tool_results:
            for pattern in result.contains.values():
                re.compile(pattern)


def test_candidate_reuses_one_trusted_customer_snapshot(monkeypatch):
    from src.agents import load_spec
    from src.pipeline import context as context_module

    reads = []

    def read_snapshot(cliente_id):
        reads.append(cliente_id)
        return "Nombre privado", "Premium"

    repo = context_module.get_repo()
    monkeypatch.setattr(repo, "get_customer_snapshot", read_snapshot)
    monkeypatch.setattr(repo, "get_cliente", lambda *_args: pytest.fail("Full CRM lookup"))
    system = _sistema("consulta")
    system.snapshot_agents = frozenset({"triaje", "consultas"})
    result = procesar_ticket(TICKETS[4], system)
    assert reads == [TICKETS[4]["cliente_id"]]
    assert "Segmento verificado: Premium" in system.triaje.prompts[0]
    assert "Nombre privado" not in system.triaje.prompts[0]
    assert "segmento=Premium" in system.consultas.prompts[0]
    assert result.clasificacion.segmento_cliente == "Premium"
    assert [tool.name for tool in load_spec("triaje", "v6").tools] == ["consultar_ultimo_pedido"]
    assert "consultar_cliente" not in [tool.name for tool in load_spec("consultas", "v6").tools]


def test_golden_latest_order_checks_select_expected_calls_for_each_triaje_version():
    from src.pipeline.langsmith_eval import tool_trajectory_match

    row = next(scenario for scenario in load_eval_dataset() if scenario["id"] == "EVAL-007")
    reference = {"outputs": row}
    old_calls = row["expected_tool_calls"]
    new_calls = [{"agent": "triaje", "tool": "consultar_ultimo_pedido"}, *old_calls[1:]]
    assert tool_trajectory_match({"outputs": {"tool_calls": old_calls}}, reference)["score"] == 1
    candidate = {"customer_snapshot_agents": ["triaje", "consultas"], "tool_calls": new_calls}
    assert tool_trajectory_match({"outputs": candidate}, reference)["score"] == 1
    assert tool_trajectory_match({"outputs": {**candidate, "tool_calls": old_calls}}, reference)["score"] == 0
    assert tool_trajectory_match({"outputs": {**candidate, "tool_calls": new_calls[1:]}}, reference)["score"] == 0


@pytest.mark.parametrize(("message", "order_id", "allowed"), [
    ("Quiero devolver el último producto que compré", None, True),
    ("Quiero devolver mi compra más reciente", None, True),
    ("Quiero devolver mi último pedido P9003", None, False),
    ("Quiero devolver mi último pedido", "P9005", False),
    ("¿Cuál es el último estado de mi envío?", None, False),
])
def test_latest_order_lookup_requires_an_unresolved_latest_order_reference(message, order_id, allowed):
    from src.pipeline.context import solicita_ultimo_pedido

    assert solicita_ultimo_pedido({"mensaje": message, "pedido_id": order_id}) is allowed


@pytest.mark.parametrize("explicit_order", [None, "P9003"])
def test_verified_empty_latest_order_only_overrides_an_unresolved_order(explicit_order):
    from src.pipeline.eval_dataset import scenario_to_ticket

    scenario = next(row for row in load_eval_dataset() if row["id"] == "EVAL-023")
    ticket = {**scenario_to_ticket(scenario), "pedido_id": explicit_order}
    system = _sistema("devolucion")
    system.snapshot_agents = frozenset({"triaje"})
    system.scoped_order_agents = frozenset({"triaje", "devoluciones"})
    system.triaje = Stub(
        ClasificacionTicket(
            categoria="devolucion", prioridad="media", segmento_cliente="Estándar",
            pedido_id=explicit_order or "último", sku="SKU-002", resumen="r", justificacion="j",
        ),
        "triaje",
        tool_calls=[{"name": "consultar_ultimo_pedido", "args": {}, "id": "latest"}],
        tool_results=[ToolMessage(content='{"ultimo_pedido": null}', name="consultar_ultimo_pedido", tool_call_id="latest")],
    )

    result = procesar_ticket(ticket, system)

    assert system.triaje.contexts[0].latest_order_allowed is (explicit_order is None)
    assert system.devoluciones.contexts[0].latest_order_missing is (explicit_order is None)
    assert result.clasificacion.pedido_id == explicit_order
    assert result.clasificacion.sku == (None if explicit_order is None else "SKU-002")
    assert ("no encontró pedidos" in system.devoluciones.prompts[0]) is (explicit_order is None)


def test_verified_latest_order_reaches_returns_in_the_ticket_context():
    from src.pipeline.eval_dataset import scenario_to_ticket

    scenario = next(row for row in load_eval_dataset() if row["id"] == "EVAL-007")
    system = _sistema("devolucion")
    system.snapshot_agents = frozenset({"triaje"})
    system.scoped_order_agents = frozenset({"triaje", "devoluciones"})
    system.verified_return_handoff = True
    system.triaje = Stub(
        ClasificacionTicket(categoria="devolucion", prioridad="media", segmento_cliente="VIP", resumen="r", justificacion="j"),
        "triaje",
        tool_calls=[{"name": "consultar_ultimo_pedido", "args": {}, "id": "latest"}],
        tool_results=[ToolMessage(
            content='{"ultimo_pedido": {"pedido_id": "P9001"}}', name="consultar_ultimo_pedido", tool_call_id="latest",
        )],
    )

    result = procesar_ticket(scenario_to_ticket(scenario), system)

    assert result.clasificacion.pedido_id == "P9001"
    assert "Pedido referenciado: ninguno" in system.triaje.prompts[0]
    assert "Pedido referenciado: P9001" in system.devoluciones.prompts[0]
    assert "Pedido referenciado: ninguno" not in system.devoluciones.prompts[0]


def test_verified_label_is_sent_to_qa_after_truncation():
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from openai import LengthFinishReasonError
    from openai.types.chat import ChatCompletion

    from src.agents import build_agent
    from src.data.repositories import evaluation_repository
    from src.pipeline.eval_dataset import scenario_to_ticket
    from src.schemas.outputs import EvaluacionQACompacta

    class ReturnsModel(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, *args, **kwargs):
            if isinstance(messages[-1], ToolMessage) and messages[-1].name == "crear_etiqueta_devolucion":
                raise LengthFinishReasonError(completion=ChatCompletion(
                    id="test", choices=[], created=0, model="gpt-4o-mini", object="chat.completion",
                    usage={"prompt_tokens": 1556, "completion_tokens": 1500, "total_tokens": 3056},
                ))
            return super()._generate(messages, *args, **kwargs)

    calls = [
        ("consultar_pedido", {"pedido_id": "P9005"}),
        ("verificar_devolucion", {"pedido_id": "P9005", "sku": "SKU-001"}),
        ("crear_etiqueta_devolucion", {"pedido_id": "P9005", "sku": "SKU-001", "motivo": "Fallo de sonido"}),
    ]
    responses = [
        AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": name}])
        for name, args in calls
    ]
    qa = EvaluacionQACompacta(precision=5, politica=5, tono=5, completitud=5, veredicto="aprobado", respuesta_final=None)
    system = _sistema("devolucion", qas=qa)
    system.devoluciones = build_agent("devoluciones", version="v7", llm=ReturnsModel(responses=responses))
    scenario = next(row for row in load_eval_dataset() if row["id"] == "EVAL-022")

    with evaluation_repository():
        result = procesar_ticket(scenario_to_ticket(scenario), system)

    assert result.failed_stage is None and not result.escalado_humano
    rma = result.tool_calls[-1].result
    assert rma["rma_id"] in result.respuesta_final and rma["etiqueta_url"] in result.respuesta_final
    assert "5-7 días laborables" in result.respuesta_final
    assert rma["rma_id"] in system.qa.prompts[0]
    assert result.metricas_agentes[1].model_calls == 4
    assert result.metricas_agentes[1].total_tokens == 3056


def test_snapshot_benchmark_requires_trusted_tier_and_scoped_tools_for_partial_adoption():
    from src.pipeline.langsmith_eval import scenario_assertions, tool_trajectory_match

    row = next(scenario for scenario in load_eval_dataset() if scenario["id"] == "EVAL-005")
    reference = {"outputs": row}
    triaje_crm = next(call for call in row["expected_tool_calls"] if call["agent"] == "triaje")
    candidate = {
        "customer_snapshot_agents": ["consultas"],
        "customer_snapshot_loaded": True,
        "clasificacion": {"segmento_cliente": "Estándar", "pedido_id": None},
        "respuesta_final": "30 días. Reembolso de 5 a 7 días laborables. Productos personalizados y licencias no admitidos.",
        "tool_calls": [triaje_crm],
    }
    assert tool_trajectory_match({"outputs": candidate}, reference)["score"] == 1
    assert scenario_assertions({"outputs": candidate}, reference)["score"] == 1
    assert scenario_assertions({"outputs": {**candidate, "customer_snapshot_loaded": False}}, reference)["score"] == 0
    assert scenario_assertions({"outputs": {**candidate, "clasificacion": {"segmento_cliente": "VIP"}}}, reference)["score"] == 0
    unexpected = {**candidate, "tool_calls": [triaje_crm, {"agent": "triaje", "tool": "consultar_ultimo_pedido"}]}
    assert tool_trajectory_match({"outputs": unexpected}, reference)["score"] == 0


@pytest.mark.parametrize(("verdict", "rewrite", "expected"), [
    ("aprobado", None, "borrador"),
    ("reescrito", "texto corregido", "texto corregido"),
])
def test_compact_qa_only_supplies_text_when_rewriting(verdict, rewrite, expected):
    from src.agents import load_spec
    from src.schemas.outputs import EvaluacionQACompacta

    assert load_spec("qa", "v4").response_format is EvaluacionQACompacta
    assert load_spec("qa", "v3").response_format is EvaluacionQA
    review = EvaluacionQACompacta(
        precision=5, politica=5, tono=5, completitud=5, veredicto=verdict, respuesta_final=rewrite,
    )
    result = procesar_ticket(TICKETS[0], _sistema("consulta", qas=review))
    assert result.respuesta_final == expected
    assert result.qa.respuesta_final == rewrite
