"""CLI: procesa tickets de muestra o un mensaje personalizado."""
import argparse
import json
from datetime import datetime

from rich.console import Console
from rich.table import Table

from src import config
from src.data import init_db
from src.data.sample_tickets import TICKETS
from src.pipeline.orchestrator import construir_sistema, procesar_ticket, ticket_personalizado


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mensaje", help="Mensaje personalizado del cliente")
    ap.add_argument("--cliente", default="C900", help="ID de cliente para el mensaje personalizado")
    ap.add_argument("--pedido", default=None)
    args = ap.parse_args()

    console = Console()
    init_db()
    sistema = construir_sistema()
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
        console.print(
            f"[cyan]{r.clasificacion.categoria}[/] | prioridad {r.clasificacion.prioridad} | "
            f"{r.clasificacion.segmento_cliente} -> {r.especialista} | "
            f"QA: {r.qa.veredicto} (intentos: {r.intentos_qa}){esc_tag}"
        )
        console.print(r.respuesta_final)

    table = Table(title="Resumen")
    for col in ("Ticket", "Categoría", "Prioridad", "Segmento", "Especialista", "P/Pol/T/C", "QA (int.)", "Escalado", "s"):
        table.add_column(col)
    for r in resultados:
        q = r.qa
        table.add_row(
            r.ticket_id,
            r.clasificacion.categoria,
            r.clasificacion.prioridad,
            r.clasificacion.segmento_cliente,
            r.especialista,
            f"{q.precision}/{q.politica}/{q.tono}/{q.completitud}",
            f"{q.veredicto} ({r.intentos_qa})",
            "SÍ" if r.escalado_humano else "NO",
            str(r.segundos),
        )
    console.print(table)

    config.OUTPUT_DIR.mkdir(exist_ok=True)
    out = config.OUTPUT_DIR / f"resultados_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps([r.model_dump() for r in resultados], ensure_ascii=False, indent=2), encoding="utf-8")
    console.print(f"Guardado en {out}")


if __name__ == "__main__":
    main()
