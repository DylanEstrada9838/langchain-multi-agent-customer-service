"""Tests del Quality Gate, summary evaluators y versiones activas."""
from types import SimpleNamespace

from src.agents import AGENT_BINDINGS, get_active_versions, list_versions
from src.pipeline.langsmith_eval import summarize_pipeline
from src.pipeline.quality_gate import (
    compute_pipeline_metrics,
    evaluate_gate,
    load_baseline,
    render_markdown,
    save_baseline,
)

GOOD = {
    "pass_rate": 0.9565,
    "escalation_accuracy": 0.9545,
    "mean_qa_politica": 5.0,
    "first_pass_qa_approval_rate": 1.0,
    "avg_tokens": 8584.7,
    "avg_cost_usd": 0.0028,
    "avg_latency_seconds": 10.54,
    "avg_ttft_seconds": 10.54,
}
BASELINE = {"metrics": GOOD}


def _row(sid, stage="pipeline", *, ok=True, esc=1, politica=5, intentos=1, veredicto="aprobado", tokens=100, cost=0.001, seg=2.0, ttft=2.0):
    scores = {
        "categoria_match": int(ok) if stage != "qa" else None,
        "especialista_match": int(ok) if stage != "qa" else None,
        "escalado_match": esc if stage != "qa" else None,
        "tool_trajectory_match": int(ok),
        "qa_quality_gate": int(ok),
    }
    outputs = {
        "stage": stage,
        "total_tokens": tokens,
        "cost_usd": cost,
        "segundos": seg,
        "ttft_seconds": ttft,
        "qa": {"politica": politica, "veredicto": veredicto},
    }
    if stage != "qa":
        outputs["intentos_qa"] = intentos
    return {"scenario_id": sid, "stage": stage, "scores": scores, "outputs": outputs}


def test_active_versions_cubren_todos_los_agentes_y_existen():
    active = get_active_versions()
    assert set(active) == set(AGENT_BINDINGS)
    for name, ver in active.items():
        assert ver in list_versions(name)


def test_calculate_cost():
    from src.llm import calculate_cost
    # gpt-4o-mini: 0.15/1M in, 0.60/1M out
    c = calculate_cost("gpt-4o-mini", 1000, 500)
    assert c == 0.00045


def test_compute_pipeline_metrics():
    rows = [
        _row("A", tokens=100, cost=0.001, seg=2.0, ttft=2.0),
        _row("B", ok=False, esc=0, intentos=2, veredicto="rechazado", politica=3, tokens=300, cost=0.003, seg=4.0, ttft=4.0),
        _row("QA", stage="qa", tokens=100, cost=0.001, seg=2.0, ttft=2.0),
    ]
    m = compute_pipeline_metrics(rows)
    assert m["pass_rate"] == round(2 / 3, 4)
    assert m["escalation_accuracy"] == 0.5  # solo las 2 filas end-to-end
    assert m["mean_qa_politica"] == 4.0
    assert m["first_pass_qa_approval_rate"] == 0.5
    assert m["avg_tokens"] == round(500 / 3, 1)
    assert m["avg_cost_usd"] == round(0.005 / 3, 6)
    assert m["avg_latency_seconds"] == round(8.0 / 3, 2)
    assert m["avg_ttft_seconds"] == round(8.0 / 3, 2)


def test_fila_con_excepcion_cuenta_como_fallo():
    row = {"scenario_id": "X", "stage": "pipeline", "scores": {"categoria_match": 0, "escalado_match": 0}, "outputs": {}}
    m = compute_pipeline_metrics([row, _row("A")])
    assert m["pass_rate"] == 0.5 and m["escalation_accuracy"] == 0.5
    assert m["avg_tokens"] is None


def test_qa_only_gate_uses_scenario_pass_rate():
    report = evaluate_gate({"pass_rate": 0.9}, provenance={"evaluation_stage": "qa"})
    assert report.passed
    assert [target.metric for target in report.targets] == ["pass_rate"]


