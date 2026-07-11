"""
modules/demo.py — Demostración con datos simulados
===================================================
Genera un conjunto de datos representativos sin realizar requests reales,
permitiendo verificar el funcionamiento completo del sistema (storage,
reporting, gráficos) en entorno local sin conectividad a sitios externos.

Los datos simulados replican el universo muestral propuesto en la Fase 1
del plan de relevamiento: mayoristas de consumo masivo con presencia en Argentina.
"""

import random
import logging
from datetime import datetime, timedelta

from config import COMPLIANCE_SCALE, QA_DIMENSIONS, QA_TEST_CASES, SITES
from modules.storage import DatabaseManager, ProductData, AuditResult, SnapshotRecord

logger = logging.getLogger(__name__)


# ── Datos maestros para simulación ────────────────────────────────────────────

# Sitios simulados alineados al contexto de investigación:
# Provincia de Misiones — Posadas · Garupá · Itaembé Guazú
# Mercado: mayoristas de bienes de consumo masivo
_SIMULATED_SITES = [
    {
        "id"      : "MIS001",
        "name"    : "Makro Posadas",
        "base_url": "https://www.makro.com.ar",
        "platform": "VTEX",
        "region"  : "Misiones · Posadas / Garupá / Itaembé Guazú",
    },
    {
        "id"      : "MIS002",
        "name"    : "DIA% Mayorista",
        "base_url": "https://diaonline.supermercadosdia.com.ar",
        "platform": "Custom",
        "region"  : "Misiones · Posadas / Garupá / Itaembé Guazú",
    },
    {
        "id"      : "MIS003",
        "name"    : "Vital Mayorista NEA",
        "base_url": "https://www.vital.com.ar",
        "platform": "Magento / Custom",
        "region"  : "Misiones · Posadas / Garupá / Itaembé Guazú",
    },
]

_CATEGORIES = [
    "Bebidas sin alcohol", "Aguas y jugos", "Lácteos",
    "Snacks y galletitas", "Limpieza del hogar", "Higiene personal",
    "Enlatados y conservas", "Cereales y pastas", "Aceites y aderezos",
]

_BRANDS = [
    "La Serenísima", "Arcor", "Mastellone", "Molinos", "Danone",
    "Unilever", "P&G", "Pepsico", "Quilmes", "Coca-Cola Andina",
    "SanCor", "Bagley", "Kraft Heinz", "Nestlé", "Havanna",
]

_PRODUCT_TEMPLATES = [
    ("{brand} Leche entera x {qty}lt", "Lácteos",        "lt",  1,  6,  85.0,  190.0),
    ("{brand} Agua mineral x {qty}lt", "Aguas y jugos",  "lt",  1,  6,  45.0,   90.0),
    ("{brand} Galletitas x {qty}g",    "Snacks y galletitas","g", 200,300,180.0, 380.0),
    ("{brand} Detergente x {qty}ml",   "Limpieza del hogar", "ml",750,1500,350.0,680.0),
    ("{brand} Aceite x {qty}lt",       "Aceites y aderezos","lt",  1,  5, 420.0, 840.0),
    ("{brand} Yerba x {qty}kg",        "Cereales y pastas",  "kg",  1,  5, 320.0, 640.0),
    ("{brand} Fideos x {qty}kg",       "Cereales y pastas",  "kg",0.5,  1, 210.0, 420.0),
    ("{brand} Mermelada x {qty}g",     "Enlatados y conservas","g",500,900,380.0, 720.0),
    ("{brand} Jabón x {qty}g",         "Higiene personal",   "g", 100,300,220.0, 430.0),
    ("{brand} Mayonesa x {qty}g",      "Aceites y aderezos", "g", 250,500,310.0, 590.0),
]

# Perfil de cumplimiento por sitio (0-3) para cada dimensión
# Representa diferencias realistas entre plataformas
_SITE_PROFILES = {
    "SIM001": {"D1": 2.8, "D2": 2.4, "D3": 2.6, "D4": 2.2, "D5": 2.5, "D6": 2.0, "D7": 1.8, "D8": 2.7},
    "SIM002": {"D1": 2.2, "D2": 1.6, "D3": 2.0, "D4": 2.4, "D5": 1.8, "D6": 2.6, "D7": 2.2, "D8": 2.0},
    "SIM003": {"D1": 1.8, "D2": 1.2, "D3": 1.5, "D4": 1.8, "D5": 1.4, "D6": 1.6, "D7": 1.0, "D8": 1.6},
}


# ─────────────────────────────────────────────────────────────────────────────
def _gen_price(base: float, variation_pct: float = 0.15) -> float:
    """Genera un precio con variación aleatoria sobre el base."""
    delta = base * variation_pct * (random.random() * 2 - 1)
    return round(base + delta, 2)


def _gen_products(site_id: str, snap_id: int, count: int = 60) -> list[ProductData]:
    """Genera una lista de productos simulados para un sitio y snapshot."""
    products = []
    for _ in range(count):
        tpl    = random.choice(_PRODUCT_TEMPLATES)
        brand  = random.choice(_BRANDS)
        name_tpl, cat, unit, qty_min, qty_max, p_min, p_max = tpl
        qty    = random.choice([qty_min, qty_max])
        name   = name_tpl.format(brand=brand, qty=qty)
        pu     = _gen_price(random.uniform(p_min, p_max))
        pb     = round(pu * random.uniform(5, 12), 2)
        disc   = random.random() < 0.25
        disc_p = round(random.uniform(5, 20), 1) if disc else 0.0
        stock  = random.choices(
            ["disponible", "disponible", "disponible", "sin stock"],
            weights=[80, 80, 80, 20]
        )[0]
        products.append(ProductData(
            site_id          = site_id,
            snapshot_id      = snap_id,
            product_url      = f"{site_id.lower()}/producto/{name.lower().replace(' ','_')[:40]}",
            name             = name,
            brand            = brand,
            category         = cat,
            price_unit       = pu,
            price_bulk       = pb,
            unit_measure     = unit,
            quantity_per_bulk= qty_max,
            stock_status     = stock,
            has_discount     = disc,
            discount_pct     = disc_p,
            ean              = f"779{random.randint(100000000, 999999999)}",
            image_url        = f"https://cdn.{site_id.lower()}.com.ar/img/{random.randint(100,999)}.jpg",
        ))
    return products


