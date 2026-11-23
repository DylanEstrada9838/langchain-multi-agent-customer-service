"""Integración con LangSmith Datasets & Experiments para automatizar evaluaciones."""
import os
import uuid
from pathlib import Path
from typing import Any

from langsmith import Client
from pydantic import BaseModel, ValidationError

from src import config
from src.agents import active_version, get_active_versions
from src.data.repositories import evaluation_repository
from src.pipeline import steps
from src.pipeline.context import TicketContext, generar_contexto
from src.pipeline.eval_dataset import load_eval_dataset, scenario_to_ticket
from src.pipeline.eval_provenance import evaluation_provenance
from src.schemas.outputs import BorradorRespuesta, ClasificacionTicket, EvaluacionQA
from src.pipeline.scenario_checks import ScenarioChecks, check_scenario, check_tools
from src.pipeline.quality_gate import compute_pipeline_metrics
from src.pipeline.orchestrator import (
    AgentRunError,
    SistemaMultiagente,
    ToolCallTrace,
    _run,
    construir_sistema,
    procesar_ticket,
)

_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


class DatasetSyncResult(BaseModel):
    dataset_name: str
    dataset_id: str
    total_examples: int
    created: bool


def scenario_to_langsmith_example(sc: dict[str, Any], dataset_name: str) -> dict[str, Any]:
    """Convierte una fila de `eval_dataset.jsonl` al formato `(id, inputs, outputs, metadata)` de LangSmith."""
    example_id = str(uuid.uuid5(_NAMESPACE, f"{dataset_name}:{sc['id']}"))
    context = sc.get("context") or {}
    qa_inputs = {}
    if context.get("stage_under_test") == "qa":
        qa_inputs = {"expected_routing": sc["expected_routing"]}
    return {
        "id": example_id,
        "inputs": {
            "id": sc["id"],
            "category": sc["category"],
            "context": context,
            **qa_inputs,
            "user_input": sc["user_input"],
        },
        "outputs": {
            "expected_routing": sc["expected_routing"],
            "expected_tool_calls": sc["expected_tool_calls"],
            "expected_behavior": sc.get("expected_behavior", ""),
            "pass_fail_criteria": sc.get("pass_fail_criteria") or [],
            "assertions": sc.get("assertions") or {},
        },
        "metadata": {
            "scenario_id": sc["id"],
            "category": sc["category"],
            "stage_under_test": (sc.get("context") or {}).get("stage_under_test", "pipeline"),
        },
    }


def sync_dataset_to_langsmith(
    dataset_name: str | None = None,
    *,
    dataset_path: Path | None = None,
    client: Any = None,
) -> DatasetSyncResult:
    """Sincroniza `data/eval_dataset.jsonl` con un Dataset de LangSmith de forma idempotente."""
    name = dataset_name or config.LANGSMITH_DATASET_NAME
    ls_client = client or Client()
    scenarios = load_eval_dataset(dataset_path)

    created = False
    if ls_client.has_dataset(dataset_name=name):
        dataset = ls_client.read_dataset(dataset_name=name)
    else:
        dataset = ls_client.create_dataset(
            dataset_name=name,
            description=(
                "Golden evaluation dataset (23 escenarios) para el sistema multiagente "
                f"de soporte al cliente de {config.EMPRESA_NOMBRE}."
            ),
        )
        created = True

    existing_by_id = {str(ex.id): ex for ex in ls_client.list_examples(dataset_id=dataset.id)}

    for sc in scenarios:
        ex_data = scenario_to_langsmith_example(sc, name)
        ex_id = ex_data["id"]
        if ex_id in existing_by_id:
            ls_client.update_example(
                example_id=ex_id,
                inputs=ex_data["inputs"],
                outputs=ex_data["outputs"],
                metadata=ex_data["metadata"],
            )
        else:
            ls_client.create_example(
                inputs=ex_data["inputs"],
                outputs=ex_data["outputs"],
                metadata=ex_data["metadata"],
                dataset_id=dataset.id,
                example_id=ex_id,
            )

    return DatasetSyncResult(
        dataset_name=name,
        dataset_id=str(dataset.id),
        total_examples=len(scenarios),
        created=created,
    )



