"""
modules/scraper.py — Motor de scraping ético
=============================================
Extrae datos estructurados de sitios mayoristas aplicando las salvaguardas
éticas definidas en modules/ethics.py:
  - Verificación de robots.txt antes de cada acceso
  - Rate limiting configurable con jitter aleatorio
  - Registro de auditoría de todos los accesos realizados
  - Límites máximos de extracción por sitio y categoría

Clases principales:
  - PageFetcher      : obtiene y parsea HTML de forma ética
  - ProductExtractor : extrae datos de una ficha de producto
  - CatalogExtractor : recorre el catálogo de un sitio
  - ScrapingEngine   : orquestador principal (invocado desde main.py)
"""

import re
import time
import logging
import random
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from config import SCRAPING_CONFIG, SITES, SNAPSHOTS_DIR, LOGS_DIR
from modules.ethics import RobotsChecker, RateLimiter, EthicsLogger, ethical_request
from modules.storage import DatabaseManager, ProductData, SnapshotRecord

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
class PageFetcher:
    """
    Obtiene HTML de páginas web de forma ética.
    Aplica verificación de robots.txt, rate limiting y registro de acceso.
    """

    def __init__(self, cfg: dict = SCRAPING_CONFIG):
        self.cfg             = cfg
        self.session         = self._build_session(cfg)
        self.robots_checker  = RobotsChecker(cfg["user_agent"])
        self.rate_limiter    = RateLimiter(
            base_delay = cfg["rate_limit_seconds"],
            jitter     = cfg["rate_limit_jitter"],
        )
        self.ethics_log      = EthicsLogger(
            LOGS_DIR / f"access_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )

    @staticmethod
    def _build_session(cfg: dict) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "User-Agent": cfg["user_agent"],
            **cfg.get("headers", {}),
        })
        return session

    def get(self, url: str) -> BeautifulSoup | None:
        """Obtiene y parsea una página. Retorna None si no es accesible."""
        response = ethical_request(
            url            = url,
            robots_checker = self.robots_checker,
            rate_limiter   = self.rate_limiter,
            ethics_logger  = self.ethics_log,
            session        = self.session,
            timeout        = self.cfg["timeout_seconds"],
        )
        if response is None or response.status_code >= 400:
            return None
        return BeautifulSoup(response.text, "lxml")

    def get_response(self, url: str) -> requests.Response | None:
        """Retorna el objeto Response sin parsear (para chequeos de código HTTP)."""
        return ethical_request(
            url            = url,
            robots_checker = self.robots_checker,
            rate_limiter   = self.rate_limiter,
            ethics_logger  = self.ethics_log,
            session        = self.session,
            timeout        = self.cfg["timeout_seconds"],
        )

    def measure_response_time(self, url: str) -> float:
        """Retorna el tiempo de respuesta en segundos. -1 si falla."""
        if not self.robots_checker.is_allowed(url):
            return -1.0
        self.rate_limiter.wait()
        t0 = time.monotonic()
        try:
            self.session.get(url, timeout=self.cfg["timeout_seconds"])
            return time.monotonic() - t0
        except Exception:
            return -1.0

    def ethics_summary(self) -> dict:
        return self.ethics_log.summary()


