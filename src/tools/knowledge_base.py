from typing import Optional

from langchain_core.tools import tool

from src.data import get_repo
from src.schemas.tool_inputs import BuscarKBInput
from src.tools.crm import dump


@tool("buscar_knowledge_base", args_schema=BuscarKBInput)
def buscar_knowledge_base(consulta: str, categoria: Optional[str] = None) -> str:
    """Busca en la base de conocimiento manuales de solución de problemas técnicos por síntomas."""
    res = get_repo().buscar_kb(consulta, categoria=categoria)
    if not res:
        return dump({"resultados": [], "mensaje": "Sin artículos relevantes en la KB"})
    return dump({"resultados": res})