def _gen_audit_results(site_id: str, profile: dict) -> list[AuditResult]:
    """
    Genera resultados de auditoría simulados para un sitio, siguiendo
    el perfil de cumplimiento definido en _SITE_PROFILES.
    """
    results = []
    for dim_id, test_cases in QA_TEST_CASES.items():
        target_avg = profile.get(dim_id, 2.0)
        for tc in test_cases:
            # Generar compliance alrededor del promedio objetivo con variación
            raw   = target_avg + random.gauss(0, 0.4)
            comp  = min(3, max(1, round(raw)))
            label = COMPLIANCE_SCALE[comp]
            if comp == 3:
                evidence = f"Verificado OK — selector/patrón encontrado en {site_id.lower()}.com.ar"
                notes    = ""
            elif comp == 2:
                evidence = f"Cumplimiento parcial detectado (revisar manualmente)"
                notes    = "Elemento presente pero con limitaciones de visualización"
            else:
                evidence = ""
                notes    = f"Elemento/patrón no encontrado en la página auditada"
            results.append(AuditResult(
                site_id         = site_id,
                dimension_id    = dim_id,
                test_case_id    = tc["id"],
                test_case_name  = tc["name"],
                compliance      = comp,
                compliance_label= label,
                evidence        = evidence,
                notes           = notes,
            ))
    return results


def _gen_price_history(db: DatabaseManager, site_id: str, products: list[ProductData]) -> None:
    """Simula 3 snapshots temporales con variación de precios entre cortes."""
    # Snapshot 1 ya fue insertado con los productos originales
    for p in products:
        db.record_price_history(p, snapshot_number=1)

    # Snapshots 2 y 3: ajuste de precios (inflación simulada)
    for snap_num in (2, 3):
        inflation = 1 + (snap_num - 1) * random.uniform(0.03, 0.08)
        for p in products:
            new_price = round(p.price_unit * inflation, 2)
            adjusted  = ProductData(
                site_id     = site_id,
                snapshot_id = snap_num,
                product_url = p.product_url,
                name        = p.name,
                price_unit  = new_price,
                price_bulk  = round(p.price_bulk * inflation, 2),
                has_discount= p.has_discount and random.random() > 0.3,
                discount_pct= p.discount_pct,
            )
            db.record_price_history(adjusted, snapshot_number=snap_num)


# ─────────────────────────────────────────────────────────────────────────────
def run_demo(db: DatabaseManager) -> None:
    """
    Punto de entrada del modo demostración.
    Puebla la base de datos con datos simulados y genera el informe completo.
    """
    print("\n" + "═" * 60)
    print("  MODO DEMOSTRACIÓN — Datos simulados")
    print("  Investigación académica: auditoría de mayoristas AR")
    print("═" * 60 + "\n")

    # ── 1. Registrar sitios simulados ────────────────────────────────────────
    for site in _SIMULATED_SITES:
        db.upsert_site(site)
        logger.info(f"[DEMO] Sitio registrado: {site['name']}")

    # ── 2. Generar productos y snapshots ─────────────────────────────────────
    all_products_by_site: dict[str, list[ProductData]] = {}
    for site in _SIMULATED_SITES:
        sid  = site["id"]
        snap = SnapshotRecord(
            site_id         = sid,
            snapshot_number = 1,
            notes           = "Snapshot inicial — datos de demostración",
        )
        snap_id  = db.insert_snapshot(snap)
        products = _gen_products(sid, snap_id, count=random.randint(50, 80))
        db.insert_products_bulk(products)
        db.update_snapshot_count(snap_id, len(products), len(set(p.category for p in products)))
        all_products_by_site[sid] = products
        logger.info(f"[DEMO] {sid}: {len(products)} productos generados.")

    # ── 3. Simular historial de precios (3 snapshots) ────────────────────────
    for sid, products in all_products_by_site.items():
        _gen_price_history(db, sid, products)
        logger.info(f"[DEMO] {sid}: historial de precios (3 snapshots) generado.")

    # ── 4. Generar resultados de auditoría QA ────────────────────────────────
    for site in _SIMULATED_SITES:
        sid     = site["id"]
        profile = _SITE_PROFILES.get(sid, {})
        results = _gen_audit_results(sid, profile)
        db.insert_audit_results_bulk(results)
        logger.info(f"[DEMO] {sid}: {len(results)} resultados de auditoría generados.")

    # ── 5. Imprimir resumen en consola ───────────────────────────────────────
    total_products = sum(len(v) for v in all_products_by_site.values())
    total_results  = sum(
        len(QA_TEST_CASES.get(d, [])) for d in QA_DIMENSIONS
    ) * len(_SIMULATED_SITES)

    print(f"  ✓ {len(_SIMULATED_SITES)} sitios registrados")
    print(f"  ✓ {total_products} productos simulados")
    print(f"  ✓ {total_results} casos de prueba evaluados")
    print(f"  ✓ Historial de precios: 3 cortes temporales por sitio\n")
    print("  Base de datos populada. Ejecute 'report' para generar el informe.\n")
