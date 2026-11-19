from typing import Optional

from langchain_core.tools import tool

from src.data import get_repo
from src.schemas.tool_inputs import VerificarIncidenciasInput
from src.tools.crm import dump


@tool("verificar_incidencias", args_schema=VerificarIncidenciasInput)
def verificar_incidencias(tipo: Optional[str] = None, zona: Optional[str] = None) -> str:
    """Consulta incidencias ACTIVAS globales: caídas de servicio o problemas logísticos."""
    res = get_repo().listar_incidencias_activas(tipo=tipo, zona=zona)
    return dump(
        {"incidencias_activas": res}
        if res
        else {"incidencias_activas": [], "mensaje": "No hay incidencias activas"}
    )
