from datetime import date

from langchain_core.tools import tool

from src import config
from src.data import get_repo
from src.schemas.tool_inputs import CrearEtiquetaInput, VerificarDevolucionInput
from src.tools.crm import dump


def evaluar_devolucion(pedido_id: str, sku: str) -> dict:
    repo = get_repo()
    pedido = repo.get_pedido(pedido_id)
    sku = sku.strip().upper()
    if not pedido:
        return {"elegible": False, "motivo": f"Pedido {pedido_id} no encontrado"}
    if sku not in [p["sku"] for p in pedido["productos"]]:
        return {"elegible": False, "motivo": f"El SKU {sku} no pertenece al pedido"}
    prod = repo.get_producto(sku)
    if not prod or not prod["devolvible"]:
        return {"elegible": False, "motivo": "Producto no devolvible (personalizado o licencia de software)"}
    if pedido["estado_envio"] != "entregado":
        return {"elegible": False, "motivo": f"El pedido aún no está entregado (estado: {pedido['estado_envio']})"}

    cliente = repo.get_cliente(pedido["cliente_id"])
    segmento = cliente["segmento"] if cliente else "Estándar"
    plazo = config.DIAS_DEVOLUCION_VIP if segmento == "VIP" else config.DIAS_DEVOLUCION_ESTANDAR
    dias = (date.today() - date.fromisoformat(pedido["fecha_entrega"])).days
    restantes = plazo - dias
    return {
        "elegible": restantes >= 0,
        "motivo": "Dentro de plazo" if restantes >= 0 else f"Fuera de plazo ({dias} días desde la entrega, plazo {plazo})",
        "segmento": segmento,
        "plazo_dias": plazo,
        "dias_desde_entrega": dias,
        "dias_restantes": max(restantes, 0),
    }


@tool("verificar_devolucion", args_schema=VerificarDevolucionInput)
def verificar_devolucion(pedido_id: str, sku: str) -> str:
    """Verifica si un producto de un pedido es elegible para devolución (plazo según segmento, estado y tipo de producto)."""
    return dump(evaluar_devolucion(pedido_id, sku))


@tool("crear_etiqueta_devolucion", args_schema=CrearEtiquetaInput)
def crear_etiqueta_devolucion(pedido_id: str, sku: str, motivo: str) -> str:
    """Genera una etiqueta de envío (RMA) para devolver un producto y la persiste en la base de datos. Solo funciona si es elegible."""
    ev = evaluar_devolucion(pedido_id, sku)
    if not ev["elegible"]:
        return dump({"error": "No se puede crear la etiqueta", "motivo": ev["motivo"]})
    rma = get_repo().get_or_create_rma(pedido_id, sku, motivo)
    return dump(rma)