def make_pipeline_target(
    sistema: SistemaMultiagente | None = None,
    *,
    versions: dict[str, str] | None = None,
    llm: Any = None,
):
    """Crea el `target` para `langsmith.evaluate()` que envuelve `procesar_ticket()`.

    Recibe `inputs` de un Example (`id`, `category`, `context`, `user_input`) y devuelve un dict
    JSON-serializable que consumirán los evaluators (Step 3). Los escenarios con
    `stage_under_test == "qa"` se ejecutan solo contra el agente QA.
    """
    sys_instance = sistema or construir_sistema(llm=llm, versions=versions)

    def target(inputs: dict[str, Any]) -> dict[str, Any]:
        sc = {
            "id": inputs["id"],
            "category": inputs["category"],
            "context": inputs.get("context") or {},
            "user_input": inputs["user_input"],
        }

        ticket = scenario_to_ticket(sc)
        if sc["context"].get("stage_under_test") == "qa":
            routing = inputs["expected_routing"]
            classification = ClasificacionTicket(
                categoria=routing["categoria"],
                prioridad=routing["prioridad"],
                segmento_cliente=routing["segmento_cliente"],
                resumen=inputs["user_input"][:80],
                pedido_id=ticket["pedido_id"],
                justificacion="eval_override",
            )
            draft = BorradorRespuesta.model_validate(sc["context"]["specialist_draft_override"])
            qa_ver = sys_instance.versiones.get("qa") or active_version("qa")
            qa = None
            try:
                assessment, metrics = _run(
                    sys_instance.qa,
                    steps.paso_qa(generar_contexto(ticket), classification, draft),
                    context=TicketContext(ticket["cliente_id"]), agent_name="qa", version=qa_ver,
                )
            except AgentRunError as exc:
                metrics = exc.metrics
            else:
                try:
                    qa = EvaluacionQA.model_validate(assessment)
                except ValidationError:
                    pass
            return {
                "stage": "qa",
                "qa": qa.model_dump() if qa is not None else None,
                "failed_stage": "qa" if qa is None else None,
                "tool_calls": [call.model_dump() for call in metrics.tool_calls],
                "total_tokens": metrics.total_tokens,
                "token_usage_complete": metrics.token_usage_complete,
                "cost_usd": metrics.cost_usd,
                "ttft_seconds": None,
                "segundos": metrics.segundos,
            }

        res = procesar_ticket(ticket, sys_instance)
        return {
            "stage": "pipeline",
            "categoria": res.clasificacion.categoria if res.clasificacion else None,
            "prioridad": res.clasificacion.prioridad if res.clasificacion else None,
            "clasificacion": res.clasificacion.model_dump() if res.clasificacion else None,
            "borrador": {"requiere_escalado": res.borrador.requiere_escalado} if res.borrador else None,
            "failed_stage": res.failed_stage,
            "especialista": res.especialista,
            "escalado_humano": res.escalado_humano,
            "motivo_escalado": res.motivo_escalado,
            "intentos_qa": res.intentos_qa,
            "qa": res.qa.model_dump() if res.qa is not None else None,
            "respuesta_final": res.respuesta_final,
            "tool_calls": [tc.model_dump() for tc in res.tool_calls],
            "versiones_agentes": res.versiones_agentes,
            "customer_snapshot_agents": sorted(sys_instance.snapshot_agents),
            "customer_snapshot_loaded": res.customer_snapshot_loaded,
            "total_tokens": res.total_tokens,
            "token_usage_complete": res.token_usage_complete,
            "cost_usd": res.cost_usd,
            "ttft_seconds": res.ttft_seconds,
            "segundos": res.segundos,
        }

    return target


# ---------------------------------------------------------------------------
# Evaluators de código (deterministas) -- mismos 5 checks que `evaluate_pipeline`
# ---------------------------------------------------------------------------

def _outputs_of(run: Any) -> dict[str, Any]:
    return (getattr(run, "outputs", None) or {}) if not isinstance(run, dict) else (run.get("outputs") or {})


def _ref_of(example: Any) -> dict[str, Any]:
    return (getattr(example, "outputs", None) or {}) if not isinstance(example, dict) else (example.get("outputs") or {})


def _result(key: str, ok: bool | None, comment: str = "") -> dict[str, Any]:
    if ok is None:
        return {"key": key, "score": None, "comment": comment or "n/a (escenario de etapa QA)"}
    return {"key": key, "score": int(ok), "comment": comment}


