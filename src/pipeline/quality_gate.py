"""Quality Gate del pipeline: métricas agregadas, umbrales absolutos y regresión frente a un baseline."""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from src import config

BASELINE_PATH = config.ROOT / "data" / "baseline_pipeline.json"

# Metrics "más es mejor" comparadas contra el baseline: (tolerancia absoluta permitida)
# Con 23 escenarios, 1 escenario ~ 0.043: la tolerancia de 0.05 absorbe un fallo aislado por variabilidad del LLM.
REGRESSION_TOLERANCES: dict[str, float] = {
    "pass_rate": 0.05,
    "escalation_accuracy": 0.05,
    "first_pass_qa_approval_rate": 0.05,
    "mean_qa_politica": 0.25,
}
# Metrics "menos es mejor": solo se reportan (no bloquean el gate).
COST_METRICS = ("avg_tokens", "avg_cost_usd", "avg_latency_seconds", "avg_ttft_seconds")


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


class MetricComparison(BaseModel):
    metric: str
    value: float
    baseline: float
    delta: float
    tolerance: float
    regressed: bool


class CostComparison(BaseModel):
    metric: str
    value: float | None
    baseline: float | None = None
    delta_pct: float | None = None


class GateReport(BaseModel):
    passed: bool
    targets_passed: bool
    regression_passed: bool
    baseline_found: bool
    experiment_name: str = ""
    experiment_url: str = ""
    versions: dict[str, str] = Field(default_factory=dict)
    total_examples: int = 0
    metrics: dict[str, float | None] = Field(default_factory=dict)
    targets: list[QualityTargetEvaluation] = Field(default_factory=list)
    comparisons: list[MetricComparison] = Field(default_factory=list)
    costs: list[CostComparison] = Field(default_factory=list)
    failed_scenarios: dict[str, list[str]] = Field(default_factory=dict)
    scenario_feedback: dict[str, dict[str, str]] = Field(default_factory=dict)
    scenario_ids: list[str] = Field(default_factory=list)
    partial: bool = False
    provenance: dict[str, Any] = Field(default_factory=dict)


