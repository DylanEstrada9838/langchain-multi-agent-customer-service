"""Integración con LangSmith Datasets & Experiments para automatizar evaluaciones."""
import uuid
from pathlib import Path
from typing import Any

from langsmith import Client
from pydantic import BaseModel

from src import config
from src.pipeline.evaluator import (
    DEFAULT_DATASET_PATH,
    _check_tools_match,
    _scenario_to_ticket,
    evaluate_qa_scenario,
    load_eval_dataset,
)
from src.pipeline.orchestrator import (
    SistemaMultiagente,
    ToolCallTrace,
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
    return {
        "id": example_id,
        "inputs": {
            "id": sc["id"],
            "category": sc["category"],
            "context": sc.get("context") or {},
            "user_input": sc["user_input"],
        },
        "outputs": {
            "expected_routing": sc["expected_routing"],
            "expected_tool_calls": sc["expected_tool_calls"],
            "expected_behavior": sc.get("expected_behavior", ""),
            "pass_fail_criteria": sc.get("pass_fail_criteria") or [],
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
    scenarios = load_eval_dataset(dataset_path or DEFAULT_DATASET_PATH)

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
    `stage_under_test == "qa"` se ejecutan solo contra el agente QA, igual que `evaluate_pipeline`.
    """
    sys_instance = sistema or construir_sistema(llm=llm, versions=versions)

    def target(inputs: dict[str, Any]) -> dict[str, Any]:
        sc = {
            "id": inputs["id"],
            "category": inputs["category"],
            "context": inputs.get("context") or {},
            "user_input": inputs["user_input"],
        }

        if sc["context"].get("stage_under_test") == "qa":
            # evaluate_qa_scenario necesita expected_routing para construir la clasificación de entrada
            full = next(s for s in load_eval_dataset() if s["id"] == sc["id"])
            qa_ver = sys_instance.versiones.get("qa", config.DEFAULT_AGENT_VERSION)
            res_qa = evaluate_qa_scenario(full, version=qa_ver, llm=llm)
            return {
                "stage": "qa",
                "qa": res_qa.detalles.get("qa", {}),
                "stage_checks": res_qa.checks,
                "tool_calls": [tc.model_dump() for tc in res_qa.actual_tools],
                "total_tokens": res_qa.total_tokens,
                "segundos": res_qa.segundos,
            }

        res = procesar_ticket(_scenario_to_ticket(sc), sys_instance)
        return {
            "stage": "pipeline",
            "categoria": res.clasificacion.categoria,
            "prioridad": res.clasificacion.prioridad,
            "especialista": res.especialista,
            "escalado_humano": res.escalado_humano,
            "motivo_escalado": res.motivo_escalado,
            "intentos_qa": res.intentos_qa,
            "qa": res.qa.model_dump(),
            "respuesta_final": res.respuesta_final,
            "tool_calls": [tc.model_dump() for tc in res.tool_calls],
            "versiones_agentes": res.versiones_agentes,
            "total_tokens": res.total_tokens,
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
        ok = bool((out.get("stage_checks") or {}).get("no_tools_called", False))
        return _result("tool_trajectory_match", ok, "QA no debe llamar herramientas")
    actual = [ToolCallTrace(**tc) for tc in out.get("tool_calls", [])]
    ok, recall = _check_tools_match(ref.get("expected_tool_calls", []), actual)
    return _result("tool_trajectory_match", ok, f"recall={recall}")


def qa_quality_gate(run: Any, example: Any) -> dict[str, Any]:
    out = _outputs_of(run)
    if out.get("stage") == "qa":
        ok = all((out.get("stage_checks") or {}).values())
        return _result("qa_quality_gate", ok, "QA rechaza borrador contradictorio")
    veredicto = (out.get("qa") or {}).get("veredicto")
    ok = veredicto in ("aprobado", "reescrito") or bool(out.get("escalado_humano"))
    return _result("qa_quality_gate", ok, f"veredicto={veredicto}")


CODE_EVALUATORS = [
    categoria_match,
    especialista_match,
    escalado_match,
    tool_trajectory_match,
    qa_quality_gate,
]


# ---------------------------------------------------------------------------
# Runner de experimentos (`--eval --langsmith`)
# ---------------------------------------------------------------------------

class ExperimentSummary(BaseModel):
    experiment_name: str
    dataset_name: str
    total_examples: int
    passed_examples: int
    pass_rate: float
    metric_means: dict[str, float]
    failed_scenarios: dict[str, list[str]]


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
    """Ejecuta `langsmith.evaluate()` con el target del pipeline y los evaluators de código."""
    from langsmith import evaluate

    name = dataset_name or config.LANGSMITH_DATASET_NAME
    ls_client = client or Client()
    examples = list(ls_client.list_examples(dataset_name=name))
    if category:
        examples = [e for e in examples if (e.metadata or {}).get("category") == category]
    examples.sort(key=lambda e: (e.metadata or {}).get("scenario_id", ""))
    if limit:
        examples = examples[:limit]
    if not examples:
        raise ValueError(f"El dataset '{name}' no tiene ejemplos (¿ejecutaste --sync-dataset?).")

    ver_tag = ",".join(f"{k}:{v}" for k, v in (versions or {}).items()) or config.DEFAULT_AGENT_VERSION
    prefix = experiment_prefix or f"pipeline-{ver_tag}".replace(":", "-").replace(",", "_")

    results = evaluate(
        make_pipeline_target(versions=versions, llm=llm),
        data=examples,
        evaluators=CODE_EVALUATORS,
        experiment_prefix=prefix,
        max_concurrency=max_concurrency,
        client=ls_client,
        metadata={"versions": versions or config.DEFAULT_AGENT_VERSION, "kind": "code-evaluators"},
    )

    rows = []
    for r in results:
        scores = {er.key: er.score for er in r["evaluation_results"]["results"]}
        rows.append({"scenario_id": r["example"].metadata.get("scenario_id", str(r["example"].id)), "scores": scores})

    total, passed, means, failed = summarize_experiment_rows(rows)
    return ExperimentSummary(
        experiment_name=results.experiment_name,
        dataset_name=name,
        total_examples=total,
        passed_examples=passed,
        pass_rate=round(passed / max(total, 1), 4),
        metric_means=means,
        failed_scenarios=failed,
    )
