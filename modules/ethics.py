"""
modules/ethics.py — Resguardos éticos para scraping académico
==============================================================
Implementa:
 - RobotsChecker : verifica permisos antes de cada acceso
 - RateLimiter   : controla la cadencia de requests
 - EthicsLogger  : registro de auditoría de acceso

Referencia metodológica: el protocolo de este módulo sigue los principios
de scraping ético descriptos en Hirano et al. (2019) y en las
directrices de la ACM sobre investigación con datos web.
"""

import time
import random
import logging
import urllib.robotparser
from datetime import datetime
from urllib.parse import urlparse
from functools import wraps
from pathlib import Path

import requests

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
class RobotsChecker:
    """
    Verifica si la URL objetivo está permitida para acceso automatizado
    según el archivo robots.txt del sitio.

    Comportamiento:
    - Si el sitio no tiene robots.txt, se asume permiso (pero se registra).
    - Si el archivo no es accesible, se asume restricción por precaución.
    - El resultado se cachea por sitio para evitar consultas repetidas.
    """

    def __init__(self, user_agent: str):
        self.user_agent = user_agent
        self._cache: dict[str, urllib.robotparser.RobotFileParser] = {}

    def _get_parser(self, base_url: str) -> urllib.robotparser.RobotFileParser:
        """Obtiene (o construye) el parser de robots.txt para el sitio."""
        if base_url in self._cache:
            return self._cache[base_url]

        robots_url = f"{base_url.rstrip('/')}/robots.txt"
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)

        try:
            rp.read()
            logger.info(f"[ÉTICA] robots.txt leído correctamente: {robots_url}")
        except Exception as exc:
            logger.warning(
                f"[ÉTICA] No se pudo acceder a {robots_url}: {exc}. "
                "Se aplicará restricción por precaución."
            )
            # Crea un parser vacío que denegará todo acceso
            rp = _RestrictiveRobotParser()

        self._cache[base_url] = rp
        return rp

    def is_allowed(self, url: str) -> bool:
        """Retorna True si el acceso a la URL está permitido."""
        parsed   = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        rp       = self._get_parser(base_url)
        allowed  = rp.can_fetch(self.user_agent, url)

        if not allowed:
            logger.warning(f"[ÉTICA] Acceso NO permitido por robots.txt: {url}")
        return allowed

    def get_crawl_delay(self, base_url: str) -> float | None:
        """Retorna el Crawl-Delay indicado en robots.txt, si existe."""
        rp = self._get_parser(base_url)
        return rp.crawl_delay(self.user_agent)


class _RestrictiveRobotParser:
    """Stub de robots.txt que deniega todo acceso (usado como fallback seguro)."""
    def can_fetch(self, *args) -> bool:
        return False
    def crawl_delay(self, *args) -> None:
        return None


# ─────────────────────────────────────────────────────────────────────────────
class RateLimiter:
    """
    Controla la cadencia de requests para no sobrecargar el servidor auditado.

    La demora entre requests incluye:
    1. Valor base configurado (rate_limit_seconds)
    2. Jitter aleatorio (±rate_limit_jitter) para evitar patrones predecibles
    3. Respeto al Crawl-Delay del robots.txt si es mayor al valor base

    La demora efectiva mínima garantizada es siempre ≥ 1 segundo.
    """

    def __init__(
        self,
        base_delay: float = 3.0,
        jitter: float = 1.5,
        crawl_delay: float | None = None,
    ):
        self.base_delay   = base_delay
        self.jitter       = jitter
        self.crawl_delay  = crawl_delay
        self._last_request: float = 0.0

    def wait(self) -> None:
        """Espera el tiempo necesario antes de realizar el próximo request."""
        effective_base = max(
            self.base_delay,
            self.crawl_delay if self.crawl_delay else 0,
            1.0,  # mínimo absoluto
        )
        delay    = effective_base + random.uniform(-self.jitter / 2, self.jitter)
        delay    = max(delay, 1.0)
        elapsed  = time.monotonic() - self._last_request
        sleep_for = max(0.0, delay - elapsed)

        if sleep_for > 0:
            logger.debug(f"[RATE LIMIT] Esperando {sleep_for:.2f}s antes del próximo request.")
            time.sleep(sleep_for)

        self._last_request = time.monotonic()


