from langchain_core.tools import tool

from src.data import get_repo
from src.schemas.tool_inputs import ConsultarPedidoInput
from src.tools.crm import dump


@tool("consultar_pedido", args_schema=ConsultarPedidoInput)
def consultar_pedido(pedido_id: str) -> str:
    """Consulta el ERP: estado de envío, fechas, productos, transportista y tracking de un pedido."""
    p = get_repo().get_pedido(pedido_id)
    return dump(p) if p else dump({"error": f"Pedido {pedido_id} no encontrado"})
