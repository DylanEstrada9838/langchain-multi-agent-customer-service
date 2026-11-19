from src.tools.crm import consultar_cliente
from src.tools.devoluciones import crear_etiqueta_devolucion, verificar_devolucion
from src.tools.erp import consultar_pedido
from src.tools.incidencias import verificar_incidencias
from src.tools.knowledge_base import buscar_knowledge_base

TRIAJE_TOOLS = [consultar_cliente]
DEVOLUCIONES_TOOLS = [consultar_pedido, verificar_devolucion, crear_etiqueta_devolucion]
SOPORTE_TOOLS = [buscar_knowledge_base, verificar_incidencias]
CONSULTAS_TOOLS = [consultar_pedido, consultar_cliente, verificar_incidencias]
QA_TOOLS: list = []

__all__ = [
    "consultar_cliente",
    "consultar_pedido",
    "buscar_knowledge_base",
    "verificar_incidencias",
    "verificar_devolucion",
    "crear_etiqueta_devolucion",
    "TRIAJE_TOOLS",
    "DEVOLUCIONES_TOOLS",
    "SOPORTE_TOOLS",
    "CONSULTAS_TOOLS",
    "QA_TOOLS",
]