def compute_pipeline_metrics(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    """Aggregate LangSmith scores and measurements for the quality gate."""
    n_all = max(len(rows), 1)
    e2e = [r for r in rows if r.get("stage") != "qa"]
    n_e2e = max(len(e2e), 1)

    def _scored(r: dict[str, Any]) -> dict[str, int]:
        return {k: int(v) for k, v in r["scores"].items() if v is not None}

    passed = sum(1 for r in rows if _scored(r) and all(_scored(r).values()))
    esc_hits = sum(1 for r in e2e if r["scores"].get("escalado_match") == 1)
    politica = [r["outputs"]["qa"]["politica"] for r in e2e if (r.get("outputs") or {}).get("qa")]
    first_pass = sum(
        1
        for r in e2e
        if (r.get("outputs") or {}).get("intentos_qa") == 1
        and ((r["outputs"].get("qa") or {}).get("veredicto") in ("aprobado", "reescrito"))
    )
    token_usage_complete = all((row.get("outputs") or {}).get("token_usage_complete", True) for row in rows)

    def average_observed(key: str, digits: int) -> float | None:
        values = [(row.get("outputs") or {}).get(key) for row in rows]
        if not values or None in values:
            return None
        return round(sum(values) / len(values), digits)


    return {
        "pass_rate": round(passed / n_all, 4),
        "escalation_accuracy": round(esc_hits / n_e2e, 4),
        "mean_qa_politica": round(sum(politica) / max(len(politica), 1), 2),
        "first_pass_qa_approval_rate": round(first_pass / n_e2e, 4),
        "avg_tokens": average_observed("total_tokens", 1) if token_usage_complete else None,
        "avg_cost_usd": average_observed("cost_usd", 6),
        "avg_latency_seconds": average_observed("segundos", 2),
        "avg_ttft_seconds": average_observed("ttft_seconds", 2),
    }


def load_baseline(path: Path | None = None) -> dict[str, Any] | None:
    p = path or BASELINE_PATH
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def save_baseline(report: GateReport, path: Path | None = None) -> Path:
    p = path or BASELINE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": 2 if report.provenance else 1,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "versions": report.versions,
        "experiment": report.experiment_name,
        "total_examples": report.total_examples,
        "metrics": report.metrics,
        **({"benchmark_fingerprint": report.provenance["benchmark_fingerprint"]} if report.provenance else {}),
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def evaluate_gate(
    metrics: dict[str, float | None],
    *,
    baseline: dict[str, Any] | None = None,
    tolerances: dict[str, float] | None = None,
    versions: dict[str, str] | None = None,
    experiment_name: str = "",
    experiment_url: str = "",
    total_examples: int = 0,
    failed_scenarios: dict[str, list[str]] | None = None,
    scenario_feedback: dict[str, dict[str, str]] | None = None,
    scenario_ids: list[str] | None = None,
    partial: bool = False,
    provenance: dict[str, Any] | None = None,
) -> GateReport:
    """Aplica umbrales absolutos (`PIPELINE_QUALITY_TARGETS`) + regresión frente al baseline."""
    definitions = PIPELINE_QUALITY_TARGETS
    if (provenance or {}).get("evaluation_stage") == "qa":
        definitions = [target for target in definitions if target[1] == "pass_rate"]
    targets_ok, targets = _evaluate_targets(definitions, {key: value for key, value in metrics.items() if value is not None})
    tol = {**REGRESSION_TOLERANCES, **(tolerances or {})}
    base_metrics = (baseline or {}).get("metrics") or {}

    comparisons: list[MetricComparison] = []
    for key, tolerance in tol.items():
        if base_metrics.get(key) is None or metrics.get(key) is None:
            continue
        delta = round(metrics[key] - base_metrics[key], 4)
        comparisons.append(
            MetricComparison(
                metric=key,
                value=metrics[key],
                baseline=base_metrics[key],
                delta=delta,
                tolerance=tolerance,
                regressed=delta < -tolerance - 1e-9,
            )
        )

    costs: list[CostComparison] = []
    for key in COST_METRICS:
        base = base_metrics.get(key)
        value = metrics.get(key)
        pct = round((value - base) / base * 100, 1) if base and value is not None else None
        costs.append(CostComparison(metric=key, value=value, baseline=base, delta_pct=pct))

    regression_ok = not any(c.regressed for c in comparisons)
    return GateReport(
        passed=targets_ok and regression_ok,
        targets_passed=targets_ok,
        regression_passed=regression_ok,
        baseline_found=bool(base_metrics),
        experiment_name=experiment_name,
        experiment_url=experiment_url,
        versions=versions or {},
        total_examples=total_examples,
        metrics=metrics,
        targets=targets,
        comparisons=comparisons,
        costs=costs,
        failed_scenarios=failed_scenarios or {},
        scenario_feedback=scenario_feedback or {},
        scenario_ids=scenario_ids or [],
        partial=partial,
        provenance=provenance or {},
    )


def _fmt(metric: str, val: float | None) -> str:
    if val is None:
        return "-"
    if metric == "mean_qa_politica":
        return f"{val:.2f} / 5"
    if metric == "avg_tokens":
        return f"{val:,.0f}"
    if metric == "avg_cost_usd":
        return f"${val:.4f}"
    if metric in ("avg_latency_seconds", "avg_ttft_seconds"):
        return f"{val:.2f} s"
    return f"{val * 100:.1f}%"


def render_markdown(report: GateReport, *, active_baseline: dict[str, Any] | None = None) -> str:
    """Informe en Markdown para el comentario de la PR y el resumen del job."""
    icon = "✅" if report.passed else "❌"
    lines = [
        "<!-- eval-gate-report -->",
        f"## {icon} Eval Quality Gate — {'PASSED' if report.passed else 'FAILED'}",
        "",
    ]
    if report.experiment_name:
        link = f"[{report.experiment_name}]({report.experiment_url})" if report.experiment_url else report.experiment_name
        lines.append(f"**LangSmith experiment:** {link} ({report.total_examples} scenarios)")
    if report.versions:
        lines.append("**Evaluated versions:** " + ", ".join(f"`{k}:{v}`" for k, v in report.versions.items()))
    if active_baseline and report.passed and not report.partial and report.experiment_name and (
        active_baseline.get("experiment") == report.experiment_name
        and active_baseline.get("versions") == report.versions
        and active_baseline.get("metrics") == report.metrics
        and active_baseline.get("benchmark_fingerprint") == report.provenance.get("benchmark_fingerprint")
    ):
        lines.append("**Promotion status:** This experiment is the active baseline.")
    if dataset_name := report.provenance.get("dataset_name"):
        lines.append(f"**Dataset:** `{dataset_name}` ({report.provenance['dataset_split']})")
    if report.provenance.get("evaluation_stage") == "qa":
        lines.append("**Evaluation stage:** QA only")
    lines += ["", "### Absolute thresholds", "", "| Priority | Metric | Result | Target | Status |", "|---|---|---:|---:|:---:|"]
    for t in report.targets:
        lines.append(
            f"| {t.priority} | `{t.metric}` | {_fmt(t.metric, t.value)} | ≥ {_fmt(t.metric, t.target)} | {'✅' if t.passed else '❌'} |"
        )

    lines += ["", "### Baseline comparison at run time", ""]
    if report.partial:
        lines.append("_Partial diagnostic run._")
    elif report.comparisons:
        lines += ["| Metric | Result | Baseline | Δ | Tolerance | Status |", "|---|---:|---:|---:|---:|:---:|"]
        for c in report.comparisons:
            sign = "+" if c.delta > 0 else ""
            lines.append(
                f"| `{c.metric}` | {_fmt(c.metric, c.value)} | {_fmt(c.metric, c.baseline)} | "
                f"{sign}{c.delta:.4g} | ±{c.tolerance:g} | {'❌ regression' if c.regressed else '✅'} |"
            )
    else:
        lines.append("_This run used the absolute thresholds. No compatible prior baseline was loaded for comparison._")

    lines += ["", "### Cost and latency (informational)", "", "| Metric | Result | Baseline | Δ % |", "|---|---:|---:|---:|"]
    for c in report.costs:
        base = _fmt(c.metric, c.baseline) if c.baseline is not None else "-"
        delta = f"{'+' if c.delta_pct > 0 else ''}{c.delta_pct}%" if c.delta_pct is not None else "-"
        lines.append(f"| `{c.metric}` | {_fmt(c.metric, c.value)} | {base} | {delta} |")

    if report.failed_scenarios:
        lines += ["", "### Failed scenarios", ""]
        for sid, checks in report.failed_scenarios.items():
            lines.append(f"- `{sid}`: {', '.join(checks)}")
            for check in checks:
                if comment := report.scenario_feedback.get(sid, {}).get(check):
                    lines.append(f"  - `{check}` {comment}")

    manual = {sid: feedback["manual_review"] for sid, feedback in report.scenario_feedback.items() if "manual_review" in feedback}
    if manual:
        lines += ["", "### Manual review criteria (outside automated scoring)", ""]
        lines.extend(f"- `{sid}`: {criteria}" for sid, criteria in manual.items())

    return "\n".join(lines) + "\n"
