
"""CLI: procesa tickets de muestra, un mensaje personalizado o ejecuta la suite de evaluación (`--eval`)."""
import argparse
import json
import sys
from datetime import datetime

from rich.console import Console
from rich.table import Table

from src import config
from src.agents import active_version
from src.data import init_db
from src.data.sample_tickets import TICKETS
from src.pipeline.evaluator import evaluate_pipeline, evaluate_triage_version, load_eval_dataset
from src.pipeline.langsmith_eval import run_langsmith_experiment, sync_dataset_to_langsmith
from src.pipeline.quality_gate import evaluate_gate, load_baseline, render_markdown, save_baseline
from src.pipeline.orchestrator import construir_sistema, procesar_ticket, ticket_personalizado


def _parse_versions(ver_str: str | None) -> dict[str, str] | None:
    if not ver_str:
        return None
    out: dict[str, str] = {}
    for item in ver_str.split(","):
        if ":" in item:
            k, v = item.split(":", 1)
            out[k.strip()] = v.strip()
    return out or None


def _format_target_val(metric: str, val: float) -> str:
    if "score" in metric or "politica" in metric:
        return f"{val:.2f} / 5.00"
    return f"{val * 100:.1f}%"


def _run_eval_cli(args, console: Console):
    scenarios = load_eval_dataset(category=args.category, limit=args.limit)
    versions = _parse_versions(args.versions)

    if args.agent == "triaje":
        ver = (versions or {}).get("triaje", args.version or active_version("triaje"))
        console.rule(f"[bold cyan]Evaluando Agente Aislado: triaje ({ver}) — {len(scenarios)} escenarios")
        report = evaluate_triage_version(scenarios, version=ver)
    else:
        if args.version and not versions:
            versions = {k: args.version for k in ("triaje", "devoluciones", "soporte_tecnico", "consultas", "qa")}
        console.rule(f"[bold cyan]Evaluando Pipeline Completo — {len(scenarios)} escenarios")
        report = evaluate_pipeline(scenarios, versions=versions)

    sc_table = Table(title=f"Resultados por Escenario ({report.target})")
    for col in ("ID", "Categoría", "Estado", "Checks fallidos", "Tools ejecutadas", "Tokens", "s"):
        sc_table.add_column(col)
    for r in report.results:
        failed = [k for k, ok in r.checks.items() if not ok]
        tools_str = ", ".join(f"{tc.agent}.{tc.tool}" for tc in r.actual_tools) or "none"
        sc_table.add_row(
            r.scenario_id,
            r.category,
            "[green]PASS[/]" if r.passed else "[bold red]FAIL[/]",
            ", ".join(failed) or "-",
            tools_str,
            str(r.total_tokens),
            str(r.segundos),
        )
    console.print(sc_table)

    verdict_badge = "[bold green]APPROVED[/]" if report.quality_gate_passed else "[bold red]NEEDS IMPROVEMENT[/]"
    t_table = Table(
        title=f"Core Quality Targets — {report.target} (versiones: {report.versiones}) -> {verdict_badge}"
    )
    for col in ("Prioridad de Decisión", "Métrica", "Resultado", "Target", "Estado", "Qué evalúa"):
        t_table.add_column(col)
    for qt in report.quality_targets:
        t_table.add_row(
            qt.priority,
            f"[bold]{qt.metric}[/]",
            _format_target_val(qt.metric, qt.value),
            f">= {_format_target_val(qt.metric, qt.target)}",
            "[green]PASS[/]" if qt.passed else "[bold red]FAIL[/]",
            qt.description,
        )
    console.print(t_table)

    diag_str = " | ".join(f"{k}: {v}" for k, v in report.diagnostics.items())
    console.print(f"[dim]Diagnósticos secundarios ({report.passed_scenarios}/{report.total_scenarios} escenarios): {diag_str}[/]")

    config.OUTPUT_DIR.mkdir(exist_ok=True)
    out = config.OUTPUT_DIR / f"eval_{report.target.replace(':', '_')}_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps(report.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    console.print(f"Reporte de evaluación guardado en {out}")


