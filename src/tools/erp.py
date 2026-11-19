from typing import Optional

from langchain_core.tools import tool

from src.data import get_repo
from src.schemas.tool_inputs import ConsultarPedidoInput
from src.tools.crm import dump


@tool("consultar_pedido", args_schema=ConsultarPedidoInput)
def consultar_pedido(pedido_id: str, cliente_id: Optional[str] = None) -> str:
    """Consulta el ERP: estado de envío, fechas, productos, transportista y tracking de un pedido. Verifica titularidad si se pasa cliente_id."""
    p = get_repo().get_pedido(pedido_id, cliente_id=cliente_id)
    if not p:
        return dump({"error": f"Pedido {pedido_id} no encontrado"})
    if "error_titularidad" in p:
        return dump({"error": p["error_titularidad"]})
    return dump(p)
