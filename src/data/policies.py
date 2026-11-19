"""Políticas de negocio de la empresa (separadas de los datos persistidos en base de datos)."""
from src import config

POLITICAS = {
    "devoluciones": {
        "plazo_dias_estandar": config.DIAS_DEVOLUCION_ESTANDAR,
        "plazo_dias_vip": config.DIAS_DEVOLUCION_VIP,
        "condiciones": "Producto devolvible, entregado y dentro de plazo. Etiqueta de devolución gratuita.",
        "no_devolvibles": "Productos personalizados y licencias de software.",
        "reembolso": "Reembolso en 5-7 días laborables tras recibir el producto.",
        "cancelacion_antes_entrega": (
            "Si el pedido está en estado 'procesando', puede cancelarse antes del envío derivando el caso a un especialista humano "
            "(requiere_escalado=true). Si ya está en tránsito ('enviado' o 'retrasado'), no puede emitirse una etiqueta RMA todavía: "
            "el cliente debe esperar a que se entregue para generar la etiqueta o rechazar la entrega al transportista."
        ),
    },
    "envios": {
        "estandar": "3-5 días laborables",
        "retraso": "Si el envío supera 5 días, se ofrece cupón de 10 EUR (Estándar/Premium) o 20 EUR (VIP).",
    },
    "compensaciones": {
        "queja_grave": (
            "VIP: reembolso de gastos de envío + cupón 25 EUR + atención prioritaria. "
            "Premium: cupón 15 EUR. Estándar: cupón 10 EUR."
        ),
    },
    "tono": {
        "VIP": "Muy personalizado, tratar de usted, reconocer su fidelidad, ofrecer contacto directo y compensación.",
        "Premium": "Cercano y profesional, mencionar su condición de cliente Premium.",
        "Estándar": "Cordial, claro y conciso.",
    },
}