# ─────────────────────────────────────────────────────────────────────────────
class ProductExtractor:
    """
    Extrae datos estructurados de una ficha de producto o de una tarjeta
    de producto dentro de un listado de categoría.
    Usa los selectores configurados por plataforma en config.SITES.
    """

    # Patrones para extraer unidad de medida de texto libre
    _UNIT_PATTERN = re.compile(
        r'(\d[\d.,]*)\s*'
        r'(kg|kgs|kilos?|g|gr|gramos?|lt?|lts|litros?|ml|cc|un|und|unid|'
        r'pack|packs?|caja|cajas|bulto|bultos?)',
        re.IGNORECASE,
    )
    _PRICE_PATTERN = re.compile(r'[\$\s]*([\d.,]+)', re.IGNORECASE)

    def __init__(self, site_cfg: dict):
        self.site_cfg  = site_cfg
        self.selectors = site_cfg.get("selectors", {})
        self.base_url  = site_cfg["base_url"]

    def _text(self, soup: BeautifulSoup, selector_key: str) -> str:
        """Extrae texto del primer elemento que coincide con el selector."""
        sel = self.selectors.get(selector_key, "")
        if not sel:
            return ""
        tag = soup.select_one(sel)
        return tag.get_text(strip=True) if tag else ""

    def _parse_price(self, raw: str) -> float:
        """Convierte string de precio a float."""
        raw = raw.replace(".", "").replace(",", ".")
        m   = self._PRICE_PATTERN.search(raw)
        if m:
            try:
                return float(m.group(1).replace(".", "").replace(",", "."))
            except ValueError:
                pass
        return 0.0

    def _parse_unit_measure(self, text: str) -> tuple[str, int]:
        """Extrae unidad de medida y cantidad del texto. Retorna (unidad, cantidad)."""
        m = self._UNIT_PATTERN.search(text)
        if m:
            return m.group(2).lower(), int(float(m.group(1).replace(",", ".")))
        return "", 0

    def from_card(
        self,
        card: BeautifulSoup,
        site_id: str,
        snapshot_id: int,
        category: str = "",
    ) -> ProductData | None:
        """Extrae un ProductData de una tarjeta de producto en un listado."""
        # URL del producto
        link  = card.select_one("a[href]")
        if not link:
            return None
        href  = link.get("href", "")
        url   = urljoin(self.base_url, href) if href.startswith("/") else href

        # Nombre
        name_tag = card.select_one(self.selectors.get("product_name", "h3, .name, [class*='name']"))
        name     = name_tag.get_text(strip=True) if name_tag else ""

        # Precio
        price_tag = card.select_one(self.selectors.get("product_price", ".price, [class*='price']"))
        price_raw = price_tag.get_text(strip=True) if price_tag else "0"
        price     = self._parse_price(price_raw)

        # Imagen y alt-text
        img       = card.select_one(self.selectors.get("product_image", "img"))
        image_url = img.get("src", "") if img else ""

        # Unidad de medida (del nombre del producto o atributos)
        unit, qty = self._parse_unit_measure(name)

        # Stock
        stock_tag   = card.select_one(self.selectors.get("stock_indicator", "[class*='stock']"))
        stock_text  = stock_tag.get_text(strip=True).lower() if stock_tag else ""
        stock_status = (
            "sin stock" if any(w in stock_text for w in ["sin stock", "agotado", "out"])
            else "disponible" if stock_text
            else "desconocido"
        )

        # Descuento (heurístico: si hay precio tachado y precio actual)
        old_price_tag = card.select_one("[class*='old'], [class*='list'], [class*='prev']")
        has_discount  = old_price_tag is not None

        return ProductData(
            site_id          = site_id,
            snapshot_id      = snapshot_id,
            product_url      = url,
            name             = name,
            category         = category,
            price_unit       = price,
            unit_measure     = unit,
            quantity_per_bulk= qty,
            stock_status     = stock_status,
            has_discount     = has_discount,
            image_url        = image_url,
        )

    def from_detail_page(
        self,
        soup: BeautifulSoup,
        url: str,
        site_id: str,
        snapshot_id: int,
        category: str = "",
    ) -> ProductData | None:
        """Extrae datos completos de la página de detalle de un producto."""
        if soup is None:
            return None

        # Nombre
        name_candidates = [
            soup.select_one(self.selectors.get("product_name", "")),
            soup.select_one("h1"),
            soup.select_one("[itemprop='name']"),
        ]
        name = next((t.get_text(strip=True) for t in name_candidates if t), "")

        # Precio unitario
        price_candidates = [
            soup.select_one(self.selectors.get("product_price", "")),
            soup.select_one("[itemprop='price']"),
            soup.select_one(".price"),
        ]
        price_tag = next((t for t in price_candidates if t), None)
        price_raw = (price_tag.get("content") or price_tag.get_text(strip=True)) if price_tag else "0"
        price     = self._parse_price(price_raw)

        # Marca
        brand_tag = soup.select_one("[itemprop='brand'], [class*='brand'], [class*='marca']")
        brand     = brand_tag.get_text(strip=True) if brand_tag else ""

        # Unidad
        full_text    = soup.get_text(separator=" ")
        unit, qty    = self._parse_unit_measure(name + " " + full_text[:500])

        # EAN / código de barras
        ean_tag = soup.select_one("[itemprop='gtin13'], [itemprop='gtin8'], [class*='ean'], [class*='sku']")
        ean     = ean_tag.get_text(strip=True) if ean_tag else ""

        # Imagen
        img_tag   = soup.select_one(self.selectors.get("product_image", "") or "[itemprop='image']")
        image_url = ""
        if img_tag:
            image_url = img_tag.get("src") or img_tag.get("content") or ""

        # Stock
        stock_tag    = soup.select_one(self.selectors.get("stock_indicator", "") or "[class*='availability']")
        stock_text   = stock_tag.get_text(strip=True).lower() if stock_tag else ""
        stock_status = (
            "sin stock"   if any(w in stock_text for w in ["sin stock", "agotado", "out"])
            else "disponible" if stock_text
            else "desconocido"
        )

        # Descuento
        old_price_tag = soup.select_one("[class*='oldPrice'], [class*='listPrice'], [class*='de'] .price")
        has_discount  = old_price_tag is not None
        discount_pct  = 0.0
        if has_discount:
            old_price = self._parse_price(old_price_tag.get_text(strip=True))
            if old_price > 0 and price > 0:
                discount_pct = round((1 - price / old_price) * 100, 1)

        # Precio por bulto
        bulk_candidates = [
            soup.select_one("[class*='bulk'], [class*='pack'], [class*='caja']"),
            soup.select_one("[class*='packPrice']"),
        ]
        bulk_tag  = next((t for t in bulk_candidates if t), None)
        price_bulk = self._parse_price(bulk_tag.get_text(strip=True)) if bulk_tag else 0.0

        return ProductData(
            site_id          = site_id,
            snapshot_id      = snapshot_id,
            product_url      = url,
            name             = name,
            brand            = brand,
            category         = category,
            price_unit       = price,
            price_bulk       = price_bulk,
            unit_measure     = unit,
            quantity_per_bulk= qty,
            stock_status     = stock_status,
            has_discount     = has_discount,
            discount_pct     = discount_pct,
            ean              = ean,
            image_url        = image_url,
        )


