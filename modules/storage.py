"""
modules/storage.py — Capa de persistencia (SQLite + CSV)
=========================================================
Gestiona el almacenamiento estructurado de:
  - Resultados de auditoría QA por dimensión y caso de prueba
  - Datos de productos extraídos por scraping
  - Historial de snapshots temporales (3 cortes)
  - Historial de precios para análisis de variación temporal
"""

import sqlite3
import csv
import logging
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Any

logger = logging.getLogger(__name__)


# ── DDL: esquema relacional ────────────────────────────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS sites (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    base_url      TEXT NOT NULL,
    platform      TEXT,
    region        TEXT,
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS snapshots (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id          TEXT REFERENCES sites(id),
    snapshot_number  INTEGER NOT NULL CHECK(snapshot_number BETWEEN 1 AND 3),
    products_count   INTEGER DEFAULT 0,
    categories_count INTEGER DEFAULT 0,
    scraped_at       TEXT DEFAULT (datetime('now')),
    notes            TEXT
);

CREATE TABLE IF NOT EXISTS products (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id           TEXT REFERENCES sites(id),
    snapshot_id       INTEGER REFERENCES snapshots(id),
    name              TEXT,
    brand             TEXT,
    category          TEXT,
    subcategory       TEXT,
    price_unit        REAL,
    price_bulk        REAL,
    unit_measure      TEXT,
    quantity_per_bulk INTEGER,
    stock_status      TEXT,
    has_discount      INTEGER DEFAULT 0,
    discount_pct      REAL,
    ean               TEXT,
    image_url         TEXT,
    product_url       TEXT NOT NULL,
    scraped_at        TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS price_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id         TEXT REFERENCES sites(id),
    product_url     TEXT NOT NULL,
    product_name    TEXT,
    price_unit      REAL,
    price_bulk      REAL,
    has_discount    INTEGER DEFAULT 0,
    snapshot_number INTEGER,
    recorded_at     TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit_results (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id          TEXT REFERENCES sites(id),
    dimension_id     TEXT NOT NULL,
    test_case_id     TEXT NOT NULL,
    test_case_name   TEXT NOT NULL,
    compliance       INTEGER NOT NULL CHECK(compliance BETWEEN 0 AND 3),
    compliance_label TEXT NOT NULL,
    evidence         TEXT,
    notes            TEXT,
    audited_at       TEXT DEFAULT (datetime('now'))
);
"""


# ── Dataclasses de dominio ─────────────────────────────────────────────────────

@dataclass
class ProductData:
    site_id         : str
    snapshot_id     : int
    product_url     : str
    name            : str   = ""
    brand           : str   = ""
    category        : str   = ""
    subcategory     : str   = ""
    price_unit      : float = 0.0
    price_bulk      : float = 0.0
    unit_measure    : str   = ""
    quantity_per_bulk: int  = 0
    stock_status    : str   = "desconocido"
    has_discount    : bool  = False
    discount_pct    : float = 0.0
    ean             : str   = ""
    image_url       : str   = ""


@dataclass
class AuditResult:
    site_id         : str
    dimension_id    : str
    test_case_id    : str
    test_case_name  : str
    compliance      : int        # 0-3
    compliance_label: str
    evidence        : str = ""
    notes           : str = ""


@dataclass
class SnapshotRecord:
    site_id         : str
    snapshot_number : int
    products_count  : int = 0
    categories_count: int = 0
    notes           : str = ""


# ── DatabaseManager ────────────────────────────────────────────────────────────

class DatabaseManager:
    """
    Wrapper sobre SQLite para todas las operaciones de persistencia.
    Usa context managers internos para garantizar commit/rollback automático.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_schema()
        logger.info(f"[DB] Base de datos inicializada: {db_path}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    # ── Sitios ─────────────────────────────────────────────────────────────────

    def upsert_site(self, site: dict) -> None:
        sql = """
            INSERT OR REPLACE INTO sites (id, name, base_url, platform, region)
            VALUES (:id, :name, :base_url, :platform, :region)
        """
        with self._connect() as conn:
            conn.execute(sql, {
                "id"      : site["id"],
                "name"    : site["name"],
                "base_url": site["base_url"],
                "platform": site.get("platform", ""),
                "region"  : site.get("region", ""),
            })
        logger.debug(f"[DB] Sitio registrado: {site['id']}")

    def get_sites(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM sites").fetchall()
        return [dict(r) for r in rows]

    # ── Snapshots ──────────────────────────────────────────────────────────────

    def insert_snapshot(self, snap: SnapshotRecord) -> int:
        sql = """
            INSERT INTO snapshots (site_id, snapshot_number, products_count,
                                   categories_count, notes)
            VALUES (?, ?, ?, ?, ?)
        """
        with self._connect() as conn:
            cur = conn.execute(sql, (
                snap.site_id, snap.snapshot_number,
                snap.products_count, snap.categories_count, snap.notes,
            ))
            snap_id = cur.lastrowid
        logger.info(f"[DB] Snapshot #{snap.snapshot_number} creado para {snap.site_id} (id={snap_id})")
        return snap_id

    def update_snapshot_count(self, snap_id: int, products_count: int, categories_count: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE snapshots SET products_count=?, categories_count=? WHERE id=?",
                (products_count, categories_count, snap_id),
            )

    # ── Productos ──────────────────────────────────────────────────────────────

    def insert_product(self, p: ProductData) -> None:
        sql = """
            INSERT INTO products
                (site_id, snapshot_id, name, brand, category, subcategory,
                 price_unit, price_bulk, unit_measure, quantity_per_bulk,
                 stock_status, has_discount, discount_pct, ean, image_url, product_url)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """
        with self._connect() as conn:
            conn.execute(sql, (
                p.site_id, p.snapshot_id, p.name, p.brand,
                p.category, p.subcategory, p.price_unit, p.price_bulk,
                p.unit_measure, p.quantity_per_bulk, p.stock_status,
                int(p.has_discount), p.discount_pct, p.ean,
                p.image_url, p.product_url,
            ))

    def insert_products_bulk(self, products: list[ProductData]) -> None:
        """Inserta múltiples productos en una sola transacción."""
        sql = """
            INSERT INTO products
                (site_id, snapshot_id, name, brand, category, subcategory,
                 price_unit, price_bulk, unit_measure, quantity_per_bulk,
                 stock_status, has_discount, discount_pct, ean, image_url, product_url)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """
        rows = [
            (p.site_id, p.snapshot_id, p.name, p.brand,
             p.category, p.subcategory, p.price_unit, p.price_bulk,
             p.unit_measure, p.quantity_per_bulk, p.stock_status,
             int(p.has_discount), p.discount_pct, p.ean,
             p.image_url, p.product_url)
            for p in products
        ]
        with self._connect() as conn:
            conn.executemany(sql, rows)
        logger.info(f"[DB] {len(rows)} productos insertados.")

    def record_price_history(self, p: ProductData, snapshot_number: int) -> None:
        sql = """
            INSERT INTO price_history
                (site_id, product_url, product_name, price_unit,
                 price_bulk, has_discount, snapshot_number)
            VALUES (?,?,?,?,?,?,?)
        """
        with self._connect() as conn:
            conn.execute(sql, (
                p.site_id, p.product_url, p.name, p.price_unit,
                p.price_bulk, int(p.has_discount), snapshot_number,
            ))

    def get_products(self, site_id: str | None = None) -> list[dict]:
        if site_id:
            sql  = "SELECT * FROM products WHERE site_id = ? ORDER BY category, name"
            args = (site_id,)
        else:
            sql  = "SELECT * FROM products ORDER BY site_id, category, name"
            args = ()
        with self._connect() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def get_price_history(self, site_id: str | None = None) -> list[dict]:
        if site_id:
            sql  = "SELECT * FROM price_history WHERE site_id = ? ORDER BY product_url, snapshot_number"
            args = (site_id,)
        else:
            sql  = "SELECT * FROM price_history ORDER BY site_id, product_url, snapshot_number"
            args = ()
        with self._connect() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    # ── Resultados de auditoría ────────────────────────────────────────────────

    def insert_audit_result(self, result: AuditResult) -> None:
        sql = """
            INSERT INTO audit_results
                (site_id, dimension_id, test_case_id, test_case_name,
                 compliance, compliance_label, evidence, notes)
            VALUES (?,?,?,?,?,?,?,?)
        """
        with self._connect() as conn:
            conn.execute(sql, (
                result.site_id, result.dimension_id, result.test_case_id,
                result.test_case_name, result.compliance, result.compliance_label,
                result.evidence, result.notes,
            ))

    def insert_audit_results_bulk(self, results: list[AuditResult]) -> None:
        sql = """
            INSERT INTO audit_results
                (site_id, dimension_id, test_case_id, test_case_name,
                 compliance, compliance_label, evidence, notes)
            VALUES (?,?,?,?,?,?,?,?)
        """
        rows = [
            (r.site_id, r.dimension_id, r.test_case_id, r.test_case_name,
             r.compliance, r.compliance_label, r.evidence, r.notes)
            for r in results
        ]
        with self._connect() as conn:
            conn.executemany(sql, rows)
        logger.info(f"[DB] {len(rows)} resultados de auditoría insertados.")

    def get_audit_results(self, site_id: str | None = None) -> list[dict]:
        if site_id:
            sql  = "SELECT * FROM audit_results WHERE site_id = ? ORDER BY dimension_id, test_case_id"
            args = (site_id,)
        else:
            sql  = "SELECT * FROM audit_results ORDER BY site_id, dimension_id, test_case_id"
            args = ()
        with self._connect() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def get_dimension_scores(self) -> list[dict]:
        """Calcula el promedio de cumplimiento por sitio y dimensión."""
        sql = """
            SELECT
                site_id,
                dimension_id,
                ROUND(AVG(CAST(compliance AS REAL)), 2) AS avg_compliance,
                COUNT(*) AS total_cases,
                SUM(CASE WHEN compliance = 3 THEN 1 ELSE 0 END) AS full_pass,
                SUM(CASE WHEN compliance = 1 THEN 1 ELSE 0 END) AS fail_count
            FROM audit_results
            WHERE compliance > 0
            GROUP BY site_id, dimension_id
            ORDER BY site_id, dimension_id
        """
        with self._connect() as conn:
            rows = conn.execute(sql).fetchall()
        return [dict(r) for r in rows]

    # ── Exportación CSV ────────────────────────────────────────────────────────

    def export_csv(self, table: str, output_path: Path) -> Path:
        """Exporta una tabla completa a CSV con timestamp en el nombre."""
        ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_file = output_path / f"{table}_{ts}.csv"
        with self._connect() as conn:
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        if not rows:
            logger.warning(f"[CSV] Tabla '{table}' vacía — archivo no generado.")
            return out_file
        with open(out_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows([dict(r) for r in rows])
        logger.info(f"[CSV] Exportado: {out_file} ({len(rows)} filas)")
        return out_file

    def export_all_csv(self, output_path: Path) -> list[Path]:
        """Exporta todas las tablas a CSV."""
        tables = ["sites", "snapshots", "products", "price_history", "audit_results"]
        return [self.export_csv(t, output_path) for t in tables]
