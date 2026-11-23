
"""CLI: procesa tickets de muestra, un mensaje personalizado o ejecuta la suite de evaluación (`--eval`)."""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from src import config
from src.agents import AGENT_BINDINGS, list_versions
from src.data import init_db
from src.data.sample_tickets import TICKETS
from src.pipeline.eval_dataset import load_eval_dataset, private_holdout_rows
from src.pipeline.eval_provenance import benchmark_fingerprint
from src.pipeline.langsmith_eval import run_langsmith_experiment, sync_dataset_to_langsmith
from src.pipeline.quality_gate import BASELINE_PATH, evaluate_gate, load_baseline, render_markdown, save_baseline
from src.pipeline.orchestrator import construir_sistema, procesar_ticket, ticket_personalizado


def _parse_versions(args) -> dict[str, str]:
    versions = {agent: args.version for agent in AGENT_BINDINGS} if args.version else {}
    if args.versions:
        for entry in args.versions.split(","):
            agent, separator, version = (part.strip() for part in entry.partition(":"))
            if not separator or not agent or not version or agent in versions:
                raise ValueError(f"Version de agente invalida o repetida: {entry!r}. Usa agente:version.")
            versions[agent] = version

    for agent, version in versions.items():
        if agent not in AGENT_BINDINGS or version not in list_versions(agent):
            raise ValueError(f"Version de agente desconocida: {agent}:{version}.")
    return versions


def _validate_cli(args) -> None:
    if args.holdout_file is not None:
        if not (args.eval or args.sync_dataset):
            raise ValueError("--holdout-file requires --eval or --sync-dataset.")
        if args.category is not None or args.limit is not None or args.baseline or args.update_baseline:
            raise ValueError("Holdout runs cannot use filters, compare against the development baseline, or update it.")
        private_holdout_rows(args.holdout_file, args.dataset_name)
    if args.langsmith and not args.eval:
        raise ValueError("--langsmith requiere --eval.")
    if not args.eval and any((
        args.category is not None, args.limit is not None, args.max_concurrency is not None,
        args.experiment_prefix, args.fail_on_gate, args.baseline, args.update_baseline,
        args.report_md, args.report_json,
    )):
        raise ValueError("Las opciones de evaluacion requieren --eval.")
    if not args.mensaje and (args.cliente is not None or args.pedido is not None):
        raise ValueError("--cliente y --pedido requieren --mensaje.")
    if args.dataset_name and not (args.eval or args.sync_dataset):
        raise ValueError("--dataset-name requiere --eval o --sync-dataset.")
    if args.sync_dataset and (args.version or args.versions):
        raise ValueError("--sync-dataset no utiliza versiones de agentes.")
    if args.limit is not None and args.limit < 1:
        raise ValueError("--limit debe ser mayor que cero.")
    if args.max_concurrency is not None and args.max_concurrency < 1:
        raise ValueError("--max-concurrency debe ser mayor que cero.")
    if args.category is not None and args.category not in {row["category"] for row in load_eval_dataset()}:
        raise ValueError(f"Categoria desconocida: {args.category}.")


def _report_paths(args, *, partial: bool) -> tuple[Path, Path]:
    canonical = config.ROOT / "data" / "latest_eval_report"
    prefix = "eval-holdout" if getattr(args, "holdout_file", None) is not None else "eval-smoke"
    basename = config.OUTPUT_DIR / f"{prefix}-{datetime.now():%Y%m%d-%H%M%S-%f}" if partial else canonical
    md = Path(args.report_md) if args.report_md else basename.with_suffix(".md")
    structured = Path(args.report_json) if args.report_json else basename.with_suffix(".json")
    if md.resolve() == structured.resolve():
        raise ValueError("Los informes Markdown y JSON requieren rutas distintas.")
    if partial:
        protected = {canonical.with_suffix(suffix).resolve() for suffix in (".md", ".json")}
        if {md.resolve(), structured.resolve()} & protected:
            raise ValueError("Filtered and holdout runs cannot overwrite the canonical development reports.")
    return md, structured


