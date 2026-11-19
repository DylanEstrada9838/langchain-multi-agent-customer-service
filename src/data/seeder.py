"""Generador de datos sintéticos (Faker) y escenarios fijos para poblar la base de datos."""
import random
from datetime import date, timedelta

from faker import Faker
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src import config
from src.data.models import (
    ClienteModel,
    IncidenciaModel,
    KnowledgeBaseModel,
    PedidoItemModel,
    PedidoModel,
    ProductoModel,
)

_PRODUCTOS_TEMPLATE = [
    ("Auriculares Bluetooth Pro", "audio", 49, 199, 24, True),
    ("Smartwatch Fit 3", "wearables", 79, 299, 24, True),
    ("Cámara de Seguridad WiFi", "domotica", 39, 149, 24, True),
    ("Altavoz Inteligente Eco", "audio", 59, 179, 24, True),
    ("Portátil UltraBook 14", "ordenadores", 599, 1499, 36, True),
    ("Ratón Inalámbrico Ergo", "perifericos", 19, 79, 24, True),
    ("Teclado Mecánico RGB", "perifericos", 49, 149, 24, True),
    ("Termostato Inteligente", "domotica", 69, 199, 24, True),
    ("Tablet 10 pulgadas", "ordenadores", 199, 599, 24, True),
    ("Cargador Rápido 65W", "accesorios", 19, 59, 12, True),
    ("Funda Personalizada Móvil", "accesorios", 15, 35, 6, False),
    ("Software Antivirus (licencia)", "software", 25, 79, 0, False),
]

_KNOWLEDGE_BASE_SEED = [
    {
        "id": "KB-001",
        "categoria": "audio",
        "sintoma": "Los auriculares Bluetooth no se emparejan",
        "palabras_clave": ["auriculares", "bluetooth", "emparejar", "conectar", "pairing"],
        "pasos_solucion": [
            "Apagar los auriculares y mantener pulsado el botón 10 s hasta ver luz roja/azul alternando",
            "Borrar el dispositivo de la lista Bluetooth del móvil",
            "Volver a buscar y emparejar",
            "Si persiste, actualizar el firmware desde la app",
        ],
    },
    {
        "id": "KB-002",
        "categoria": "audio",
        "sintoma": "Sonido con cortes o poca batería",
        "palabras_clave": ["sonido", "cortes", "batería", "bateria", "altavoz", "auriculares"],
        "pasos_solucion": [
            "Cargar el dispositivo durante 2 horas con el cable original",
            "Alejar de fuentes de interferencia WiFi",
            "Restablecer de fábrica (botón 15 s)",
        ],
    },
    {
        "id": "KB-003",
        "categoria": "domotica",
        "sintoma": "La cámara WiFi no sincroniza con la nube",
        "palabras_clave": ["cámara", "camara", "wifi", "nube", "cloud", "sincroniza", "sincronización", "app"],
        "pasos_solucion": [
            "Comprobar que el router emite en 2.4 GHz",
            "Reiniciar la cámara (desenchufar 30 s)",
            "Cerrar sesión y volver a entrar en la app",
            "Si hay una incidencia activa del servicio cloud, esperar a su resolución",
        ],
    },
    {
        "id": "KB-004",
        "categoria": "domotica",
        "sintoma": "El termostato no mantiene la temperatura programada",
        "palabras_clave": ["termostato", "temperatura", "programación", "programada"],
        "pasos_solucion": [
            "Verificar la hora y zona horaria",
            "Recalibrar sensor desde ajustes",
            "Reinstalar el programa horario",
        ],
    },
    {
        "id": "KB-005",
        "categoria": "wearables",
        "sintoma": "El smartwatch no se enciende o no carga",
        "palabras_clave": ["smartwatch", "reloj", "enciende", "carga", "cargar", "pantalla"],
        "pasos_solucion": [
            "Limpiar los contactos de carga",
            "Usar el cargador original 30 min",
            "Forzar reinicio manteniendo el botón lateral 12 s",
        ],
    },
    {
        "id": "KB-006",
        "categoria": "ordenadores",
        "sintoma": "El portátil va lento o se calienta",
        "palabras_clave": ["portátil", "portatil", "lento", "calienta", "ventilador", "temperatura"],
        "pasos_solucion": [
            "Cerrar procesos en segundo plano",
            "Actualizar BIOS y drivers",
            "Limpiar rejillas de ventilación",
            "Usar perfil de energía equilibrado",
        ],
    },
    {
        "id": "KB-007",
        "categoria": "perifericos",
        "sintoma": "El ratón o teclado inalámbrico no responde",
        "palabras_clave": ["ratón", "raton", "teclado", "inalámbrico", "receptor", "usb", "no responde"],
        "pasos_solucion": [
            "Cambiar las pilas / cargar la batería",
            "Reconectar el receptor USB en otro puerto",
            "Reemparejar con el botón inferior",
        ],
    },
]

