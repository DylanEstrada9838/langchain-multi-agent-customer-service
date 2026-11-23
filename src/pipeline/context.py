"""Generación de contexto: información básica del ticket y del cliente desde el repositorio."""
import re
from dataclasses import dataclass

from src.data import get_repo

_ORDER_ID = re.compile(r"\bP\d+\b", re.IGNORECASE)
_LATEST_ORDER = re.compile(
    r"\b(?:[uú]ltim[oa]\s+(?:pedido|compra|producto)|(?:pedido|compra|producto)\s+m[aá]s\s+reciente)\b",
    re.IGNORECASE,
)


def solicita_ultimo_pedido(ticket: dict) -> bool:
    message = ticket["mensaje"]
    return (
        not ticket.get("pedido_id")
        and not _ORDER_ID.search(message)
        and bool(_LATEST_ORDER.search(message))
    )


@dataclass(frozen=True)
class CustomerSnapshot:
    nombre: str
    segmento: str


@dataclass(frozen=True)
class TicketContext:
    cliente_id: str
    customer: CustomerSnapshot | None = None
    latest_order_allowed: bool = True
    latest_order_missing: bool = False

    def authorized_customer(self, requested_id: str | None) -> str | None:
        customer_id = self.cliente_id.strip().upper()
        if not customer_id:
            return None
        if requested_id is not None and requested_id.strip().upper() != customer_id:
            return None
        return customer_id


def cargar_contexto_cliente(cliente_id: str) -> TicketContext:
    record = get_repo().get_customer_snapshot(cliente_id)
    return TicketContext(cliente_id, CustomerSnapshot(*record) if record is not None else None)


def generar_contexto(
    ticket: dict, *, context: TicketContext | None = None, incluir_identidad: bool = True,
) -> str:
    repo = get_repo()
    if context is None:
        cliente = repo.get_cliente(ticket["cliente_id"]) or {}
        cliente_linea = f"Cliente: {cliente.get('nombre', 'Desconocido')} (ID: {ticket['cliente_id']})"
    elif incluir_identidad:
        nombre = context.customer.nombre if context.customer else "Desconocido"
        cliente_linea = f"Cliente: {nombre} (ID: {context.cliente_id})"
    else:
        segmento = context.customer.segmento if context.customer else "Desconocido"
        cliente_linea = f"Segmento verificado: {segmento}"
    fecha_contexto = f"Fecha de referencia: {repo.as_of.isoformat()}\n" if repo.as_of else ""
    return (
        f"TICKET {ticket.get('id', 'N/A')}\n"
        f"{fecha_contexto}"
        f"{cliente_linea}\n"
        f"Pedido referenciado: {ticket.get('pedido_id') or 'ninguno'}\n"
        f"Asunto: {ticket.get('asunto', '')}\n"
        f"Mensaje del cliente: {ticket['mensaje']}"
    )
