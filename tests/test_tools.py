import json
import pytest

from src.data import get_repo, init_db
from src.data.sample_tickets import TICKETS
from src.tools import (
    CONSULTAS_TOOLS,
    DEVOLUCIONES_TOOLS,
    SOPORTE_TOOLS,
    TRIAJE_TOOLS,
    buscar_knowledge_base,
    consultar_cliente,
    consultar_pedido,
    crear_etiqueta_devolucion,
    verificar_devolucion,
    verificar_incidencias,
)


@pytest.fixture(scope="module", autouse=True)
def setup_in_memory_db():
    """Usa una base de datos SQLite en memoria durante los tests (rápida y aislada)."""
    init_db("sqlite:///:memory:", reset=True)


def test_cliente_y_pedido():
    cliente = json.loads(consultar_cliente.invoke({"cliente_id": "C900"}))
    assert cliente["segmento"] == "VIP"
    assert any(p["pedido_id"] == "P9001" for p in cliente["pedidos_recientes"])
    assert "error" in json.loads(consultar_cliente.invoke({"cliente_id": "NOPE"}))
    assert json.loads(consultar_pedido.invoke({"pedido_id": "P9001", "cliente_id": "C900"}))["estado_envio"] == "entregado"
    assert "error" in json.loads(consultar_pedido.invoke({"pedido_id": "X"}))


def test_titularidad_pedido_bloquea_acceso_cruzado():
    # P9001 pertenece a C900; si consulta C901 debe denegar el acceso en las 3 herramientas de pedidos/devoluciones
    res_pedido = json.loads(consultar_pedido.invoke({"pedido_id": "P9001", "cliente_id": "C901"}))
    assert "error" in res_pedido and "no pertenece al cliente C901" in res_pedido["error"]

    res_verif = json.loads(verificar_devolucion.invoke({"pedido_id": "P9001", "sku": "SKU-002", "cliente_id": "C901"}))
    assert res_verif["elegible"] is False
    assert "no pertenece al cliente C901" in res_verif["motivo"]

    res_rma = json.loads(
        crear_etiqueta_devolucion.invoke(
            {"pedido_id": "P9001", "sku": "SKU-002", "motivo": "intento cruzado", "cliente_id": "C901"}
        )
    )
    assert "error" in res_rma and "no pertenece al cliente C901" in res_rma["motivo"]


def test_kb_e_incidencias():
    r = json.loads(buscar_knowledge_base.invoke({"consulta": "auriculares bluetooth no emparejan"}))
    assert r["resultados"][0]["id"] == "KB-001"
    inc = json.loads(verificar_incidencias.invoke({"tipo": "caida_servicio"}))
    assert inc["incidencias_activas"][0]["id"] == "INC-001"


def test_devolucion_elegibilidad():
    assert json.loads(verificar_devolucion.invoke({"pedido_id": "P9001", "sku": "SKU-002"}))["elegible"] is True
    assert json.loads(verificar_devolucion.invoke({"pedido_id": "P9002", "sku": "SKU-007"}))["elegible"] is False
    assert json.loads(verificar_devolucion.invoke({"pedido_id": "P9007", "sku": "SKU-011"}))["elegible"] is False
    # Pedido aún en tránsito (retrasado): no elegible para RMA hasta entrega
    no_entregado = json.loads(verificar_devolucion.invoke({"pedido_id": "P9004", "sku": "SKU-005"}))
    assert no_entregado["elegible"] is False
    assert "estado: retrasado" in no_entregado["motivo"]
    assert "rechazar la entrega" in no_entregado["motivo"]


def test_etiqueta_solo_si_elegible_y_persiste_en_db():
    ok = json.loads(crear_etiqueta_devolucion.invoke({"pedido_id": "P9001", "sku": "SKU-002", "motivo": "no me convence"}))
    assert ok["rma_id"] == "RMA-00001"
    ok_2 = json.loads(crear_etiqueta_devolucion.invoke({"pedido_id": "P9001", "sku": "SKU-002", "motivo": "duplicado"}))
    assert ok_2["rma_id"] == "RMA-00001"
    assert "error" in json.loads(crear_etiqueta_devolucion.invoke({"pedido_id": "P9002", "sku": "SKU-007", "motivo": "x"}))


def test_tickets_apuntan_a_datos_reales_en_db():
    repo = get_repo()
    for t in TICKETS:
        assert repo.get_cliente(t["cliente_id"]) is not None
        assert t["pedido_id"] is None or repo.get_pedido(t["pedido_id"]) is not None


def test_persistencia_en_archivo_sqlite(tmp_path):
    db_file = tmp_path / "test_soporte.db"
    url = f"sqlite:///{db_file.as_posix()}"
    repo = init_db(url, reset=True)
    assert db_file.exists()
    assert repo.get_cliente("C900")["nombre"] == "Laura Fernández"
    init_db("sqlite:///:memory:", reset=True)


def test_asignacion_de_herramientas():
    names = lambda ts: {t.name for t in ts}
    assert names(TRIAJE_TOOLS) == {"consultar_cliente"}
    assert names(DEVOLUCIONES_TOOLS) == {"consultar_pedido", "verificar_devolucion", "crear_etiqueta_devolucion"}
    assert names(SOPORTE_TOOLS) == {"buscar_knowledge_base", "verificar_incidencias"}
    assert names(CONSULTAS_TOOLS) == {"consultar_pedido", "consultar_cliente", "verificar_incidencias"}
