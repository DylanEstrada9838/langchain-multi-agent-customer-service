"""Repository Pattern: abstrae el acceso a datos para las herramientas y el pipeline."""
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sqlalchemy import Engine, func, select

from src.data.engine import Base, build_engine, build_session_factory
from src.data.models import (
    ClienteModel,
    DevolucionModel,
    IncidenciaModel,
    KnowledgeBaseModel,
    PedidoModel,
    ProductoModel,
)
from src.data.seeder import seed_database


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


_ERROR_CODE = re.compile(r"\b(?!sku\b|kb\b)([a-z]{1,8})\s*[-‐‑–]\s*(\d+[a-z]?)\b", re.IGNORECASE)


def _error_codes(text: str) -> set[str]:
    return {f"{prefix.upper()}-{number.upper()}" for prefix, number in _ERROR_CODE.findall(text)}


class SupportRepository:
    """Repositorio de acceso a CRM, ERP, Catálogo, Knowledge Base, Incidencias y RMAs."""

    def __init__(self, engine: Engine, *, as_of: date | None = None):
        self.engine = engine
        self.as_of = as_of
        self._session_factory = build_session_factory(engine)

    def current_date(self) -> date:
        return self.as_of or date.today()

    def get_cliente(self, cliente_id: str) -> dict[str, Any] | None:
        cid = cliente_id.strip().upper()
        with self._session_factory() as s:
            row = s.get(ClienteModel, cid)
            if not row:
                return None
            data = row.to_dict()
            pedidos = s.scalars(
                select(PedidoModel)
                .where(PedidoModel.cliente_id == cid)
                .order_by(PedidoModel.fecha_compra.desc())
            ).unique().all()
            data["pedidos_recientes"] = [
                {
                    "pedido_id": p.pedido_id,
                    "fecha_compra": p.fecha_compra,
                    "estado_envio": p.estado_envio,
                    "productos": [{"sku": i.sku, "nombre": i.nombre} for i in p.items],
                }
                for p in pedidos
            ]
            return data

    def get_pedido(self, pedido_id: str, cliente_id: str | None = None) -> dict[str, Any] | None:
        pid = pedido_id.strip().upper()
        with self._session_factory() as s:
            row = s.get(PedidoModel, pid)
            if not row:
                return None
            data = row.to_dict()
        if cliente_id and data["cliente_id"] != cliente_id.strip().upper():
            return {"error_titularidad": f"Acceso denegado: el pedido {pid} no pertenece al cliente {cliente_id.strip().upper()}"}
        return data

    def get_producto(self, sku: str) -> dict[str, Any] | None:
        code = sku.strip().upper()
        with self._session_factory() as s:
            row = s.get(ProductoModel, code)
            return row.to_dict() if row else None

    def buscar_kb(self, consulta: str, categoria: str | None = None, limit: int = 3) -> list[dict[str, Any]]:
        q = _tokens(consulta)
        codes = _error_codes(consulta)
        with self._session_factory() as s:
            stmt = select(KnowledgeBaseModel)
            if categoria:
                stmt = stmt.where(func.lower(KnowledgeBaseModel.categoria) == categoria.strip().lower())
            rows = s.scalars(stmt).all()

        scored: list[tuple[int, dict[str, Any]]] = []
        for art in rows:
            keywords = " ".join(art.palabras_clave)
            if codes:
                article_codes = _error_codes(f"{art.sintoma} {keywords}")
                if not codes.issubset(article_codes):
                    continue
            score = len(q & _tokens(keywords)) + len(q & _tokens(art.sintoma))
            if score:
                scored.append((score, art.to_dict()))
        scored.sort(key=lambda x: -x[0])
        return [item for _, item in scored[:limit]]

    def listar_incidencias_activas(
        self, tipo: str | None = None, zona: str | None = None
    ) -> list[dict[str, Any]]:
        with self._session_factory() as s:
            stmt = select(IncidenciaModel).where(IncidenciaModel.activa.is_(True))
            if tipo:
                stmt = stmt.where(IncidenciaModel.tipo == tipo)
            rows = s.scalars(stmt).all()

        if zona:
            z = zona.strip().lower()
            rows = [r for r in rows if r.zona.lower() in (z, "global")]
        return [r.to_dict() for r in rows]

    def get_or_create_rma(self, pedido_id: str, sku: str, motivo: str, *, cliente_id: str) -> dict[str, Any]:
        pid, code = pedido_id.strip().upper(), sku.strip().upper()
        with self._session_factory() as s:
            pedido = s.get(PedidoModel, pid)
            if pedido is None or pedido.cliente_id != cliente_id.strip().upper():
                return {"error": "Acceso denegado: el pedido no pertenece al cliente del ticket"}
            existing = s.scalar(
                select(DevolucionModel).where(
                    DevolucionModel.pedido_id == pid,
                    DevolucionModel.sku == code,
                )
            )
            if existing:
                return existing.to_dict()

            total = s.scalar(select(func.count()).select_from(DevolucionModel)) or 0
            rma_id = f"RMA-{total + 1:05d}"
            rma = DevolucionModel(
                rma_id=rma_id,
                pedido_id=pid,
                sku=code,
                motivo=motivo,
                etiqueta_url=f"https://devoluciones.techstore.example/etiqueta/{rma_id}.pdf",
                transportista="Correos Express",
            )
            s.add(rma)
            s.commit()
            return rma.to_dict()


_DEFAULT_REPO: SupportRepository | None = None


def init_db(url: str | None = None, *, reset: bool = False, as_of: date | None = None) -> SupportRepository:
    """Inicializa las tablas y las puebla con datos sintéticos si están vacías."""
    global _DEFAULT_REPO
    engine = build_engine(url)
    if reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)
    with session_factory() as session:
        seed_database(session, as_of=as_of)
    _DEFAULT_REPO = SupportRepository(engine, as_of=as_of)
    return _DEFAULT_REPO


@contextmanager
def evaluation_repository() -> Iterator[SupportRepository]:
    """Use a fresh SQLite fixture for one CLI evaluation, including worker threads."""
    global _DEFAULT_REPO
    previous = _DEFAULT_REPO
    with TemporaryDirectory(prefix="techstore-eval-") as directory:
        db_path = (Path(directory) / "evaluation.db").as_posix()
        repo = init_db(f"sqlite:///{db_path}", as_of=date(2026, 1, 15))
        try:
            yield repo
        finally:
            _DEFAULT_REPO = previous
            repo.engine.dispose()


def get_repo() -> SupportRepository:
    """Devuelve el repositorio activo (inicializando la base de datos por defecto en el primer uso)."""
    global _DEFAULT_REPO
    if _DEFAULT_REPO is None:
        return init_db()
    return _DEFAULT_REPO
