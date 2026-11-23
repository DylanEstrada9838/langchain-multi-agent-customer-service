import json

from langchain.tools import ToolRuntime, tool

from src.data import get_repo
from src.pipeline.context import TicketContext
from src.schemas.tool_inputs import ConsultarClienteInput


def dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


@tool("consultar_cliente", args_schema=ConsultarClienteInput)
def consultar_cliente(cliente_id: str, *, runtime: ToolRuntime[TicketContext] = None) -> str:
    """Consulta el CRM: segmento (VIP/Premium/Estándar), datos de contacto, historial de tickets y lista de pedidos recientes del cliente."""
    cliente_id = ticket_customer(runtime, cliente_id)
    if cliente_id is None:
        return dump({"error": "Acceso denegado: cliente fuera del contexto del ticket"})
    c = get_repo().get_cliente(cliente_id)
    return dump(c) if c else dump({"error": f"Cliente {cliente_id} no encontrado"})


@tool
def consultar_ultimo_pedido(runtime: ToolRuntime[TicketContext] = None) -> str:
    """Devuelve el último pedido del cliente del ticket, con su estado y los productos."""
    cliente_id = ticket_customer(runtime, None)
    if cliente_id is None:
        return dump({"error": "Acceso denegado: cliente fuera del contexto del ticket"})
    if not runtime.context.latest_order_allowed:
        return dump({"error": "La solicitud no requiere buscar el último pedido"})
    return dump({"ultimo_pedido": get_repo().get_latest_order_summary(cliente_id)})


def ticket_customer(runtime: ToolRuntime[TicketContext] | None, requested_id: str | None) -> str | None:
    context = runtime.context if runtime is not None else None
    return context.authorized_customer(requested_id) if isinstance(context, TicketContext) else None
