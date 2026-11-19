"""Generación de contexto: información básica del ticket y del cliente desde el repositorio."""
from src.data import get_repo


def generar_contexto(ticket: dict) -> str:
    cliente = get_repo().get_cliente(ticket["cliente_id"]) or {}
    return (
        f"TICKET {ticket.get('id', 'N/A')}\n"
        f"Cliente: {cliente.get('nombre', 'Desconocido')} (ID: {ticket['cliente_id']})\n"
        f"Pedido referenciado: {ticket.get('pedido_id') or 'ninguno'}\n"
        f"Asunto: {ticket.get('asunto', '')}\n"
        f"Mensaje del cliente: {ticket['mensaje']}"
    )