def categoria_match(run: Any, example: Any) -> dict[str, Any]:
    out, ref = _outputs_of(run), _ref_of(example)
    if out.get("stage") == "qa":
        return _result("categoria_match", None)
    exp = ref["expected_routing"]["categoria"]
    return _result("categoria_match", out.get("categoria") == exp, f"esperado={exp} real={out.get('categoria')}")


def especialista_match(run: Any, example: Any) -> dict[str, Any]:
    out, ref = _outputs_of(run), _ref_of(example)
    if out.get("stage") == "qa":
        return _result("especialista_match", None)
    exp = ref["expected_routing"]["especialista"]
    return _result("especialista_match", out.get("especialista") == exp, f"esperado={exp} real={out.get('especialista')}")


def escalado_match(run: Any, example: Any) -> dict[str, Any]:
    out, ref = _outputs_of(run), _ref_of(example)
    if out.get("stage") == "qa":
        return _result("escalado_match", None)
    exp = ref["expected_routing"]["escalado_humano"]
    return _result("escalado_match", out.get("escalado_humano") == exp, f"esperado={exp} real={out.get('escalado_humano')}")


def tool_trajectory_match(run: Any, example: Any) -> dict[str, Any]:
    out, ref = _outputs_of(run), _ref_of(example)
    if out.get("stage") == "qa":
        ok = out.get("tool_calls") == []
        return _result("tool_trajectory_match", ok, "QA no debe llamar herramientas")
    actual = [ToolCallTrace(**tc) for tc in out.get("tool_calls", [])]
    rules = ScenarioChecks.model_validate(ref.get("assertions") or {})
    snapshot_agents = set(out.get("customer_snapshot_agents") or [])
    expected = ref.get("expected_tool_calls", [])
    latest_order_expected = "triaje" in snapshot_agents and rules.latest_order_lookup
    if snapshot_agents and isinstance(expected, list):
        expected = [
            call for call in expected
            if not (call["tool"] == "consultar_cliente" and call["agent"] in snapshot_agents)
        ]
        if latest_order_expected:
            expected = [{"agent": "triaje", "tool": "consultar_ultimo_pedido"}, *expected]
    ok, recall = check_tools(expected, actual, ordered=rules.ordered_tools)
    unexpected = [
        f"{call.agent}.{call.tool}" for call in actual
        if (call.tool == "consultar_cliente" and call.agent in snapshot_agents)
        or (call.tool == "consultar_ultimo_pedido" and not latest_order_expected)
    ]
    detail = f"; unexpected={', '.join(unexpected)}" if unexpected else ""
    return _result("tool_trajectory_match", ok and not unexpected, f"recall={recall}{detail}")


def qa_quality_gate(run: Any, example: Any) -> dict[str, Any]:
    out = _outputs_of(run)
    if out.get("failed_stage"):
        return _result("qa_quality_gate", False, f"Fallo de ejecucion: {out['failed_stage']}")
    if out.get("stage") == "qa":
        ok = (out.get("qa") or {}).get("veredicto") == "rechazado"
        return _result("qa_quality_gate", ok, "QA rechaza borrador contradictorio")
    veredicto = (out.get("qa") or {}).get("veredicto")
    ok = veredicto is not None and (veredicto in ("aprobado", "reescrito") or bool(out.get("escalado_humano")))
    return _result("qa_quality_gate", ok, f"veredicto={veredicto}")


def scenario_assertions(run: Any, example: Any) -> dict[str, Any]:
    out, ref = _outputs_of(run), _ref_of(example)
    assertions = ref.get("assertions")
    if assertions is None:
        return _result("scenario_assertions", None, "No scenario assertions")
    rules = ScenarioChecks.model_validate(assertions)
    checks = check_scenario(
        assertions,
        classification=out.get("clasificacion"),
        draft=out.get("borrador"),
        qa=out.get("qa"),
        reply=out.get("respuesta_final") or "",
        calls=[ToolCallTrace(**call) for call in out.get("tool_calls", [])],
    )
    if out.get("customer_snapshot_agents"):
        checks["customer_snapshot_loaded"] = out.get("customer_snapshot_loaded") is True
        expected_tier = (ref.get("expected_routing") or {}).get("segmento_cliente")
        observed_tier = (out.get("clasificacion") or {}).get("segmento_cliente")
        checks["verified_customer_tier"] = expected_tier is not None and observed_tier == expected_tier
    failed = ", ".join(key for key, ok in checks.items() if not ok) or "none"
    manual = ", ".join(str(index) for index in rules.manual_criteria) or "none"
    return _result("scenario_assertions", all(checks.values()), f"Failed: {failed}. Manual criteria: {manual}.")


