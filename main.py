"""CLI: procesa tickets de muestra, un mensaje personalizado o ejecuta la suite de evaluación (`--eval`)."""
import argparse
import json
from datetime import datetime

from rich.console import Console
from rich.table import Table

from src import config
from src.data import init_db
from src.data.sample_tickets import TICKETS
from src.pipeline.evaluator import evaluate_pipeline, evaluate_triage_version, load_eval_dataset
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
        ver = (versions or {}).get("triaje", args.version or config.DEFAULT_AGENT_VERSION)
        console.rule(f"[bold cyan]Evaluando Agente Aislado: triaje ({ver}) — {len(scenarios)} escenarios")
        report = evaluate_triage_version(scenarios, version=ver)
    else:
        if args.version and not versions:
            versions = {"triaje": args.version}
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
    args = ap.parse_args()

    console = Console()
    init_db()

    if args.eval:
        _run_eval_cli(args, console)
        return

    versions = _parse_versions(args.versions) or ({"triaje": args.version} if args.version else None)
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
