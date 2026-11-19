import json

from langchain_core.tools import tool

from src.data import get_repo
from src.schemas.tool_inputs import ConsultarClienteInput


def dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


@tool("consultar_cliente", args_schema=ConsultarClienteInput)
def consultar_cliente(cliente_id: str) -> str:
    """Consulta el CRM: segmento (VIP/Premium/Estándar), datos de contacto e historial de tickets de un cliente."""
    c = get_repo().get_cliente(cliente_id)
    return dump(c) if c else dump({"error": f"Cliente {cliente_id} no encontrado"})
