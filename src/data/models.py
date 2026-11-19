"""Modelos relacionales SQLAlchemy (compatibles con SQLite y PostgreSQL)."""
from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.data.engine import Base


class ProductoModel(Base):
    __tablename__ = "catalogo"

    sku: Mapped[str] = mapped_column(String(32), primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    categoria: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    precio: Mapped[float] = mapped_column(Float, nullable=False)
    garantia_meses: Mapped[int] = mapped_column(Integer, nullable=False)
    devolvible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sku": self.sku,
            "nombre": self.nombre,
            "categoria": self.categoria,
            "precio": self.precio,
            "garantia_meses": self.garantia_meses,
            "devolvible": self.devolvible,
        }


class ClienteModel(Base):
    __tablename__ = "clientes"

    cliente_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(150), nullable=False)
    telefono: Mapped[str] = mapped_column(String(64), nullable=False)
    segmento: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    fecha_alta: Mapped[str] = mapped_column(String(32), nullable=False)
    historial_tickets: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    total_gastado: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cliente_id": self.cliente_id,
            "nombre": self.nombre,
            "email": self.email,
            "telefono": self.telefono,
            "segmento": self.segmento,
            "fecha_alta": self.fecha_alta,
            "historial_tickets": self.historial_tickets,
            "total_gastado": self.total_gastado,
        }


class PedidoModel(Base):
    __tablename__ = "pedidos"

    pedido_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    cliente_id: Mapped[str] = mapped_column(String(32), ForeignKey("clientes.cliente_id"), nullable=False, index=True)
    fecha_compra: Mapped[str] = mapped_column(String(32), nullable=False)
    estado_envio: Mapped[str] = mapped_column(String(32), nullable=False)
    fecha_entrega: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fecha_estimada: Mapped[str] = mapped_column(String(32), nullable=False)
    transportista: Mapped[str] = mapped_column(String(64), nullable=False)
    tracking: Mapped[str] = mapped_column(String(64), nullable=False)
    zona: Mapped[str] = mapped_column(String(64), nullable=False)

    items: Mapped[list["PedidoItemModel"]] = relationship(
        back_populates="pedido", cascade="all, delete-orphan", lazy="joined"
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "pedido_id": self.pedido_id,
            "cliente_id": self.cliente_id,
            "productos": [{"sku": i.sku, "nombre": i.nombre, "precio": i.precio} for i in self.items],
            "fecha_compra": self.fecha_compra,
            "estado_envio": self.estado_envio,
            "fecha_entrega": self.fecha_entrega,
            "fecha_estimada": self.fecha_estimada,
            "transportista": self.transportista,
            "tracking": self.tracking,
            "zona": self.zona,
        }


class PedidoItemModel(Base):
    __tablename__ = "pedido_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pedido_id: Mapped[str] = mapped_column(String(32), ForeignKey("pedidos.pedido_id"), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(32), ForeignKey("catalogo.sku"), nullable=False)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    precio: Mapped[float] = mapped_column(Float, nullable=False)

    pedido: Mapped["PedidoModel"] = relationship(back_populates="items")


class KnowledgeBaseModel(Base):
    __tablename__ = "knowledge_base"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    categoria: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sintoma: Mapped[str] = mapped_column(Text, nullable=False)
    palabras_clave: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    pasos_solucion: Mapped[list[str]] = mapped_column(JSON, nullable=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "categoria": self.categoria,
            "sintoma": self.sintoma,
            "palabras_clave": self.palabras_clave,
            "pasos_solucion": self.pasos_solucion,
        }


class IncidenciaModel(Base):
    __tablename__ = "incidencias"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tipo: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    servicio: Mapped[str] = mapped_column(String(120), nullable=False)
    zona: Mapped[str] = mapped_column(String(64), nullable=False)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False)
    eta: Mapped[str] = mapped_column(String(64), nullable=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tipo": self.tipo,
            "servicio": self.servicio,
            "zona": self.zona,
            "activa": self.activa,
            "descripcion": self.descripcion,
            "eta": self.eta,
        }


class DevolucionModel(Base):
    __tablename__ = "devoluciones"

    rma_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    pedido_id: Mapped[str] = mapped_column(String(32), ForeignKey("pedidos.pedido_id"), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(32), ForeignKey("catalogo.sku"), nullable=False)
    motivo: Mapped[str] = mapped_column(Text, nullable=False)
    etiqueta_url: Mapped[str] = mapped_column(String(255), nullable=False)
    transportista: Mapped[str] = mapped_column(String(64), nullable=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rma_id": self.rma_id,
            "pedido_id": self.pedido_id,
            "sku": self.sku,
            "motivo": self.motivo,
            "etiqueta_url": self.etiqueta_url,
            "transportista": self.transportista,
        }