CODE_EVALUATORS = [
    categoria_match,
    especialista_match,
    escalado_match,
    tool_trajectory_match,
    qa_quality_gate,
    scenario_assertions,
]


# ---------------------------------------------------------------------------
# Summary evaluators (métricas agregadas del experimento, visibles en la UI de LangSmith)
# ---------------------------------------------------------------------------

_CODE_KEYS = [ev.__name__ for ev in CODE_EVALUATORS]


def _pair_to_row(outputs, example_inputs, example_outputs, *, feedback=None) -> dict[str, Any]:
    stage = "qa" if (example_inputs.get("context") or {}).get("stage_under_test") == "qa" else "pipeline"
    outputs = outputs or {}
    if not outputs:
        checks = {key: {"score": 0, "comment": "El escenario no devolvio resultados."} for key in _CODE_KEYS}
    elif feedback is None:
        run_like, ref_like = {"outputs": outputs}, {"outputs": example_outputs}
        checks = {ev.__name__: ev(run_like, ref_like) for ev in CODE_EVALUATORS}
    else:
        checks = {item.key: {"score": item.score, "comment": item.comment} for item in feedback}

    comments = {}
    scores = {}
    for key in _CODE_KEYS:
        check = checks.get(key, {"score": 0, "comment": "No se recibio feedback del evaluador."})
        score = check["score"]
        not_applicable = stage == "qa" and key in {"categoria_match", "especialista_match", "escalado_match"}
        optional_assertions = key == "scenario_assertions" and "assertions" not in example_outputs
        if score is None and not (not_applicable or optional_assertions):
            score = 0
        scores[key] = score
        if score == 0 and check["comment"]:
            comments[key] = check["comment"]
    rules = ScenarioChecks.model_validate(example_outputs.get("assertions") or {})
    if rules.manual_criteria:
        comments["manual_review"] = ", ".join(str(index) for index in rules.manual_criteria)
    return {"scenario_id": example_inputs.get("id", ""), "stage": stage, "scores": scores, "outputs": outputs, "comments": comments}


def summarize_pipeline(runs: list[Any], examples: list[Any]) -> dict:
    rows = [
        _pair_to_row(getattr(run, "outputs", None), example.inputs or {}, example.outputs or {})
        for run, example in zip(runs, examples, strict=True)
    ]
    return {"results": [
        {"key": key, "score": value}
        for key, value in compute_pipeline_metrics(rows).items() if value is not None
    ]}


# ---------------------------------------------------------------------------
# Runner de experimentos (`--eval --langsmith`)
# ---------------------------------------------------------------------------

class ExperimentSummary(BaseModel):
    experiment_name: str
    experiment_url: str = ""
    dataset_name: str
    versions: dict[str, str]
    total_examples: int
    passed_examples: int
    pass_rate: float
    metric_means: dict[str, float]
    metrics: dict[str, float | None]
    failed_scenarios: dict[str, list[str]]
    scenario_feedback: dict[str, dict[str, str]]
    scenario_ids: list[str]
    partial: bool
    provenance: dict[str, Any]


def summarize_experiment_rows(rows: list[dict[str, Any]]) -> tuple[int, int, dict[str, float], dict[str, list[str]]]:
    """Agrega filas `{scenario_id, scores: {key: 0|1|None}}` en pass_rate y media por evaluator."""
    sums: dict[str, list[int]] = {}
    failed: dict[str, list[str]] = {}
    passed = 0
    for row in rows:
        scores = {k: v for k, v in row["scores"].items() if v is not None}
        for k, v in scores.items():
            sums.setdefault(k, []).append(int(v))
        bad = [k for k, v in scores.items() if not v]
        if bad:
            failed[row["scenario_id"]] = bad
        passed += int(not bad and bool(scores))
    means = {k: round(sum(v) / len(v), 4) for k, v in sums.items()}
    return len(rows), passed, means, failed