# ─────────────────────────────────────────────────────────────────────────────
class CatalogExtractor:
    """
    Recorre el catálogo de un sitio: extrae categorías y los productos
    de cada una respetando los límites de extracción configurados.
    """

    def __init__(self, site_cfg: dict, fetcher: PageFetcher, cfg: dict = SCRAPING_CONFIG):
        self.site_cfg  = site_cfg
        self.fetcher   = fetcher
        self.cfg       = cfg
        self.extractor = ProductExtractor(site_cfg)
        self.base_url  = site_cfg["base_url"]

    def get_categories(self, soup: BeautifulSoup) -> list[dict]:
        """Extrae categorías de primer nivel de la página de inicio."""
        categories = []
        sel        = self.site_cfg["selectors"].get("category_links", "nav a")
        links      = soup.select(sel)[:30]   # máximo 30 categorías
        seen_hrefs = set()

        for link in links:
            href = link.get("href", "")
            text = link.get_text(strip=True)
            if not href or not text or href in seen_hrefs:
                continue
            # Filtrar links de utilidad (login, contacto, etc.)
            skip_words = ["login", "cuenta", "carrito", "contacto", "blog", "ayuda", "#"]
            if any(w in href.lower() for w in skip_words):
                continue
            seen_hrefs.add(href)
            full_url = urljoin(self.base_url, href) if href.startswith("/") else href
            if urlparse(full_url).netloc == urlparse(self.base_url).netloc:
                categories.append({"name": text, "url": full_url})

        logger.info(f"[CATALOG] {len(categories)} categorías encontradas en {self.base_url}")
        return categories

    def scrape_category(
        self,
        category: dict,
        site_id: str,
        snapshot_id: int,
    ) -> list[ProductData]:
        """Extrae productos de una página de categoría."""
        products = []
        soup     = self.fetcher.get(category["url"])
        if soup is None:
            return products

        card_sel = self.site_cfg["selectors"].get("product_card", ".product-item, [class*='product']")
        cards    = soup.select(card_sel)
        limit    = self.cfg["max_products_per_category"]
        logger.info(f"[CATALOG] {len(cards)} tarjetas en '{category['name']}' (límite {limit})")

        for card in cards[:limit]:
            p = self.extractor.from_card(
                card        = card,
                site_id     = site_id,
                snapshot_id = snapshot_id,
                category    = category["name"],
            )
            if p and p.name:
                products.append(p)

        return products

    def run(
        self,
        site_id: str,
        snapshot_id: int,
    ) -> tuple[list[ProductData], list[dict]]:
        """
        Ejecuta el scraping completo del catálogo.
        Retorna (lista de productos, lista de categorías).
        """
        logger.info(f"[SCRAPER] Iniciando scraping de catálogo: {self.base_url}")
        home_soup = self.fetcher.get(self.base_url)
        if home_soup is None:
            logger.error(f"[SCRAPER] No se pudo acceder a {self.base_url}")
            return [], []

        categories   = self.get_categories(home_soup)
        all_products : list[ProductData] = []
        site_limit   = self.cfg["max_products_per_site"]

        for cat in categories:
            if len(all_products) >= site_limit:
                logger.info(f"[SCRAPER] Límite de {site_limit} productos alcanzado.")
                break
            products = self.scrape_category(cat, site_id, snapshot_id)
            all_products.extend(products)
            logger.info(
                f"[SCRAPER] '{cat['name']}': {len(products)} productos | "
                f"Total acumulado: {len(all_products)}"
            )

        return all_products, categories