def _run_langsmith_cli(args, console: Console, versions: dict[str, str]) -> int:
    partial = args.category is not None or args.limit is not None
    holdout_path = getattr(args, "holdout_file", None)
    baseline_path = Path(args.baseline) if args.baseline else None
    report_md_path, report_json_path = _report_paths(args, partial=partial or holdout_path is not None)
    baseline = None if partial or holdout_path is not None else load_baseline(baseline_path)
    if baseline is not None and baseline.get("benchmark_fingerprint") != benchmark_fingerprint():
        raise ValueError("Baseline incompatible con este benchmark. Usa --baseline con una ruta nueva.")
    if (baseline_path or BASELINE_PATH).resolve() in {report_md_path.resolve(), report_json_path.resolve()}:
        raise ValueError("El baseline y los informes requieren rutas distintas.")
    console.rule("[bold cyan]Experimento LangSmith — Pipeline Completo (evaluators de código)")
    summary = run_langsmith_experiment(
        args.dataset_name,
        versions=versions,
        category=args.category,
        limit=args.limit,
        max_concurrency=args.max_concurrency or 4,
        experiment_prefix=args.experiment_prefix,
        holdout_path=holdout_path,
    )

    table = Table(title=f"Experimento {summary.experiment_name} (dataset: {summary.dataset_name})")
    table.add_column("Evaluator")
    table.add_column("Media")
    for k, v in summary.metric_means.items():
        table.add_row(k, f"{v * 100:.1f}%")
    console.print(table)
    if summary.experiment_url:
        console.print(f"Experimento: {summary.experiment_url}")

    report = evaluate_gate(
        summary.metrics,
        baseline=baseline,
        versions=summary.versions,
        experiment_name=summary.experiment_name,
        experiment_url=summary.experiment_url,
        total_examples=summary.total_examples,
        failed_scenarios=summary.failed_scenarios,
        scenario_feedback=summary.scenario_feedback,
        scenario_ids=summary.scenario_ids,
        partial=summary.partial,
        provenance=summary.provenance,
    )
    # Guardar informe por defecto en data/latest_eval_report.* (o ruta personalizada)
    report_json_path.parent.mkdir(parents=True, exist_ok=True)
    report_json_path.write_text(
        json.dumps(report.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    updated_baseline = save_baseline(report, baseline_path) if args.update_baseline and report.passed else None
    markdown = render_markdown(report, active_baseline=load_baseline())
    report_md_path.parent.mkdir(parents=True, exist_ok=True)
    report_md_path.write_text(markdown, encoding="utf-8")
    display = markdown.encode(console.encoding, errors="replace").decode(console.encoding)
    console.print(display, markup=False, highlight=False)

    if args.update_baseline:
        if not report.passed:
            console.print("[bold red]No se actualiza el baseline: el run no supera el Quality Gate.[/]")
            return 1
        console.print(f"[green]Baseline actualizado:[/] {updated_baseline}")

    if args.fail_on_gate and not report.passed:
        console.print("[bold red]QUALITY GATE FAILED[/]")
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--mensaje", help="Mensaje personalizado del cliente")
    mode.add_argument("--eval", action="store_true", help="Ejecuta la evaluacion en LangSmith")
    mode.add_argument("--sync-dataset", action="store_true", help="Sincroniza el dataset con LangSmith")
    ap.add_argument("--cliente", help="ID de cliente para el mensaje personalizado")
    ap.add_argument("--pedido", default=None)
    version_options = ap.add_mutually_exclusive_group()
    version_options.add_argument("--version", help="Version para todos los agentes")
    version_options.add_argument("--versions", help="Mapa de versiones por agente, p. ej. 'triaje:v4,qa:v3'")
    ap.add_argument("--category", default=None, help="Filtrar eval_dataset por categoría (happy_path, edge_case, boundary_testing, tool_invocation)")
    ap.add_argument("--limit", type=int, default=None, help="Limitar número de escenarios de evaluación")
    ap.add_argument("--dataset-name", default=None, help="Nombre del Dataset en LangSmith (por defecto LANGSMITH_DATASET_NAME)")
    ap.add_argument("--holdout-file", type=Path, help="Private holdout JSONL file. Requires a separate --dataset-name.")
    ap.add_argument("--langsmith", action="store_true", help="Con --eval: ejecuta el experimento en LangSmith (evaluators de código)")
    ap.add_argument("--max-concurrency", type=int, help="Escenarios en paralelo en el experimento LangSmith")
    ap.add_argument("--experiment-prefix", default=None, help="Prefijo del experimento LangSmith (p. ej. pr-12-ab12cd3)")
    ap.add_argument("--fail-on-gate", action="store_true", help="Con --eval --langsmith: exit code 1 si falla el Quality Gate")
    ap.add_argument("--baseline", default=None, help="Ruta del baseline JSON (por defecto data/baseline_pipeline.json)")
    ap.add_argument("--update-baseline", action="store_true", help="Guarda las métricas del run como nuevo baseline")
    ap.add_argument("--report-md", default=None, help="Escribe el informe del gate en Markdown (comentario de PR)")
    ap.add_argument("--report-json", default=None, help="Escribe el informe del gate en JSON")
    args = ap.parse_args()
    try:
        _validate_cli(args)
        versions = _parse_versions(args)
        if args.eval and (args.category is not None or args.limit is not None):
            if args.fail_on_gate or args.update_baseline or args.baseline:
                raise ValueError("Los filtros no se pueden combinar con opciones de baseline o gate.")
            _report_paths(args, partial=True)
    except (ValueError, OSError) as exc:
        ap.error(str(exc))

    console = Console()
    if args.sync_dataset:
        res = sync_dataset_to_langsmith(dataset_name=args.dataset_name, dataset_path=args.holdout_file)
        action_str = "Creado" if res.created else "Actualizado"
        console.print(
            f"[bold green]Dataset de LangSmith {action_str}:[/] [cyan]{res.dataset_name}[/] "
            f"(id={res.dataset_id}, escenarios={res.total_examples})"
        )
        return

    if args.eval:
        try:
            code = _run_langsmith_cli(args, console, versions)
        except Exception as exc:
            console.print(f"[bold red]Error de infraestructura:[/] {exc}")
            sys.exit(2)
        sys.exit(code)

    init_db()
    sistema = construir_sistema(versions=versions)
    tickets = [ticket_personalizado(args.mensaje, args.cliente or "C900", args.pedido)] if args.mensaje else TICKETS

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
        qa_status = r.qa.veredicto if r.qa is not None else "error"
        c = r.clasificacion
        routing = (
            f"[cyan]{c.categoria}[/] | prioridad {c.prioridad} | {c.segmento_cliente} -> {r.especialista} | "
            if c else ""
        )
        console.print(
            routing +
            f"Tools: [{tools_used}] | QA: {qa_status} (intentos: {r.intentos_qa}) | "
            f"Tokens: {r.total_tokens}{esc_tag}"
        )
        console.print(r.respuesta_final)

    table = Table(title="Resumen")
    for col in ("Ticket", "Categoría", "Prioridad", "Segmento", "Especialista", "Tools", "P/Pol/T/C", "QA (int.)", "Escalado", "Tokens", "s"):
        table.add_column(col)
    for r in resultados:
        q = r.qa
        c = r.clasificacion
        table.add_row(
            r.ticket_id,
            c.categoria if c else "-",
            c.prioridad if c else "-",
            c.segmento_cliente if c else "-",
            r.especialista or "-",
            str(len(r.tool_calls)),
            f"{q.precision}/{q.politica}/{q.tono}/{q.completitud}" if q else "-",
            f"{q.veredicto if q else 'error'} ({r.intentos_qa})",
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
