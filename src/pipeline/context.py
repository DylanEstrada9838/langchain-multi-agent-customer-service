"""Generación de contexto: información básica del ticket y del cliente desde el repositorio."""
from dataclasses import dataclass

from src.data import get_repo


@dataclass(frozen=True)
class TicketContext:
    cliente_id: str

    def authorized_customer(self, requested_id: str | None) -> str | None:
        customer_id = self.cliente_id.strip().upper()
        if not customer_id:
            return None
        if requested_id is not None and requested_id.strip().upper() != customer_id:
            return None
        return customer_id


def generar_contexto(ticket: dict) -> str:
    repo = get_repo()
    cliente = repo.get_cliente(ticket["cliente_id"]) or {}
    fecha_contexto = f"Fecha de referencia: {repo.as_of.isoformat()}\n" if repo.as_of else ""
    return (
        f"TICKET {ticket.get('id', 'N/A')}\n"
        f"{fecha_contexto}"
        f"Cliente: {cliente.get('nombre', 'Desconocido')} (ID: {ticket['cliente_id']})\n"
        f"Pedido referenciado: {ticket.get('pedido_id') or 'ninguno'}\n"
        f"Asunto: {ticket.get('asunto', '')}\n"
        f"Mensaje del cliente: {ticket['mensaje']}"
    )