# ─────────────────────────────────────────────────────────────────────────────
class ScrapingEngine:
    """
    Orquestador principal del módulo de scraping.
    Coordina el fetcher, el extractor y el almacenamiento.
    Invocado desde main.py con el comando 'scrape'.
    """

    def __init__(self, db: DatabaseManager, cfg: dict = SCRAPING_CONFIG):
        self.db      = db
        self.cfg     = cfg
        self.fetcher = PageFetcher(cfg)

    def run(
        self,
        site_filter    = None,
        snapshot_number= 1,
        sites_override = None,
    ):
        """
        Ejecuta el scraping para todos los sitios configurados (o uno en particular).

        Args:
            site_filter     : ID del sitio. None = todos.
            snapshot_number : Número del corte temporal (1, 2 o 3).
            sites_override  : Lista de sitios ad-hoc (override de config.SITES).
        """
        source = sites_override if sites_override is not None else SITES
        sites = [
            s for s in source
            if site_filter is None
            or s["id"].lower() == site_filter.lower()
            or s["name"].lower() == site_filter.lower()
        ]
        if not sites:
            logger.error(f"[SCRAPER] No se encontró el sitio: {site_filter}")
            return

        logger.info(f"[SCRAPER] === Iniciando scraping — Snapshot #{snapshot_number} ===")

        for site_cfg in sites:
            self.db.upsert_site(site_cfg)
            self._scrape_site(site_cfg, snapshot_number)

        summary = self.fetcher.ethics_summary()
        logger.info(f"[SCRAPER] Resumen ético de accesos: {summary}")

    def _scrape_site(self, site_cfg: dict, snapshot_number: int) -> None:
        site_id = site_cfg["id"]
        logger.info(f"[SCRAPER] ── Sitio: {site_cfg['name']} ({site_id}) ──")

        # Crear registro de snapshot
        snap = SnapshotRecord(
            site_id         = site_id,
            snapshot_number = snapshot_number,
            notes           = f"Snapshot automático #{snapshot_number}",
        )
        snap_id = self.db.insert_snapshot(snap)

        # Ejecutar scraping de catálogo
        catalog   = CatalogExtractor(site_cfg, self.fetcher, self.cfg)
        products, categories = catalog.run(site_id, snap_id)

        if products:
            # Persistir productos
            self.db.insert_products_bulk(products)
            # Registrar historial de precios
            for p in products:
                self.db.record_price_history(p, snapshot_number)
            # Actualizar contadores del snapshot
            self.db.update_snapshot_count(snap_id, len(products), len(categories))
            logger.info(
                f"[SCRAPER] {site_id}: {len(products)} productos de "
                f"{len(categories)} categorías almacenados."
            )
        else:
            logger.warning(f"[SCRAPER] {site_id}: Sin productos extraídos (verificar selectores o acceso).")