_INCIDENCIAS_SEED = [
    {
        "id": "INC-001",
        "tipo": "caida_servicio",
        "servicio": "Cloud de cámaras y app domótica",
        "zona": "Global",
        "activa": True,
        "descripcion": "Fallos de sincronización con la nube que afectan a cámaras WiFi y app domótica",
        "eta": "24 horas",
    },
    {
        "id": "INC-002",
        "tipo": "logistica",
        "servicio": "Transporte nacional",
        "zona": "Cataluña",
        "activa": True,
        "descripcion": "Retrasos de entre 2 y 4 días por huelga del transportista",
        "eta": "72 horas",
    },
    {
        "id": "INC-003",
        "tipo": "caida_servicio",
        "servicio": "Portal de descarga de firmware",
        "zona": "Global",
        "activa": False,
        "descripcion": "Incidencia resuelta la semana pasada",
        "eta": "Resuelta",
    },
    {
        "id": "INC-004",
        "tipo": "logistica",
        "servicio": "Almacén central",
        "zona": "Madrid",
        "activa": False,
        "descripcion": "Retrasos por inventario, ya resueltos",
        "eta": "Resuelta",
    },
    {
        "id": "INC-005",
        "tipo": "caida_servicio",
        "servicio": "Pasarela de reembolsos",
        "zona": "Global",
        "activa": False,
        "descripcion": "Reembolsos lentos, ya normalizados",
        "eta": "Resuelta",
    },
]


