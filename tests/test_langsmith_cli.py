"""Offline coverage for the LangSmith-only CLI and CI report contract."""
from contextlib import nullcontext
from io import BytesIO, TextIOWrapper
from types import SimpleNamespace
import sys

import pytest
from rich.console import Console

import main
from src.agents import get_active_versions
from src.pipeline import langsmith_eval
from src.pipeline.eval_dataset import load_eval_dataset
from src.pipeline.eval_provenance import evaluation_provenance, validate_full_report


def test_cli_eval_and_legacy_alias_use_langsmith(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "_run_langsmith_cli", lambda args, console, versions: calls.append(versions) or 0)
    for alias in ([], ["--langsmith"]):
        monkeypatch.setattr(sys, "argv", ["main.py", "--eval", *alias, "--versions", "triaje:v4"])
        with pytest.raises(SystemExit) as exc:
            main.main()
        assert exc.value.code == 0
    assert calls == [{"triaje": "v4"}, {"triaje": "v4"}]


@pytest.mark.parametrize("flags", [
    ["--eval", "--agent", "triaje"], ["--eval", "--limit", "0"], ["--eval", "--category", "invalid"],
    ["--eval", "--versions", "triaje=v4"], ["--eval", "--versions", "unknown:v4"],
    ["--eval", "--versions", "triaje:v99"], ["--eval", "--versions", "triaje:v3,triaje:v4"],
    ["--eval", "--limit", "1", "--fail-on-gate"], ["--langsmith"], ["--update-baseline"],
    ["--eval", "--limit", "1", "--report-json", "data/latest_eval_report.json"],
])
def test_invalid_cli_options_fail_before_inference(monkeypatch, flags):
    monkeypatch.setattr(sys, "argv", ["main.py", *flags])
    monkeypatch.setattr(main, "_run_langsmith_cli", lambda *args: pytest.fail("Unexpected LangSmith invocation"))
    with pytest.raises(SystemExit) as exc:
        main.main()
    assert exc.value.code == 2


def test_legacy_baseline_requires_an_explicit_fresh_path(monkeypatch):
    monkeypatch.setattr(main, "load_baseline", lambda path: {"schema": 1})
    monkeypatch.setattr(main, "run_langsmith_experiment", lambda *args, **kwargs: pytest.fail("Unexpected inference"))
    args = SimpleNamespace(category=None, limit=None, baseline=None, report_md=None, report_json=None)
    with pytest.raises(ValueError, match="Baseline incompatible"):
        main._run_langsmith_cli(args, None, {})


def test_full_report_is_saved_with_non_utf8_console(tmp_path, monkeypatch):
    metrics = {
        "pass_rate": 1.0, "escalation_accuracy": 1.0,
        "mean_qa_politica": 5.0, "first_pass_qa_approval_rate": 1.0,
    }
    monkeypatch.setattr(main, "run_langsmith_experiment", lambda *args, **kwargs: SimpleNamespace(
        experiment_name="test", experiment_url="", dataset_name="golden", versions={},
        total_examples=23, metrics=metrics, metric_means={}, failed_scenarios={},
        scenario_feedback={}, scenario_ids=[], partial=False, provenance={},
    ))
    args = SimpleNamespace(
        category=None, limit=None, baseline=str(tmp_path / "fresh.json"), dataset_name=None,
        max_concurrency=None, experiment_prefix=None, fail_on_gate=True, update_baseline=False,
        report_md=str(tmp_path / "report.md"), report_json=str(tmp_path / "report.json"),
    )
    with TextIOWrapper(BytesIO(), encoding="cp1252") as terminal:
        assert main._run_langsmith_cli(args, Console(file=terminal), {}) == 0
    assert "\u2705" in (tmp_path / "report.md").read_text(encoding="utf-8")
    assert (tmp_path / "report.json").exists()


def test_full_reports_must_match_current_benchmark(tmp_path):
    versions = get_active_versions()
    ids = sorted(row["id"] for row in load_eval_dataset())
    report = {
        "versions": versions, "partial": False, "scenario_ids": ids, "total_examples": len(ids),
        "provenance": evaluation_provenance(versions), "passed": True,
    }
    validate_full_report(report)
    for invalid in (
        {**report, "partial": True},
        {**report, "scenario_ids": ids[:-1]},
        {**report, "provenance": {**report["provenance"], "source_fingerprint": "stale"}},
        {**report, "provenance": {**report["provenance"], "benchmark_fingerprint": "stale"}},
        {**report, "passed": False},
    ):
        with pytest.raises(ValueError):
            validate_full_report(invalid)


def test_full_experiment_uses_langsmith_scores_and_validates_dataset(monkeypatch):
    name = "golden"
    dataset = load_eval_dataset()
    examples = [SimpleNamespace(**langsmith_eval.scenario_to_langsmith_example(row, name)) for row in dataset]
    client = SimpleNamespace(
        list_examples=lambda **kwargs: iter(examples),
        read_project=lambda **kwargs: SimpleNamespace(url="https://example.test/project"),
    )
    monkeypatch.setattr(langsmith_eval, "evaluation_repository", nullcontext)
    monkeypatch.setattr(langsmith_eval, "make_pipeline_target", lambda **kwargs: None)

    def evaluate(target, *, data, evaluators, summary_evaluators, **kwargs):
        assert len(data) == 23
        assert summary_evaluators == [langsmith_eval.summarize_pipeline]
        rows = []
        for example in data:
            feedback = [SimpleNamespace(key=check.__name__, score=1, comment="") for check in evaluators]
            if example.inputs["id"] == "EVAL-004":
                feedback[-1].score = 0
                feedback[-1].comment = "Failed: tool_result.consultar_pedido.1"
            rows.append({
                "run": SimpleNamespace(outputs={"segundos": 1.5}),
                "example": example,
                "evaluation_results": {"results": feedback},
            })

        class Results(list):
            experiment_name = "fake-experiment"

        return Results(rows)

    monkeypatch.setattr("langsmith.evaluate", evaluate)
    summary = langsmith_eval.run_langsmith_experiment(name, client=client)
    assert summary.total_examples == 23 and len(summary.scenario_ids) == 23 and not summary.partial
    assert summary.metrics["pass_rate"] == round(22 / 23, 4)
    assert summary.failed_scenarios == {"EVAL-004": ["scenario_assertions"]}
    assert "consultar_pedido.1" in summary.scenario_feedback["EVAL-004"]["scenario_assertions"]
    assert "manual_review" in summary.scenario_feedback["EVAL-004"]
    assert summary.metrics["avg_ttft_seconds"] is None

    examples[0].outputs = {**examples[0].outputs, "assertions": {}}
    monkeypatch.setattr("langsmith.evaluate", lambda *args, **kwargs: pytest.fail("Unexpected inference"))
    with pytest.raises(ValueError, match="desactualizado"):
        langsmith_eval.run_langsmith_experiment(name, client=client)


def test_out_of_scope_scenario_needs_no_second_customer_lookup():
    from src.pipeline.orchestrator import ToolCallTrace
    from src.pipeline.scenario_checks import check_scenario, check_tools

    scenario = next(row for row in load_eval_dataset() if row["id"] == "EVAL-015")
    calls = [ToolCallTrace(agent="triaje", tool="consultar_cliente", args={"cliente_id": "C904"})]
    assert check_tools(scenario["expected_tool_calls"], calls) == (True, 1.0)
    assert check_scenario(scenario["assertions"], calls=calls)["forbidden_tools"]
    calls.append(ToolCallTrace(agent="consultas", tool="consultar_pedido"))
    assert not check_scenario(scenario["assertions"], calls=calls)["forbidden_tools"]
