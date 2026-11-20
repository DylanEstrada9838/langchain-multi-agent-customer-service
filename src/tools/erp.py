from typing import Optional

from langchain.tools import ToolRuntime, tool

from src.data import get_repo
from src.pipeline.context import TicketContext
from src.schemas.tool_inputs import ConsultarPedidoInput
from src.tools.crm import dump, ticket_customer


@tool("consultar_pedido", args_schema=ConsultarPedidoInput)
def consultar_pedido(pedido_id: str, cliente_id: Optional[str] = None, *, runtime: ToolRuntime[TicketContext] = None) -> str:
    """Consulta el ERP para un pedido del cliente del ticket."""
    cliente_id = ticket_customer(runtime, cliente_id)
    if cliente_id is None:
        return dump({"error": "Acceso denegado: cliente fuera del contexto del ticket"})
    p = get_repo().get_pedido(pedido_id, cliente_id=cliente_id)
    if not p:
        return dump({"error": f"Pedido {pedido_id} no encontrado"})
    if "error_titularidad" in p:
        return dump({"error": p["error_titularidad"]})
    return dump(p)
