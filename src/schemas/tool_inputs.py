"""Esquemas de entrada (args_schema) de las herramientas."""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ConsultarClienteInput(BaseModel):
    cliente_id: str = Field(description="ID del cliente, p. ej. 'C900'")


class ConsultarPedidoInput(BaseModel):
    pedido_id: str = Field(description="ID del pedido, p. ej. 'P9001'")
    cliente_id: Optional[str] = Field(
        default=None,
        description="ID del cliente que realiza la consulta (para verificar titularidad del pedido)",
    )


class BuscarKBInput(BaseModel):
    consulta: str = Field(description="Descripción del problema técnico")
    categoria: Optional[str] = Field(
        default=None,
        description="Categoría de producto opcional: audio, domotica, wearables, ordenadores, perifericos",
    )


class VerificarIncidenciasInput(BaseModel):
    tipo: Optional[Literal["caida_servicio", "logistica"]] = Field(
        default=None, description="Filtrar por tipo de incidencia"
    )
    zona: Optional[str] = Field(default=None, description="Zona geográfica, p. ej. 'Cataluña'")


class VerificarDevolucionInput(BaseModel):
    pedido_id: str = Field(description="ID del pedido")
    sku: str = Field(description="SKU del producto a devolver, p. ej. 'SKU-002'")
    cliente_id: Optional[str] = Field(
        default=None,
        description="ID del cliente que solicita la devolución (para verificar titularidad del pedido)",
    )


class CrearEtiquetaInput(BaseModel):
    pedido_id: str = Field(description="ID del pedido")
    sku: str = Field(description="SKU del producto a devolver")
    motivo: str = Field(description="Motivo de la devolución")
    cliente_id: Optional[str] = Field(
        default=None,
        description="ID del cliente que solicita la etiqueta (para verificar titularidad del pedido)",
    )