def _run_langsmith_cli(args, console: Console) -> int:
    """Experimento LangSmith + Quality Gate. Devuelve el exit code (0 ok, 1 gate fallido)."""
    versions = _parse_versions(args.versions)
    if args.version and not versions:
        versions = {k: args.version for k in ("triaje", "devoluciones", "soporte_tecnico", "consultas", "qa")}
    console.rule("[bold cyan]Experimento LangSmith — Pipeline Completo (evaluators de código)")
    summary = run_langsmith_experiment(
        args.dataset_name,
        versions=versions,
        category=args.category,
        limit=args.limit,
        max_concurrency=args.max_concurrency,
        experiment_prefix=args.experiment_prefix,
    )

    table = Table(title=f"Experimento {summary.experiment_name} (dataset: {summary.dataset_name})")
    table.add_column("Evaluator")
    table.add_column("Media")
    for k, v in summary.metric_means.items():
        table.add_row(k, f"{v * 100:.1f}%")
    console.print(table)
    if summary.experiment_url:
        console.print(f"Experimento: {summary.experiment_url}")

    baseline = load_baseline(Path(args.baseline) if args.baseline else None)
    report = evaluate_gate(
        summary.metrics,
        baseline=baseline,
        versions=summary.versions,
        experiment_name=summary.experiment_name,
        experiment_url=summary.experiment_url,
        total_examples=summary.total_examples,
        failed_scenarios=summary.failed_scenarios,
    )
    markdown = render_markdown(report)
    console.print(markdown, markup=False, highlight=False)

    if args.report_md:
        Path(args.report_md).write_text(markdown, encoding="utf-8")
    if args.report_json:
        Path(args.report_json).write_text(
            json.dumps(report.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    if args.update_baseline:
        if not report.targets_passed:
            console.print("[bold red]No se actualiza el baseline: el run no supera los umbrales absolutos.[/]")
            return 1
        out = save_baseline(report, Path(args.baseline) if args.baseline else None)
        console.print(f"[green]Baseline actualizado:[/] {out}")

    if args.fail_on_gate and not report.passed:
        console.print("[bold red]QUALITY GATE FAILED[/]")
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mensaje", help="Mensaje personalizado del cliente")
    ap.add_argument("--cliente", default="C900", help="ID de cliente para el mensaje personalizado")
    ap.add_argument("--pedido", default=None)
    ap.add_argument("--eval", action="store_true", help="Ejecuta la evaluación con data/eval_dataset.jsonl")
    ap.add_argument("--agent", choices=["triaje", "pipeline"], default="pipeline", help="Evaluar solo triaje o el pipeline completo")
    ap.add_argument("--version", default=None, help="Versión del agente a evaluar (p. ej. v1 o v2)")
    ap.add_argument("--versions", default=None, help="Mapa de versiones por agente, p. ej. 'triaje:v2,qa:v1'")
    ap.add_argument("--category", default=None, help="Filtrar eval_dataset por categoría (happy_path, edge_case, boundary_testing, tool_invocation)")
    ap.add_argument("--limit", type=int, default=None, help="Limitar número de escenarios de evaluación")
    ap.add_argument("--sync-dataset", action="store_true", help="Sincroniza data/eval_dataset.jsonl con LangSmith Datasets")
    ap.add_argument("--dataset-name", default=None, help="Nombre del Dataset en LangSmith (por defecto LANGSMITH_DATASET_NAME)")
    ap.add_argument("--langsmith", action="store_true", help="Con --eval: ejecuta el experimento en LangSmith (evaluators de código)")
    ap.add_argument("--max-concurrency", type=int, default=4, help="Escenarios en paralelo en el experimento LangSmith")
    ap.add_argument("--experiment-prefix", default=None, help="Prefijo del experimento LangSmith (p. ej. pr-12-ab12cd3)")
    ap.add_argument("--fail-on-gate", action="store_true", help="Con --eval --langsmith: exit code 1 si falla el Quality Gate")
    ap.add_argument("--baseline", default=None, help="Ruta del baseline JSON (por defecto data/baseline_pipeline.json)")
    ap.add_argument("--update-baseline", action="store_true", help="Guarda las métricas del run como nuevo baseline")
    ap.add_argument("--report-md", default=None, help="Escribe el informe del gate en Markdown (comentario de PR)")
    ap.add_argument("--report-json", default=None, help="Escribe el informe del gate en JSON")
    args = ap.parse_args()

    console = Console()
    init_db()

    if args.sync_dataset:
        res = sync_dataset_to_langsmith(dataset_name=args.dataset_name)
        action_str = "Creado" if res.created else "Actualizado"
        console.print(
            f"[bold green]Dataset de LangSmith {action_str}:[/] [cyan]{res.dataset_name}[/] "
            f"(id={res.dataset_id}, escenarios={res.total_examples})"
        )
        return

    if args.eval and args.langsmith:
        if (args.fail_on_gate or args.update_baseline) and (args.category or args.limit):
            ap.error("--fail-on-gate / --update-baseline requieren el dataset completo (sin --category ni --limit).")
        try:
            code = _run_langsmith_cli(args, console)
        except Exception as exc:  # error de infraestructura (credenciales, red, dataset vacío...)
            console.print(f"[bold red]Error de infraestructura:[/] {exc}")
            sys.exit(2)
        sys.exit(code)

    if args.eval:
        _run_eval_cli(args, console)
        return

    versions = _parse_versions(args.versions) or (
        {k: args.version for k in ("triaje", "devoluciones", "soporte_tecnico", "consultas", "qa")}
        if args.version
        else None
    )
    sistema = construir_sistema(versions=versions)
    tickets = [ticket_personalizado(args.mensaje, args.cliente, args.pedido)] if args.mensaje else TICKETS

    resultados = []
    for t in tickets:
        console.rule(f"[bold]{t['id']} - {t['asunto']}")
        try:
            r = procesar_ticket(t, sistema)
        except Exception as e:
            console.print(f"[red]Error: {e}")
            continue
        resultados.append(r)
        esc_tag = f" | [bold red]ESCALADO ({r.motivo_escalado})[/]" if r.escalado_humano else ""
        tools_used = ", ".join(f"{tc.tool}" for tc in r.tool_calls) or "none"
        console.print(
            f"[cyan]{r.clasificacion.categoria}[/] | prioridad {r.clasificacion.prioridad} | "
            f"{r.clasificacion.segmento_cliente} -> {r.especialista} | "
            f"Tools: [{tools_used}] | QA: {r.qa.veredicto} (intentos: {r.intentos_qa}) | "
            f"Tokens: {r.total_tokens}{esc_tag}"
        )
        console.print(r.respuesta_final)

    table = Table(title="Resumen")
    for col in ("Ticket", "Categoría", "Prioridad", "Segmento", "Especialista", "Tools", "P/Pol/T/C", "QA (int.)", "Escalado", "Tokens", "s"):
        table.add_column(col)
    for r in resultados:
        q = r.qa
        table.add_row(
            r.ticket_id,
            r.clasificacion.categoria,
            r.clasificacion.prioridad,
            r.clasificacion.segmento_cliente,
            r.especialista,
            str(len(r.tool_calls)),
            f"{q.precision}/{q.politica}/{q.tono}/{q.completitud}",
            f"{q.veredicto} ({r.intentos_qa})",
            "SÍ" if r.escalado_humano else "NO",
            str(r.total_tokens),
            str(r.segundos),
        )
    console.print(table)

    config.OUTPUT_DIR.mkdir(exist_ok=True)
    out = config.OUTPUT_DIR / f"resultados_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps([r.model_dump() for r in resultados], ensure_ascii=False, indent=2), encoding="utf-8")
    console.print(f"Guardado en {out}")


if __name__ == "__main__":
    main()