def test_promoted_report_preserves_the_run_time_comparison():
    report = evaluate_gate(GOOD, experiment_name="promotion-run", versions={"qa": "v4"},
                           provenance={"benchmark_fingerprint": "benchmark"})
    active = {"experiment": report.experiment_name, "versions": report.versions, "metrics": report.metrics,
              "benchmark_fingerprint": "benchmark"}
    markdown = render_markdown(report, active_baseline=active)
    assert "This experiment is the active baseline" in markdown
    assert "No compatible prior baseline was loaded" in markdown
    assert "This experiment is the active baseline" not in render_markdown(report, active_baseline={**active, "experiment": "different"})
    assert "This experiment is the active baseline" not in render_markdown(report, active_baseline={**active, "benchmark_fingerprint": "different"})


def test_incomplete_provider_usage_does_not_publish_a_partial_token_average():
    row = _row("A", tokens=100, cost=None)
    row["outputs"]["token_usage_complete"] = False
    metrics = compute_pipeline_metrics([row, _row("B", tokens=200)])
    assert metrics["avg_tokens"] is None and metrics["avg_cost_usd"] is None


def test_gate_pasa_con_el_baseline():
    rep = evaluate_gate(GOOD, baseline=BASELINE)
    assert rep.passed and rep.targets_passed and rep.regression_passed and rep.baseline_found


def test_gate_falla_por_umbral_absoluto():
    rep = evaluate_gate({**GOOD, "escalation_accuracy": 0.90})
    assert not rep.passed and not rep.targets_passed
    assert not rep.baseline_found  # sin baseline solo aplican los umbrales


def test_gate_falla_por_regresion_aunque_supere_umbrales():
    # pass_rate 0.8696 >= 0.85 (umbral OK) pero cae 0.087 > tolerancia 0.05 respecto al baseline 0.9565
    rep = evaluate_gate({**GOOD, "pass_rate": 0.8696}, baseline=BASELINE)
    assert rep.targets_passed and not rep.regression_passed and not rep.passed
    assert [c.metric for c in rep.comparisons if c.regressed] == ["pass_rate"]


def test_gate_tolera_un_fallo_aislado():
    rep = evaluate_gate({**GOOD, "pass_rate": 0.913}, baseline=BASELINE)  # -1 escenario (-0.0435)
    assert rep.passed


def test_coste_y_latencia_son_informativos():
    rep = evaluate_gate({**GOOD, "avg_tokens": 20000.0, "avg_latency_seconds": 40.0}, baseline=BASELINE)
    assert rep.passed
    assert {c.metric: c.delta_pct for c in rep.costs}["avg_tokens"] > 100


def test_baseline_roundtrip_y_markdown(tmp_path):
    rep = evaluate_gate(GOOD, baseline=BASELINE, versions={"triaje": "v3"}, experiment_name="exp-1", total_examples=23)
    path = save_baseline(rep, tmp_path / "baseline.json")
    assert load_baseline(path)["metrics"] == GOOD
    assert load_baseline(tmp_path / "no_existe.json") is None
    md = render_markdown(rep)
    assert "<!-- eval-gate-report -->" in md and "PASSED" in md and "`triaje:v3`" in md


def test_summary_evaluators_devuelven_las_metricas():
    ref = {
        "expected_routing": {"categoria": "consulta", "especialista": "consultas", "escalado_humano": False},
        "expected_tool_calls": "none",
    }
    out = {
        "stage": "pipeline", "categoria": "consulta", "especialista": "consultas", "escalado_humano": False,
        "qa": {"politica": 4, "veredicto": "aprobado"}, "intentos_qa": 1, "tool_calls": [],
        "total_tokens": 50, "segundos": 1.5,
    }
    runs = [SimpleNamespace(outputs=out)]
    examples = [SimpleNamespace(inputs={"id": "E1", "context": {}}, outputs=ref)]
    got = {entry["key"]: entry["score"] for entry in summarize_pipeline(runs, examples)["results"]}
    assert "avg_cost_usd" not in got and "avg_ttft_seconds" not in got
    assert got["pass_rate"] == 1.0 and got["mean_qa_politica"] == 4.0
    assert got["first_pass_qa_approval_rate"] == 1.0 and got["avg_tokens"] == 50.0