# ─────────────────────────────────────────────────────────────────────────────
class EthicsLogger:
    """
    Registro de auditoría de todos los accesos realizados durante el estudio.
    Genera un archivo de log con timestamp, URL, método HTTP y resultado,
    asegurando trazabilidad y transparencia académica.
    """

    def __init__(self, log_path: Path):
        self.log_path = log_path
        self._entries: list[dict] = []
        # Escribe cabecera si el archivo no existe
        if not log_path.exists():
            log_path.write_text(
                "timestamp,url,method,status_code,robots_allowed,response_time_ms,notes\n",
                encoding="utf-8",
            )

    def record(
        self,
        url: str,
        method: str = "GET",
        status_code: int = 0,
        robots_allowed: bool = True,
        response_time_ms: float = 0.0,
        notes: str = "",
    ) -> None:
        """Registra un acceso al log CSV de transparencia."""
        entry = {
            "timestamp"       : datetime.now().isoformat(),
            "url"             : url,
            "method"          : method,
            "status_code"     : status_code,
            "robots_allowed"  : robots_allowed,
            "response_time_ms": round(response_time_ms, 2),
            "notes"           : notes.replace(",", ";"),
        }
        self._entries.append(entry)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(
                f"{entry['timestamp']},{entry['url']},{entry['method']},"
                f"{entry['status_code']},{entry['robots_allowed']},"
                f"{entry['response_time_ms']},{entry['notes']}\n"
            )

    def summary(self) -> dict:
        """Retorna un resumen del registro de acceso."""
        if not self._entries:
            return {"total": 0}
        total     = len(self._entries)
        blocked   = sum(1 for e in self._entries if not e["robots_allowed"])
        errors    = sum(1 for e in self._entries if e["status_code"] >= 400)
        avg_ms    = sum(e["response_time_ms"] for e in self._entries) / total
        return {
            "total"          : total,
            "blocked_by_robots": blocked,
            "http_errors"    : errors,
            "avg_response_ms": round(avg_ms, 2),
        }


# ─────────────────────────────────────────────────────────────────────────────
def ethical_request(
    url: str,
    robots_checker: RobotsChecker,
    rate_limiter: RateLimiter,
    ethics_logger: EthicsLogger,
    session: requests.Session,
    timeout: int = 30,
) -> requests.Response | None:
    """
    Realiza un HTTP GET ético: verifica robots.txt, espera el rate limit,
    ejecuta el request y registra el acceso en el log.

    Retorna el objeto Response o None si el acceso está bloqueado o falla.
    """
    if not robots_checker.is_allowed(url):
        ethics_logger.record(url=url, robots_allowed=False, notes="Bloqueado por robots.txt")
        logger.warning(f"[ÉTICA] Acceso bloqueado: {url}")
        return None

    rate_limiter.wait()

    t_start = time.monotonic()
    status  = 0
    try:
        response = session.get(url, timeout=timeout)
        status   = response.status_code
        elapsed  = (time.monotonic() - t_start) * 1000
        ethics_logger.record(
            url=url, status_code=status,
            robots_allowed=True, response_time_ms=elapsed
        )
        logger.info(f"[GET] {status} | {url} | {elapsed:.0f}ms")
        return response
    except requests.RequestException as exc:
        elapsed = (time.monotonic() - t_start) * 1000
        ethics_logger.record(url=url, status_code=0, response_time_ms=elapsed, notes=str(exc))
        logger.error(f"[ERROR] {url}: {exc}")
        return None
