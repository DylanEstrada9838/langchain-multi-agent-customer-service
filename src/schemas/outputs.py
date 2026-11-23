"""Esquemas de salida estructurada (response_format) de los agentes."""
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

Categoria = Literal["devolucion", "soporte_tecnico", "consulta", "queja_grave"]


class ClasificacionTicket(BaseModel):
    categoria: Categoria = Field(description="Naturaleza del ticket")
    prioridad: Literal["baja", "media", "alta", "urgente"] = Field(default="media")
    segmento_cliente: str = Field(default="Estándar", description="Segmento obtenido del CRM: VIP, Premium o Estándar")
    resumen: str = Field(default="", description="Resumen de todas las intenciones o preguntas del cliente")
    pedido_id: Optional[str] = None
    sku: Optional[str] = None
    justificacion: str = Field(default="", description="Breve justificación de la clasificación y prioridad")


class BorradorRespuesta(BaseModel):
    respuesta_cliente: str = Field(description="Borrador del mensaje final al cliente")
    acciones_realizadas: list[str] = Field(default_factory=list)
    datos_verificados: list[str] = Field(default_factory=list, description="Datos obtenidos de herramientas")
    requiere_escalado: bool = False


class EvaluacionQA(BaseModel):
    precision: int = Field(ge=1, le=5)
    politica: int = Field(ge=1, le=5)
    tono: int = Field(ge=1, le=5)
    completitud: int = Field(ge=1, le=5)
    veredicto: Literal["aprobado", "reescrito", "rechazado"]
    respuesta_final: str = Field(description="Respuesta final que verá el cliente")
    observaciones: str = Field(
        default="Sin observaciones adicionales.",
        description="Justificación del veredicto o ajustes realizados",
    )

class EvaluacionQACompacta(EvaluacionQA):
    respuesta_final: str | None = Field(description="Texto corregido si el veredicto es reescrito. Null en otro caso.")

    @model_validator(mode="after")
    def validar_respuesta_segun_veredicto(self) -> "EvaluacionQACompacta":
        if self.veredicto == "reescrito":
            if not self.respuesta_final or not self.respuesta_final.strip():
                raise ValueError("Un veredicto reescrito requiere una respuesta corregida.")
        elif self.respuesta_final is not None:
            raise ValueError("Solo un veredicto reescrito admite una respuesta corregida.")
        return self