def seed_database(session: Session) -> None:
    """Puebla la base de datos si está vacía y garantiza que los escenarios fijos existan siempre."""
    existing = session.scalar(select(func.count()).select_from(ClienteModel))
    has_random_data = bool(existing and existing > 0)

    hoy = date.today()
    Faker.seed(config.FAKER_SEED)
    fake = Faker(config.FAKER_LOCALE)
    rnd = random.Random(config.FAKER_SEED)

    # 1. Catálogo de productos
    catalogo: dict[str, ProductoModel] = {}
    for i, (nombre, cat, pmin, pmax, gar, dev) in enumerate(
        _PRODUCTOS_TEMPLATE[: max(config.NUM_PRODUCTOS, 12)], 1
    ):
        sku = f"SKU-{i:03d}"
        prod = session.get(ProductoModel, sku)
        if prod is None:
            prod = ProductoModel(
                sku=sku,
                nombre=nombre,
                categoria=cat,
                precio=float(rnd.randint(pmin, pmax)),
                garantia_meses=gar,
                devolvible=dev,
            )
            session.add(prod)
        else:
            rnd.randint(pmin, pmax)  # mantener avance determinista del RNG
        catalogo[sku] = prod

    def add_cliente(cid: str, nombre: str, segmento: str, alta_dias: int, tickets: list, gastado: float):
        session.merge(
            ClienteModel(
                cliente_id=cid,
                nombre=nombre,
                email=fake.email(),
                telefono=fake.phone_number(),
                segmento=segmento,
                fecha_alta=(hoy - timedelta(days=alta_dias)).isoformat(),
                historial_tickets=tickets,
                total_gastado=gastado,
            )
        )

    def add_pedido(
        pid: str,
        cid: str,
        skus: list[str],
        dias_compra: int,
        estado: str,
        dias_entrega: int | None = None,
        zona: str = "Madrid",
    ):
        existing_pedido = session.get(PedidoModel, pid)
        if existing_pedido is not None:
            return
        compra = hoy - timedelta(days=dias_compra)
        pedido = PedidoModel(
            pedido_id=pid,
            cliente_id=cid,
            fecha_compra=compra.isoformat(),
            estado_envio=estado,
            fecha_entrega=(hoy - timedelta(days=dias_entrega)).isoformat() if dias_entrega is not None else None,
            fecha_estimada=(compra + timedelta(days=5)).isoformat(),
            transportista=rnd.choice(["SEUR", "Correos Express", "MRW", "DHL"]),
            tracking=fake.bothify("ES##########").upper(),
            zona=zona,
            items=[
                PedidoItemModel(sku=s, nombre=catalogo[s].nombre, precio=catalogo[s].precio)
                for s in skus
            ],
        )
        session.add(pedido)

    # 2. Clientes y pedidos aleatorios (Faker) — solo en la primera inicialización
    if not has_random_data:
        segs = ["Estándar"] * 6 + ["Premium"] * 3 + ["VIP"]
        for i in range(1, config.NUM_CLIENTES + 1):
            add_cliente(
                f"C{i:03d}",
                fake.name(),
                rnd.choice(segs),
                rnd.randint(30, 1500),
                [
                    {"id": f"T-{rnd.randint(1000, 9999)}", "tipo": rnd.choice(["consulta", "soporte_tecnico", "devolucion"])}
                    for _ in range(rnd.randint(0, 3))
                ],
                round(rnd.uniform(50, 5000), 2),
            )

        skus = list(catalogo)
        for i in range(1, config.NUM_PEDIDOS + 1):
            cid = f"C{rnd.randint(1, config.NUM_CLIENTES):03d}"
            dias = rnd.randint(2, 120)
            estado = "entregado" if dias > 8 else rnd.choice(["procesando", "enviado", "retrasado", "entregado"])
            add_pedido(
                f"P{1000 + i}",
                cid,
                rnd.sample(skus, rnd.randint(1, 2)),
                dias,
                estado,
                dias - 4 if estado == "entregado" else None,
            )

    # 3. Escenarios deterministas para los tickets de muestra
    add_cliente("C900", "Laura Fernández", "VIP", 1200, [{"id": "T-0001", "tipo": "consulta"}], 4200.0)
    add_cliente("C901", "Carlos Ruiz", "Estándar", 200, [], 150.0)
    add_cliente("C902", "Marta Soler", "Premium", 600, [{"id": "T-0002", "tipo": "soporte_tecnico"}], 980.0)
    add_cliente("C903", "Javier Ortega", "VIP", 1500, [{"id": "T-0003", "tipo": "queja"}], 6100.0)
    add_cliente("C904", "Ana Beltrán", "Estándar", 90, [], 79.0)
    add_cliente("C905", "Pedro Navarro", "Premium", 400, [], 340.0)
    add_cliente("C906", "Elena Gómez", "Estándar", 60, [], 0.0)

    add_pedido("P9001", "C900", ["SKU-002"], 14, "entregado", 10)
    add_pedido("P9002", "C901", ["SKU-007"], 50, "entregado", 45)
    add_pedido("P9003", "C902", ["SKU-004"], 8, "retrasado", None, zona="Cataluña")
    add_pedido("P9004", "C903", ["SKU-005"], 12, "retrasado", None, zona="Cataluña")
    add_pedido("P9005", "C904", ["SKU-001"], 20, "entregado", 15)
    add_pedido("P9006", "C905", ["SKU-003"], 30, "entregado", 25)
    add_pedido("P9007", "C901", ["SKU-011"], 10, "entregado", 6)
    add_pedido("P9008", "C902", ["SKU-006"], 1, "procesando", None)

    # 4. Knowledge Base e Incidencias
    for art in _KNOWLEDGE_BASE_SEED:
        session.merge(KnowledgeBaseModel(**art))

    for inc in _INCIDENCIAS_SEED[: max(config.NUM_INCIDENCIAS, 1)]:
        session.merge(IncidenciaModel(**inc))

    session.commit()
