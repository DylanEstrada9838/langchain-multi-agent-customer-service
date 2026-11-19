"""Evaluador de versiones de agentes y del pipeline completo con jerarquía de Quality Targets."""
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from src import config
from src.agents import build_agent
from src.pipeline import steps
from src.pipeline.context import generar_contexto
from src.pipeline.orchestrator import (
    ResultadoTicket,
    SistemaMultiagente,
    ToolCallTrace,
    _run,
    construir_sistema,
    procesar_ticket,
)
from src.schemas.outputs import BorradorRespuesta, ClasificacionTicket

DEFAULT_DATASET_PATH = config.ROOT / "data" / "eval_dataset.jsonl"

# Umbrales oficiales de calidad (Quality Targets) ordenados por prioridad de decisión
TRIAGE_QUALITY_TARGETS: list[tuple[str, str, float, str]] = [
    ("1. Hard Gate (CRM Lookup)", "tool_call_accuracy", 1.00, "Debe consultar siempre al cliente en el CRM"),
    ("2. Primary Winner Metric", "category_accuracy", 0.90, "Determina a qué especialista se enruta el ticket"),
    ("3. Tie-Breaker", "priority_accuracy", 0.85, "Desempata versiones con igual acierto de categoría"),
]

PIPELINE_QUALITY_TARGETS: list[tuple[str, str, float, str]] = [
    ("1. Hard Gate (Safety & Escalation)", "escalation_accuracy", 0.95, "No fallar en escalados obligatorios ni falsos escalados"),
    ("1b. Hard Gate (Policy Score / 5)", "mean_qa_politica", 4.50, "Cumplimiento estricto de políticas y titularidad"),
    ("2. Primary Winner Metric", "pass_rate", 0.85, "% de escenarios resueltos de principio a fin sin ningún fallo"),
    ("3. Tie-Breaker", "first_pass_qa_approval_rate", 0.80, "% de tickets aprobados por QA a la primera sin reintento"),
]


class QualityTargetEvaluation(BaseModel):
    priority: str
    metric: str
    value: float
    target: float
    passed: bool
    description: str


class ScenarioEvalResult(BaseModel):
    scenario_id: str
    category: str
    passed: bool
    checks: dict[str, bool] = Field(default_factory=dict)
    expected_tools: list[dict[str, Any]] | str = Field(default_factory=list)
    actual_tools: list[ToolCallTrace] = Field(default_factory=list)
    segundos: float = 0.0
    total_tokens: int = 0
    detalles: dict[str, Any] = Field(default_factory=dict)


class EvalSummaryReport(BaseModel):
    target: str
    versiones: dict[str, str]
    total_scenarios: int
    passed_scenarios: int
    pass_rate: float
    quality_gate_passed: bool
    quality_targets: list[QualityTargetEvaluation] = Field(default_factory=list)
    diagnostics: dict[str, float] = Field(default_factory=dict)
    results: list[ScenarioEvalResult] = Field(default_factory=list)


def _evaluate_targets(
    target_defs: list[tuple[str, str, float, str]],
    values: dict[str, float],
) -> tuple[bool, list[QualityTargetEvaluation]]:
    evals: list[QualityTargetEvaluation] = []
    for prio, key, threshold, desc in target_defs:
        val = values.get(key, 0.0)
        evals.append(
            QualityTargetEvaluation(
                priority=prio,
                metric=key,
                value=val,
                target=threshold,
                passed=val >= threshold,
                description=desc,
            )
        )
    return all(e.passed for e in evals), evals


