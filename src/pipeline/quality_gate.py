"""Quality Gate del pipeline: métricas agregadas, umbrales absolutos y regresión frente a un baseline."""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from src import config
from src.pipeline.evaluator import PIPELINE_QUALITY_TARGETS, QualityTargetEvaluation, _evaluate_targets

BASELINE_PATH = config.ROOT / "data" / "baseline_pipeline.json"

# Métricas "más es mejor" comparadas contra el baseline: (tolerancia absoluta permitida)
# Con 23 escenarios, 1 escenario ~ 0.043: la tolerancia de 0.05 absorbe un fallo aislado por variabilidad del LLM.
REGRESSION_TOLERANCES: dict[str, float] = {
    "pass_rate": 0.05,
    "escalation_accuracy": 0.05,
    "first_pass_qa_approval_rate": 0.05,
    "mean_qa_politica": 0.25,
}
# Métricas "menos es mejor": solo se reportan (no bloquean el gate).
COST_METRICS = ("avg_tokens", "avg_latency_seconds")


class MetricComparison(BaseModel):
    metric: str
    value: float
    baseline: float
    delta: float
    tolerance: float
    regressed: bool


class CostComparison(BaseModel):
    metric: str
    value: float
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
    metrics: dict[str, float] = Field(default_factory=dict)
    targets: list[QualityTargetEvaluation] = Field(default_factory=list)
    comparisons: list[MetricComparison] = Field(default_factory=list)
    costs: list[CostComparison] = Field(default_factory=list)
    failed_scenarios: dict[str, list[str]] = Field(default_factory=dict)


def compute_pipeline_metrics(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Agrega filas `{stage, scores, outputs}` en las métricas del gate (misma definición que `evaluate_pipeline`).

    - `scores`: resultado de los 5 evaluators de código (`{key: 1|0|None}`).
    - `outputs`: salida del target (vacía si el escenario falló por excepción).
    """
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
    tokens = sum((r.get("outputs") or {}).get("total_tokens", 0) for r in rows)
    seconds = sum((r.get("outputs") or {}).get("segundos", 0.0) for r in rows)

    return {
        "pass_rate": round(passed / n_all, 4),
        "escalation_accuracy": round(esc_hits / n_e2e, 4),
        "mean_qa_politica": round(sum(politica) / max(len(politica), 1), 2),
        "first_pass_qa_approval_rate": round(first_pass / n_e2e, 4),
        "avg_tokens": round(tokens / n_all, 1),
        "avg_latency_seconds": round(seconds / n_all, 2),
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
        "schema": 1,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "versions": report.versions,
        "experiment": report.experiment_name,
        "total_examples": report.total_examples,
        "metrics": report.metrics,
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def evaluate_gate(
    metrics: dict[str, float],
    *,
    baseline: dict[str, Any] | None = None,
    tolerances: dict[str, float] | None = None,
    versions: dict[str, str] | None = None,
    experiment_name: str = "",
    experiment_url: str = "",
    total_examples: int = 0,
    failed_scenarios: dict[str, list[str]] | None = None,
) -> GateReport:
    """Aplica umbrales absolutos (`PIPELINE_QUALITY_TARGETS`) + regresión frente al baseline."""
    targets_ok, targets = _evaluate_targets(PIPELINE_QUALITY_TARGETS, metrics)
    tol = {**REGRESSION_TOLERANCES, **(tolerances or {})}
    base_metrics = (baseline or {}).get("metrics") or {}

    comparisons: list[MetricComparison] = []
    for key, tolerance in tol.items():
        if key not in base_metrics or key not in metrics:
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
        pct = round((metrics[key] - base) / base * 100, 1) if base else None
        costs.append(CostComparison(metric=key, value=metrics[key], baseline=base, delta_pct=pct))

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
    )


def _fmt(metric: str, val: float) -> str:
    if metric == "mean_qa_politica":
        return f"{val:.2f} / 5"
    if metric == "avg_tokens":
        return f"{val:,.0f}"
    if metric == "avg_latency_seconds":
        return f"{val:.2f} s"
    return f"{val * 100:.1f}%"


def render_markdown(report: GateReport) -> str:
    """Informe en Markdown para el comentario de la PR y el resumen del job."""
    icon = "✅" if report.passed else "❌"
    lines = [
        "<!-- eval-gate-report -->",
        f"## {icon} Eval Quality Gate — {'PASSED' if report.passed else 'FAILED'}",
        "",
    ]
    if report.experiment_name:
        link = f"[{report.experiment_name}]({report.experiment_url})" if report.experiment_url else report.experiment_name
        lines.append(f"**Experimento LangSmith:** {link} ({report.total_examples} escenarios)")
    if report.versions:
        lines.append("**Versiones evaluadas:** " + ", ".join(f"`{k}:{v}`" for k, v in report.versions.items()))
    lines += ["", "### Umbrales absolutos", "", "| Prioridad | Métrica | Resultado | Target | Estado |", "|---|---|---:|---:|:---:|"]
    for t in report.targets:
        lines.append(
            f"| {t.priority} | `{t.metric}` | {_fmt(t.metric, t.value)} | ≥ {_fmt(t.metric, t.target)} | {'✅' if t.passed else '❌'} |"
        )

    lines += ["", "### Regresión vs baseline", ""]
    if report.comparisons:
        lines += ["| Métrica | Resultado | Baseline | Δ | Tolerancia | Estado |", "|---|---:|---:|---:|---:|:---:|"]
        for c in report.comparisons:
            sign = "+" if c.delta > 0 else ""
            lines.append(
                f"| `{c.metric}` | {_fmt(c.metric, c.value)} | {_fmt(c.metric, c.baseline)} | "
                f"{sign}{c.delta:.4g} | ±{c.tolerance:g} | {'❌ regresión' if c.regressed else '✅'} |"
            )
    else:
        lines.append("_No se encontró baseline: solo se aplican los umbrales absolutos._")

    lines += ["", "### Coste y latencia (informativo, no bloquea)", "", "| Métrica | Resultado | Baseline | Δ % |", "|---|---:|---:|---:|"]
    for c in report.costs:
        base = _fmt(c.metric, c.baseline) if c.baseline is not None else "-"
        delta = f"{'+' if c.delta_pct > 0 else ''}{c.delta_pct}%" if c.delta_pct is not None else "-"
        lines.append(f"| `{c.metric}` | {_fmt(c.metric, c.value)} | {base} | {delta} |")

    if report.failed_scenarios:
        lines += ["", "### Escenarios con fallos", ""]
        lines += [f"- `{sid}`: {', '.join(bad)}" for sid, bad in report.failed_scenarios.items()]
    return "\n".join(lines) + "\n"