def _ci_metadata() -> dict[str, str]:
    keys = ("GITHUB_SHA", "GITHUB_REF_NAME", "GITHUB_HEAD_REF", "GITHUB_RUN_ID", "GITHUB_EVENT_NAME")
    return {k.lower(): os.environ[k] for k in keys if os.environ.get(k)}


def validate_remote_examples(examples: list[Any], rows: list[dict], dataset_name: str) -> None:
    expected = {row["id"]: scenario_to_langsmith_example(row, dataset_name) for row in rows}
    actual = {}
    for example in examples:
        name = (example.inputs or {}).get("id")
        if name in actual:
            raise ValueError(f"Escenario duplicado en LangSmith: {name}")
        actual[name] = example
    missing, extra = sorted(expected.keys() - actual.keys()), sorted(str(key) for key in actual.keys() - expected.keys())
    changed = sorted(
        name for name in expected.keys() & actual.keys()
        if actual[name].inputs != expected[name]["inputs"] or actual[name].outputs != expected[name]["outputs"]
    )
    if missing or extra or changed:
        raise ValueError(f"Dataset LangSmith desactualizado. Faltan={missing}, sobran={extra}, cambiaron={changed}. Ejecuta --sync-dataset y revisa los ejemplos extra.")


def run_langsmith_experiment(
    dataset_name: str | None = None,
    *,
    versions: dict[str, str] | None = None,
    category: str | None = None,
    limit: int | None = None,
    max_concurrency: int = 4,
    experiment_prefix: str | None = None,
    client: Any = None,
    llm: Any = None,
) -> ExperimentSummary:
    """Ejecuta `langsmith.evaluate()` con el target del pipeline, evaluators de código y summary evaluators."""
    from langsmith import evaluate

    name = dataset_name or config.LANGSMITH_DATASET_NAME
    ls_client = client or Client()
    examples = list(ls_client.list_examples(dataset_name=name))
    validate_remote_examples(examples, load_eval_dataset(), name)
    if category:
        examples = [example for example in examples if example.inputs["category"] == category]
    examples.sort(key=lambda example: example.inputs["id"])
    if limit is not None:
        examples = examples[:limit]
    if not examples:
        raise ValueError(f"El dataset '{name}' no tiene ejemplos para este filtro.")

    used_versions = {**get_active_versions(), **(versions or {})}
    provenance = evaluation_provenance(used_versions)
    ver_tag = "-".join(sorted(set(used_versions.values()))) if len(set(used_versions.values())) == 1 else "mixed"
    prefix = experiment_prefix or f"pipeline-{ver_tag}"

    with evaluation_repository():
        results = evaluate(
            make_pipeline_target(versions=versions, llm=llm),
            data=examples,
            evaluators=CODE_EVALUATORS,
            summary_evaluators=[summarize_pipeline],
            experiment_prefix=prefix,
            max_concurrency=max_concurrency,
            client=ls_client,
            metadata={"versions": used_versions, "kind": "code-evaluators", **provenance, **_ci_metadata()},
        )

        rows = []
        for r in results:
            outputs = getattr(r["run"], "outputs", None)
            ex = r["example"]
            row = _pair_to_row(outputs, ex.inputs or {}, ex.outputs or {}, feedback=r["evaluation_results"]["results"])
            rows.append(row)

    scenario_ids = sorted(row["scenario_id"] for row in rows)
    if scenario_ids != sorted(example.inputs["id"] for example in examples):
        raise RuntimeError("LangSmith no devolvio todos los escenarios seleccionados.")
    if all(not row["outputs"] for row in rows):
        raise RuntimeError("Todas las ejecuciones del target fallaron (¿credenciales o red?); no hay resultados que evaluar.")

    total, passed, means, failed = summarize_experiment_rows(rows)
    try:
        url = ls_client.read_project(project_name=results.experiment_name).url or ""
    except Exception:
        url = ""
    return ExperimentSummary(
        experiment_name=results.experiment_name,
        experiment_url=url,
        dataset_name=name,
        versions=used_versions,
        total_examples=total,
        passed_examples=passed,
        pass_rate=round(passed / max(total, 1), 4),
        metric_means=means,
        metrics=compute_pipeline_metrics(rows),
        failed_scenarios=failed,
        scenario_feedback={row["scenario_id"]: row["comments"] for row in rows if row["comments"]},
        scenario_ids=scenario_ids,
        partial=category is not None or limit is not None,
        provenance=provenance,
    )
