"""
modules/js_fetcher.py — Reverificación con navegador real (Playwright)
=========================================================================
Segunda pasada, EXCLUSIVA para indicadores QA que dependen del HTML/DOM
(element_exists, text_pattern, element_attribute, accessibility) y que el
fetch estático (modules/scraper.py::PageFetcher, basado en `requests` +
BeautifulSoup) clasificó como "No cumple" (compliance = 1).

Motivación (ver auditoría de coherencia del proyecto): `requests` no ejecuta
JavaScript. En plataformas SPA (marcadas "dynamic": true en el catálogo de
empresas, p. ej. VTEX/React/Vue) un elemento puede existir y ser visible para
un usuario real, pero no aparecer en el HTML crudo porque se inyecta al DOM
después de la carga inicial. Este módulo renderiza la página con un
navegador real (headless, vía Playwright) y vuelve a intentar el mismo
chequeo sobre el DOM ya renderizado, para distinguir:

  - Falso negativo del fetch estático  → se reclasifica el indicador.
  - Negativo real (ni siquiera con JS aparece) → se confirma "No cumple",
    ahora con mayor grado de confianza metodológica.

Nota de diseño: requirements.txt ya declaraba `playwright` como dependencia
("scraping de sitios con JavaScript, para dynamic=True"), aunque nunca se
había integrado al código. Este módulo es esa integración pendiente.

IMPORTANTE — marco ético: este módulo reutiliza el MISMO RobotsChecker,
RateLimiter y EthicsLogger que modules/scraper.py::PageFetcher. La cadencia
de acceso y el respeto de robots.txt son una única política para todo el
sistema, sin importar qué motor de fetch se use — agregar un navegador real
no debe significar una vía paralela que eluda los resguardos éticos ya
declarados en modules/ethics.py.

Deshabilitado por defecto (config.JS_RENDER_CONFIG["enabled"] = False):
requiere `pip install playwright && playwright install chromium` en el
entorno donde corre la app.
"""

import logging
import time

from bs4 import BeautifulSoup

from modules.ethics import RobotsChecker, RateLimiter, EthicsLogger

logger = logging.getLogger(__name__)


class JSFetcherNoDisponible(Exception):
    """
    Señala que el navegador no pudo inicializarse en este entorno
    (paquete 'playwright' no instalado, o no se ejecutó
    'playwright install chromium'). El llamador debe capturarla UNA vez y
    desactivar la reverificación para el resto de la corrida, en vez de
    reintentar en cada indicador.
    """


class JSFetcher:
    """
    Fetcher con navegador real (headless, Playwright) para reverificación
    de indicadores QA. Reutiliza los mismos objetos de resguardo ético que
    PageFetcher.
    """

    def __init__(
        self,
        cfg           : dict,
        robots_checker: RobotsChecker,
        rate_limiter  : RateLimiter,
        ethics_logger : EthicsLogger,
    ):
        self.cfg            = cfg
        self.robots_checker = robots_checker
        self.rate_limiter   = rate_limiter
        self.ethics_logger  = ethics_logger
        self._playwright     = None
        self._browser        = None
        self._page           = None
        self._init_fallida   = False

    # ── Ciclo de vida del navegador ─────────────────────────────────────────
    def _get_page(self):
        """
        Inicializa Playwright + Chromium headless (lazy, una sola vez por
        instancia) y retorna una página lista para navegar.
        Lanza JSFetcherNoDisponible si Playwright o el binario de Chromium
        no están disponibles en este entorno.
        """
        if self._page is not None:
            return self._page
        if self._init_fallida:
            raise JSFetcherNoDisponible("Inicialización previa ya falló en esta sesión.")

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            self._init_fallida = True
            raise JSFetcherNoDisponible(
                f"El paquete 'playwright' no está instalado: {exc}"
            ) from exc

        try:
            w, h = self.cfg.get("viewport", (1366, 900))
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=self.cfg.get("headless", True),
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            self._page = self._browser.new_page(
                user_agent = self.cfg.get("user_agent", ""),
                viewport   = {"width": w, "height": h},
            )
            self._page.set_default_navigation_timeout(
                self.cfg.get("page_load_timeout_seconds", 30) * 1000
            )
            logger.info("[PLAYWRIGHT] Navegador headless (Chromium) inicializado correctamente.")
            return self._page
        except Exception as exc:
            self._init_fallida = True
            self.close()
            raise JSFetcherNoDisponible(
                f"No se pudo inicializar Chromium con Playwright en este "
                f"entorno (¿se ejecutó 'playwright install chromium'?): {exc}"
            ) from exc

    def close(self) -> None:
        """Cierra el navegador y Playwright si fueron inicializados."""
        try:
            if self._browser is not None:
                self._browser.close()
        except Exception as exc:
            logger.warning(f"[PLAYWRIGHT] Error al cerrar el navegador: {exc}")
        finally:
            self._browser = None
            self._page    = None
        try:
            if self._playwright is not None:
                self._playwright.stop()
        except Exception as exc:
            logger.warning(f"[PLAYWRIGHT] Error al detener Playwright: {exc}")
        finally:
            self._playwright = None

    # ── Fetch ────────────────────────────────────────────────────────────────
    def get(self, url: str) -> BeautifulSoup | None:
        """
        Navega a `url` con el navegador real, espera a que el DOM se
        estabilice (incluyendo contenido inyectado por JS asincrónico) y
        retorna el HTML ya renderizado parseado con BeautifulSoup.

        Respeta el MISMO robots.txt y la MISMA cadencia de acceso que el
        fetch estático. Retorna None si el acceso está bloqueado o falla.

        Puede propagar JSFetcherNoDisponible si el navegador no está
        disponible en este entorno — el llamador debe capturarla.
        """
        if not self.robots_checker.is_allowed(url):
            self.ethics_logger.record(
                url=url, method="GET-JS", robots_allowed=False,
                notes="Bloqueado por robots.txt (reverificación Playwright)",
            )
            logger.warning(f"[ÉTICA][PLAYWRIGHT] Acceso bloqueado: {url}")
            return None

        page = self._get_page()  # puede lanzar JSFetcherNoDisponible

        self.rate_limiter.wait()

        t0     = time.monotonic()
        status = 0
        try:
            page.goto(url, wait_until="load")
            # Espera adicional tras 'load' para contenido inyectado por JS
            # asincrónico (fetch/XHR posteriores al evento load).
            page.wait_for_timeout(self.cfg.get("post_load_wait_seconds", 2.5) * 1000)
            html    = page.content()
            elapsed = (time.monotonic() - t0) * 1000
            status  = 200
            self.ethics_logger.record(
                url=url, method="GET-JS", status_code=status,
                robots_allowed=True, response_time_ms=elapsed,
                notes="Renderizado con Playwright (motor=chromium-headless)",
            )
            logger.info(f"[GET-JS] {status} | {url} | {elapsed:.0f}ms (renderizado)")
            return BeautifulSoup(html, "lxml")
        except Exception as exc:
            elapsed = (time.monotonic() - t0) * 1000
            self.ethics_logger.record(
                url=url, method="GET-JS", status_code=0,
                response_time_ms=elapsed, notes=f"Error Playwright: {exc}",
            )
            logger.error(f"[ERROR-JS] {url}: {exc}")
            return None