def load_eval_dataset(
    path: Path | None = None,
    *,
    category: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    file_path = path or DEFAULT_DATASET_PATH
    rows = [
        json.loads(line)
        for line in file_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if category:
        rows = [r for r in rows if r.get("category") == category]
    return rows[:limit] if limit else rows


def _scenario_to_ticket(sc: dict[str, Any]) -> dict[str, Any]:
    ctx = sc.get("context") or {}
    return {
        "id": sc["id"],
        "cliente_id": ctx.get("cliente_id", "C900"),
        "pedido_id": ctx.get("pedido_id"),
        "asunto": f"Eval {sc['id']} ({sc['category']})",
        "mensaje": sc["user_input"],
    }


def _check_tools_match(
    expected: list[dict[str, Any]] | str,
    actual: list[ToolCallTrace],
    *,
    agent_filter: str | None = None,
) -> tuple[bool, float]:
    """Compara las llamadas a herramientas esperadas frente a las ejecutadas realmente."""
    filtered_actual = [tc for tc in actual if not agent_filter or tc.agent == agent_filter]
    if expected == "none":
        ok = len(filtered_actual) == 0
        return ok, (1.0 if ok else 0.0)

    exp_list = [
        e for e in (expected if isinstance(expected, list) else [])
        if not agent_filter or e.get("agent") == agent_filter
    ]
    if not exp_list:
        return True, 1.0

    matched = 0
    for exp in exp_list:
        exp_tool = exp.get("tool")
        exp_args = exp.get("args") or {}
        for act in filtered_actual:
            if act.tool != exp_tool:
                continue
            key_ok = all(
                str(act.args.get(k, "")).upper() == str(v).upper()
                for k, v in exp_args.items()
                if k in ("cliente_id", "pedido_id", "sku", "tipo", "zona") and v is not None
            )
            if key_ok:
                matched += 1
                break

    recall = matched / len(exp_list)
    return matched == len(exp_list), round(recall, 4)


def evaluate_triage_version(
    scenarios: list[dict[str, Any]],
    *,
    version: str = "v1",
    llm: Any = None,
) -> EvalSummaryReport:
    """Evalúa únicamente una versión del agente `triaje` de forma aislada."""
    agent = build_agent("triaje", version=version, llm=llm)
    results: list[ScenarioEvalResult] = []
    cat_hits = prio_hits = seg_hits = tool_hits = 0
    evaluated = [sc for sc in scenarios if (sc.get("context") or {}).get("stage_under_test") != "qa"]

    for sc in evaluated:
        ticket = _scenario_to_ticket(sc)
        ctx = generar_contexto(ticket)
        exp_r = sc["expected_routing"]
        try:
            clasif, m = _run(agent, steps.paso_triaje(ctx), agent_name="triaje", version=version)
        except Exception as exc:
            results.append(
                ScenarioEvalResult(
                    scenario_id=sc["id"],
                    category=sc["category"],
                    passed=False,
                    checks={"execution_ok": False},
                    detalles={"error": str(exc), "esperado": exp_r},
                )
            )
            continue

        cat_ok = clasif.categoria == exp_r["categoria"]
        prio_ok = clasif.prioridad == exp_r["prioridad"]
        seg_ok = clasif.segmento_cliente.lower() == exp_r["segmento_cliente"].lower()
        tools_ok, _ = _check_tools_match(sc["expected_tool_calls"], m.tool_calls, agent_filter="triaje")

        cat_hits += int(cat_ok)
        prio_hits += int(prio_ok)
        seg_hits += int(seg_ok)
        tool_hits += int(tools_ok)

        checks = {
            "categoria_match": cat_ok,
            "prioridad_match": prio_ok,
            "segmento_match": seg_ok,
            "tool_calls_match": tools_ok,
        }
        results.append(
            ScenarioEvalResult(
                scenario_id=sc["id"],
                category=sc["category"],
                passed=all(checks.values()),
                checks=checks,
                expected_tools=[e for e in sc["expected_tool_calls"] if isinstance(e, dict) and e.get("agent") == "triaje"],
                actual_tools=m.tool_calls,
                segundos=m.segundos,
                total_tokens=m.total_tokens,
                detalles={"predicho": clasif.model_dump(), "esperado": exp_r},
            )
        )

    n = max(len(results), 1)
    passed = sum(1 for r in results if r.passed)
    pass_rate = round(passed / n, 4)
    all_values = {
        "pass_rate": pass_rate,
        "tool_call_accuracy": round(tool_hits / n, 4),
        "category_accuracy": round(cat_hits / n, 4),
        "priority_accuracy": round(prio_hits / n, 4),
        "segment_accuracy": round(seg_hits / n, 4),
        "avg_latency_seconds": round(sum(r.segundos for r in results) / n, 2),
        "avg_tokens": round(sum(r.total_tokens for r in results) / n, 1),
    }
    gate_ok, targets = _evaluate_targets(TRIAGE_QUALITY_TARGETS, all_values)

    return EvalSummaryReport(
        target=f"triaje:{version}",
        versiones={"triaje": version},
        total_scenarios=len(results),
        passed_scenarios=passed,
        pass_rate=pass_rate,
        quality_gate_passed=gate_ok,
        quality_targets=targets,
        diagnostics={
            "pass_rate": pass_rate,
            "segment_accuracy": all_values["segment_accuracy"],
            "avg_latency_seconds": all_values["avg_latency_seconds"],
            "avg_tokens": all_values["avg_tokens"],
        },
        results=results,
    )


def evaluate_qa_scenario(sc: dict[str, Any], *, version: str = "v1", llm: Any = None) -> ScenarioEvalResult:
    """Evalúa un escenario específico de QA con `specialist_draft_override` (como EVAL-020)."""
    agent = build_agent("qa", version=version, llm=llm)
    ticket = _scenario_to_ticket(sc)
    ctx = generar_contexto(ticket)
    exp_r = sc["expected_routing"]
    clasif = ClasificacionTicket(
        categoria=exp_r["categoria"],
        prioridad=exp_r["prioridad"],
        segmento_cliente=exp_r["segmento_cliente"],
        resumen=sc["user_input"][:80],
        pedido_id=ticket.get("pedido_id"),
        justificacion="eval_override",
    )
    borrador = BorradorRespuesta(**sc["context"]["specialist_draft_override"])
    qa, m = _run(agent, steps.paso_qa(ctx, clasif, borrador), agent_name="qa", version=version)

    no_tools = len(m.tool_calls) == 0
    rejected_bad_draft = qa.veredicto == "rechazado" and qa.precision <= 2 and qa.politica <= 2
    checks = {"no_tools_called": no_tools, "rejected_contradictory_draft": rejected_bad_draft}
    return ScenarioEvalResult(
        scenario_id=sc["id"],
        category=sc["category"],
        passed=all(checks.values()),
        checks=checks,
        expected_tools="none",
        actual_tools=m.tool_calls,
        segundos=m.segundos,
        total_tokens=m.total_tokens,
        detalles={"qa": qa.model_dump()},
    )


def evaluate_pipeline(
    scenarios: list[dict[str, Any]],
    *,
    sistema: SistemaMultiagente | None = None,
    versions: dict[str, str] | None = None,
    llm: Any = None,
) -> EvalSummaryReport:
    """Evalúa el pipeline completo frente a `eval_dataset.jsonl` con los Quality Targets jerárquicos."""
    sys_instance = sistema or construir_sistema(llm=llm, versions=versions)
    results: list[ScenarioEvalResult] = []

    cat_hits = esp_hits = esc_hits = first_pass_qa = 0
    tool_recalls: list[float] = []
    qa_prec, qa_pol, qa_tono, qa_comp = [], [], [], []
    end_to_end_count = 0

    for sc in scenarios:
        if (sc.get("context") or {}).get("stage_under_test") == "qa":
            qa_ver = sys_instance.versiones.get("qa", config.DEFAULT_AGENT_VERSION)
            try:
                results.append(evaluate_qa_scenario(sc, version=qa_ver, llm=llm))
            except Exception as exc:
                results.append(
                    ScenarioEvalResult(
                        scenario_id=sc["id"],
                        category=sc["category"],
                        passed=False,
                        checks={"execution_ok": False},
                        detalles={"error": str(exc)},
                    )
                )
            continue

        end_to_end_count += 1
        ticket = _scenario_to_ticket(sc)
        exp_r = sc["expected_routing"]
        try:
            res: ResultadoTicket = procesar_ticket(ticket, sys_instance)
        except Exception as exc:
            results.append(
                ScenarioEvalResult(
                    scenario_id=sc["id"],
                    category=sc["category"],
                    passed=False,
                    checks={"execution_ok": False},
                    detalles={"error": str(exc), "esperado": exp_r},
                )
            )
            continue

        cat_ok = res.clasificacion.categoria == exp_r["categoria"]
        esp_ok = res.especialista == exp_r["especialista"]
        esc_ok = res.escalado_humano == exp_r["escalado_humano"]
        tools_ok, recall = _check_tools_match(sc["expected_tool_calls"], res.tool_calls)
        qa_ok = res.qa.veredicto in ("aprobado", "reescrito") or res.escalado_humano

        cat_hits += int(cat_ok)
        esp_hits += int(esp_ok)
        esc_hits += int(esc_ok)
        first_pass_qa += int(res.intentos_qa == 1 and res.qa.veredicto in ("aprobado", "reescrito"))
        tool_recalls.append(recall)

        qa_prec.append(res.qa.precision)
        qa_pol.append(res.qa.politica)
        qa_tono.append(res.qa.tono)
        qa_comp.append(res.qa.completitud)

        checks = {
            "categoria_match": cat_ok,
            "especialista_match": esp_ok,
            "escalado_match": esc_ok,
            "tool_trajectory_match": tools_ok,
            "qa_quality_gate": qa_ok,
        }
        results.append(
            ScenarioEvalResult(
                scenario_id=sc["id"],
                category=sc["category"],
                passed=all(checks.values()),
                checks=checks,
                expected_tools=sc["expected_tool_calls"],
                actual_tools=res.tool_calls,
                segundos=res.segundos,
                total_tokens=res.total_tokens,
                detalles={
                    "clasificacion": res.clasificacion.model_dump(),
                    "especialista": res.especialista,
                    "qa": res.qa.model_dump(),
                    "intentos_qa": res.intentos_qa,
                    "escalado_humano": res.escalado_humano,
                    "motivo_escalado": res.motivo_escalado,
                },
            )
        )

    n_all = max(len(results), 1)
    n_e2e = max(end_to_end_count, 1)
    passed = sum(1 for r in results if r.passed)
    pass_rate = round(passed / n_all, 4)

    all_values = {
        "pass_rate": pass_rate,
        "escalation_accuracy": round(esc_hits / n_e2e, 4),
        "mean_qa_politica": round(sum(qa_pol) / max(len(qa_pol), 1), 2),
        "first_pass_qa_approval_rate": round(first_pass_qa / n_e2e, 4),
        "category_accuracy": round(cat_hits / n_e2e, 4),
        "tool_trajectory_recall": round(sum(tool_recalls) / max(len(tool_recalls), 1), 4),
        "mean_qa_score": round(
            (
                sum(qa_prec) + sum(qa_pol) + sum(qa_tono) + sum(qa_comp)
            ) / max(4 * len(qa_prec), 1),
            2,
        ),
        "avg_latency_seconds": round(sum(r.segundos for r in results) / n_all, 2),
        "avg_tokens": round(sum(r.total_tokens for r in results) / n_all, 1),
    }
    gate_ok, targets = _evaluate_targets(PIPELINE_QUALITY_TARGETS, all_values)

    return EvalSummaryReport(
        target="pipeline",
        versiones=sys_instance.versiones,
        total_scenarios=len(results),
        passed_scenarios=passed,
        pass_rate=pass_rate,
        quality_gate_passed=gate_ok,
        quality_targets=targets,
        diagnostics={
            "category_accuracy": all_values["category_accuracy"],
            "tool_trajectory_recall": all_values["tool_trajectory_recall"],
            "mean_qa_score": all_values["mean_qa_score"],
            "avg_latency_seconds": all_values["avg_latency_seconds"],
            "avg_tokens": all_values["avg_tokens"],
        },
        results=results,
    )
