"""
modules/auditor.py — Motor de auditoría QA del proceso de compra
================================================================
Evalúa el proceso de compra de cada sitio mayorista contra los casos
de prueba definidos en config.QA_TEST_CASES, produciendo un resultado
estructurado por dimensión con escala de cumplimiento 0-3.

Tipos de verificación implementados:
  element_exists    : selector CSS presente en la página
  text_pattern      : expresión regular encontrada en el texto
  response_code     : código HTTP esperado
  performance       : tiempo de respuesta < umbral
  url_check         : propiedad de la URL (https)
  element_attribute : atributo de elemento presente y no vacío
  accessibility     : regla básica de accesibilidad (WCAG)
"""

import re
import time
import logging
from dataclasses import dataclass, field
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from config import (
    SITES, QA_DIMENSIONS, QA_TEST_CASES, COMPLIANCE_SCALE, SCRAPING_CONFIG,
    JS_RENDER_CONFIG,
)
from modules.ethics import RobotsChecker, RateLimiter, EthicsLogger, ethical_request
from modules.storage import DatabaseManager, AuditResult
from modules.scraper import PageFetcher
from modules.js_fetcher import JSFetcher, JSFetcherNoDisponible

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class CheckOutcome:
    """Resultado de un caso de prueba individual."""
    test_case_id   : str
    test_case_name : str
    dimension_id   : str
    passed         : bool
    partial        : bool = False
    evidence       : str  = ""
    notes          : str  = ""
    # 'estatico' (default) | 'js_rendered' (reclasificado tras Playwright) |
    # 'estatico_confirmado_js' (Playwright confirmó el "No cumple" estático)
    verification_method: str = "estatico"

    @property
    def compliance(self) -> int:
        """Convierte el resultado en la escala 0-3."""
        if self.passed:
            return 3
        if self.partial:
            return 2
        return 1

    @property
    def compliance_label(self) -> str:
        return COMPLIANCE_SCALE.get(self.compliance, "")


@dataclass
class DimensionSummary:
    """Resumen de resultados de una dimensión completa."""
    dimension_id  : str
    dimension_name: str
    outcomes      : list[CheckOutcome] = field(default_factory=list)

    @property
    def avg_score(self) -> float:
        if not self.outcomes:
            return 0.0
        scored = [o.compliance for o in self.outcomes if o.compliance > 0]
        return round(sum(scored) / len(scored), 2) if scored else 0.0

    @property
    def pass_rate(self) -> float:
        if not self.outcomes:
            return 0.0
        total  = len(self.outcomes)
        passed = sum(1 for o in self.outcomes if o.compliance >= 2)
        return round(passed / total * 100, 1)


# ─────────────────────────────────────────────────────────────────────────────
class PageChecker:
    """
    Verifica un caso de prueba contra el contenido de una página HTML.
    Implementa todos los tipos de verificación definidos en config.
    """

    def check(
        self,
        test_case  : dict,
        soup       : BeautifulSoup | None,
        url        : str,
        response_code: int = 200,
        response_time: float = 0.0,
    ) -> CheckOutcome:
        """
        Ejecuta la verificación correspondiente al tipo del caso de prueba.
        Retorna un CheckOutcome con el resultado.
        """
        check_type = test_case.get("check_type", "")
        tc_id      = test_case["id"]
        tc_name    = test_case["name"]
        dim_id     = tc_id.split(".")[0]

        try:
            if check_type == "element_exists":
                return self._check_element_exists(test_case, soup, tc_id, tc_name, dim_id)
            elif check_type == "text_pattern":
                return self._check_text_pattern(test_case, soup, tc_id, tc_name, dim_id)
            elif check_type == "response_code":
                return self._check_response_code(test_case, response_code, tc_id, tc_name, dim_id)
            elif check_type == "performance":
                return self._check_performance(test_case, response_time, tc_id, tc_name, dim_id)
            elif check_type == "url_check":
                return self._check_url(test_case, url, tc_id, tc_name, dim_id)
            elif check_type == "element_attribute":
                return self._check_element_attribute(test_case, soup, tc_id, tc_name, dim_id)
            elif check_type == "accessibility":
                return self._check_accessibility(test_case, soup, tc_id, tc_name, dim_id)
            else:
                return CheckOutcome(
                    test_case_id=tc_id, test_case_name=tc_name,
                    dimension_id=dim_id, passed=False, partial=False,
                    notes=f"Tipo de verificación desconocido: {check_type}"
                )
        except Exception as exc:
            logger.warning(f"[CHECK] Error en {tc_id}: {exc}")
            return CheckOutcome(
                test_case_id=tc_id, test_case_name=tc_name,
                dimension_id=dim_id, passed=False,
                notes=f"Error de verificación: {exc}"
            )

    # ── Verificaciones por tipo ────────────────────────────────────────────────

    def _check_element_exists(self, tc, soup, tc_id, tc_name, dim_id) -> CheckOutcome:
        if soup is None:
            return CheckOutcome(tc_id, tc_name, dim_id, passed=False,
                                notes="Página no accesible")
        selectors = tc.get("selectors", [])
        for sel in selectors:
            tag = soup.select_one(sel)
            if tag:
                text = tag.get_text(strip=True)[:80]
                return CheckOutcome(tc_id, tc_name, dim_id, passed=True,
                                    evidence=f"Selector: '{sel}' → '{text}'")
        return CheckOutcome(tc_id, tc_name, dim_id, passed=False,
                            notes=f"Ningún selector encontrado: {selectors}")

    def _check_text_pattern(self, tc, soup, tc_id, tc_name, dim_id) -> CheckOutcome:
        if soup is None:
            return CheckOutcome(tc_id, tc_name, dim_id, passed=False,
                                notes="Página no accesible")
        pattern  = tc.get("pattern", "")
        text     = soup.get_text(separator=" ", strip=True).lower()
        match    = re.search(pattern, text, re.IGNORECASE)
        if match:
            snippet = text[max(0, match.start()-20): match.end()+20].strip()
            return CheckOutcome(tc_id, tc_name, dim_id, passed=True,
                                evidence=f"Patrón encontrado: '...{snippet}...'")
        return CheckOutcome(tc_id, tc_name, dim_id, passed=False,
                            notes=f"Patrón no encontrado: /{pattern}/")

    def _check_response_code(self, tc, code, tc_id, tc_name, dim_id) -> CheckOutcome:
        expected = tc.get("expected_code", 200)
        if code == expected:
            return CheckOutcome(tc_id, tc_name, dim_id, passed=True,
                                evidence=f"HTTP {code} == {expected}")
        # Parcial: código distinto pero la página existe
        partial = (expected == 404 and code in (200, 301, 302))
        return CheckOutcome(tc_id, tc_name, dim_id, passed=False,
                            partial=partial,
                            notes=f"HTTP {code} (esperado {expected})")

    def _check_performance(self, tc, response_time, tc_id, tc_name, dim_id) -> CheckOutcome:
        threshold = tc.get("threshold_seconds", 5.0)
        if response_time < 0:
            return CheckOutcome(tc_id, tc_name, dim_id, passed=False,
                                notes="No se pudo medir el tiempo de respuesta")
        if response_time <= threshold:
            return CheckOutcome(tc_id, tc_name, dim_id, passed=True,
                                evidence=f"{response_time:.2f}s ≤ {threshold}s")
        # Parcial: entre umbral y el doble del umbral
        partial = response_time <= threshold * 2
        return CheckOutcome(tc_id, tc_name, dim_id, passed=False, partial=partial,
                            notes=f"{response_time:.2f}s > {threshold}s (límite)")

    def _check_url(self, tc, url, tc_id, tc_name, dim_id) -> CheckOutcome:
        condition = tc.get("condition", "")
        if condition == "https":
            ok = url.startswith("https://")
            return CheckOutcome(tc_id, tc_name, dim_id, passed=ok,
                                evidence=url if ok else "",
                                notes="" if ok else f"URL no usa HTTPS: {url}")
        return CheckOutcome(tc_id, tc_name, dim_id, passed=False,
                            notes=f"Condición URL desconocida: {condition}")

    def _check_element_attribute(self, tc, soup, tc_id, tc_name, dim_id) -> CheckOutcome:
        if soup is None:
            return CheckOutcome(tc_id, tc_name, dim_id, passed=False,
                                notes="Página no accesible")
        attribute = tc.get("attribute", "")
        selectors = tc.get("selectors", [])
        found_tags = []
        for sel in selectors:
            found_tags.extend(soup.select(sel))

        if not found_tags:
            return CheckOutcome(tc_id, tc_name, dim_id, passed=False,
                                notes="Elementos no encontrados")
        with_attr    = [t for t in found_tags if t.get(attribute)]
        without_attr = len(found_tags) - len(with_attr)
        if without_attr == 0:
            return CheckOutcome(tc_id, tc_name, dim_id, passed=True,
                                evidence=f"{len(with_attr)} elementos con '{attribute}'")
        if with_attr:
            return CheckOutcome(tc_id, tc_name, dim_id, passed=False, partial=True,
                                notes=f"{without_attr} de {len(found_tags)} elementos sin '{attribute}'")
        return CheckOutcome(tc_id, tc_name, dim_id, passed=False,
                            notes=f"Ningún elemento tiene atributo '{attribute}'")

    def _check_accessibility(self, tc, soup, tc_id, tc_name, dim_id) -> CheckOutcome:
        if soup is None:
            return CheckOutcome(tc_id, tc_name, dim_id, passed=False,
                                notes="Página no accesible")
        rule = tc.get("rule", "")
        if rule == "img_alt":
            images       = soup.select("img")
            with_alt     = [i for i in images if i.get("alt")]
            without_alt  = len(images) - len(with_alt)
            if not images:
                return CheckOutcome(tc_id, tc_name, dim_id, passed=False,
                                    partial=True, notes="Sin imágenes en la página")
            if without_alt == 0:
                return CheckOutcome(tc_id, tc_name, dim_id, passed=True,
                                    evidence=f"{len(with_alt)}/{len(images)} imágenes con alt")
            pct = round(len(with_alt) / len(images) * 100)
            partial = pct >= 50
            return CheckOutcome(tc_id, tc_name, dim_id, passed=False, partial=partial,
                                notes=f"{without_alt} imágenes sin alt ({pct}% cumplen)")
        return CheckOutcome(tc_id, tc_name, dim_id, passed=False,
                            notes=f"Regla de accesibilidad desconocida: {rule}")


# ─────────────────────────────────────────────────────────────────────────────
class AuditEngine:
    """
    Orquestador principal del módulo de auditoría QA.
    Coordina el fetcher, el PageChecker y el almacenamiento.
    Invocado desde main.py con el comando 'audit'.
    """

    def __init__(self, db: DatabaseManager, cfg: dict = SCRAPING_CONFIG):
        self.db      = db
        self.cfg     = cfg
        self.fetcher = PageFetcher(cfg)
        self.checker = PageChecker()
        # Reverificación con Playwright (Opción B) — lazy, solo si está
        # habilitada en config.JS_RENDER_CONFIG y solo se instancia al
        # primer uso real (evita requerir el paquete/navegador si no se usa).
        self.js_fetcher       = None
        self._js_no_disponible = False

    def close(self) -> None:
        """Libera recursos (navegador de Playwright, si fue inicializado)."""
        if self.js_fetcher is not None:
            self.js_fetcher.close()

    def _get_js_fetcher(self):
        """
        Construye (una única vez) el fetcher con Playwright, reutilizando el
        MISMO RobotsChecker/RateLimiter/EthicsLogger que usa el fetch
        estático — una sola política ética para todo el sistema.
        Retorna None si la reverificación está deshabilitada o si el
        navegador no está disponible en este entorno.
        """
        if not JS_RENDER_CONFIG.get("enabled", False) or self._js_no_disponible:
            return None
        if self.js_fetcher is not None:
            return self.js_fetcher

        self.js_fetcher = JSFetcher(
            cfg            = JS_RENDER_CONFIG,
            robots_checker = self.fetcher.robots_checker,
            rate_limiter   = self.fetcher.rate_limiter,
            ethics_logger  = self.fetcher.ethics_log,
        )
        return self.js_fetcher

    def _reverificar_con_js(
        self, tc: dict, url: str, outcome_estatico: "CheckOutcome"
    ) -> "CheckOutcome":
        """
        Segunda pasada con navegador real para un indicador clasificado
        "No cumple" (1) por el fetch estático. Ver modules/js_fetcher.py
        para la justificación metodológica completa.
        """
        js_fetcher = self._get_js_fetcher()
        if js_fetcher is None:
            return outcome_estatico

        try:
            soup_js = js_fetcher.get(url)
        except JSFetcherNoDisponible as exc:
            logger.warning(
                f"[PLAYWRIGHT] Navegador no disponible; se desactiva la "
                f"reverificación para el resto de la corrida. Motivo: {exc}"
            )
            self._js_no_disponible = True
            return outcome_estatico

        if soup_js is None:
            # Bloqueado por robots.txt o error de red/navegación: se
            # mantiene el resultado estático sin cambios.
            return outcome_estatico

        outcome_js = self.checker.check(
            test_case     = tc, soup = soup_js, url = url,
            response_code = 200, response_time = 0.0,
        )

        if outcome_js.compliance > outcome_estatico.compliance:
            # Falso negativo confirmado: el elemento existe pero se
            # renderiza vía JavaScript; el fetch estático no podía verlo.
            nota = (
                outcome_js.notes
                + " [Reclasificado: no detectado en HTML estático, "
                  "confirmado tras renderizado con Playwright]"
            ).strip()
            return CheckOutcome(
                test_case_id   = outcome_js.test_case_id,
                test_case_name = outcome_js.test_case_name,
                dimension_id   = outcome_js.dimension_id,
                passed         = outcome_js.passed,
                partial        = outcome_js.partial,
                evidence       = outcome_js.evidence,
                notes          = nota,
                verification_method = "js_rendered",
            )

        # El navegador tampoco lo encuentra: "No cumple" confirmado con
        # mayor grado de confianza metodológica.
        nota = (
            outcome_estatico.notes
            + " [Confirmado tras renderizado con Playwright: tampoco se "
              "detecta con JavaScript ejecutado]"
        ).strip()
        return CheckOutcome(
            test_case_id   = outcome_estatico.test_case_id,
            test_case_name = outcome_estatico.test_case_name,
            dimension_id   = outcome_estatico.dimension_id,
            passed         = outcome_estatico.passed,
            partial        = outcome_estatico.partial,
            evidence       = outcome_estatico.evidence,
            notes          = nota,
            verification_method = "estatico_confirmado_js",
        )

    def run(
        self,
        site_filter      = None,
        dimension_filter = None,
        dry_run          = False,
        sites_override   = None,
    ):
        """
        Ejecuta la auditoría QA.

        Args:
            site_filter      : ID o nombre del sitio. None = todos.
            dimension_filter : str, lista de str, o None (= todas las dims).
                               Ej: 'D3' | ['D1','D3','D8']
            dry_run          : Si True, no realiza requests HTTP reales.
            sites_override   : Lista de sitios ad-hoc (override de config.SITES).

        Returns:
            dict[site_id: list[DimensionSummary]]
        """
        source = sites_override if sites_override is not None else SITES

        sites = [
            s for s in source
            if site_filter is None
            or s["id"].lower() == site_filter.lower()
            or s["name"].lower() == site_filter.lower()
        ]
        if not sites:
            logger.error(f"[AUDIT] Sitio no encontrado: {site_filter}")
            return {}

        # Normalizar dimension_filter a un set o None (todas)
        if dimension_filter is None:
            allowed_dims = None
        elif isinstance(dimension_filter, str):
            allowed_dims = {dimension_filter.upper()}
        else:
            allowed_dims = {d.upper() for d in dimension_filter}

        dims = {
            dim_id: cases
            for dim_id, cases in QA_TEST_CASES.items()
            if allowed_dims is None or dim_id.upper() in allowed_dims
        }

        all_results: dict[str, list[DimensionSummary]] = {}

        for site_cfg in sites:
            self.db.upsert_site(site_cfg)
            logger.info(f"\n[AUDIT] ══ Auditando: {site_cfg['name']} ({site_cfg['id']}) ══")
            summaries = self._audit_site(site_cfg, dims, dry_run)
            all_results[site_cfg["id"]] = summaries

            # Persistir resultados en BD
            audit_records = []
            for dim_summary in summaries:
                for outcome in dim_summary.outcomes:
                    audit_records.append(AuditResult(
                        site_id         = site_cfg["id"],
                        dimension_id    = outcome.dimension_id,
                        test_case_id    = outcome.test_case_id,
                        test_case_name  = outcome.test_case_name,
                        compliance      = outcome.compliance,
                        compliance_label= outcome.compliance_label,
                        evidence        = outcome.evidence,
                        notes           = outcome.notes,
                        verification_method = outcome.verification_method,
                    ))
            if audit_records:
                self.db.insert_audit_results_bulk(audit_records)
                logger.info(f"[AUDIT] {len(audit_records)} resultados persistidos.")

        # Transparencia metodológica: resumen de la reverificación con Playwright
        if JS_RENDER_CONFIG.get("enabled", False):
            reclasificados = sum(
                1 for site_summaries in all_results.values()
                for dim in site_summaries for o in dim.outcomes
                if o.verification_method == "js_rendered"
            )
            confirmados = sum(
                1 for site_summaries in all_results.values()
                for dim in site_summaries for o in dim.outcomes
                if o.verification_method == "estatico_confirmado_js"
            )
            if reclasificados or confirmados:
                logger.info(
                    f"[PLAYWRIGHT] Reverificación completada — "
                    f"{reclasificados} indicador(es) reclasificados (falso "
                    f"negativo confirmado), {confirmados} indicador(es) "
                    f"'No cumple' confirmados tras renderizado JS."
                )

        return all_results

    def _audit_site(
        self,
        site_cfg : dict,
        dims     : dict,
        dry_run  : bool,
    ) -> list[DimensionSummary]:
        """Ejecuta todos los casos de prueba para un sitio."""
        base_url  = site_cfg["base_url"]
        summaries = []

        for dim_id, test_cases in dims.items():
            dim_info = QA_DIMENSIONS.get(dim_id, {})
            summary  = DimensionSummary(
                dimension_id   = dim_id,
                dimension_name = dim_info.get("name", dim_id),
            )

            logger.info(f"[AUDIT] ─ Dimensión {dim_id}: {dim_info.get('name', '')}")

            for tc in test_cases:
                outcome = self._run_test_case(tc, base_url, dry_run)
                summary.outcomes.append(outcome)
                icon = "✓" if outcome.passed else ("~" if outcome.partial else "✗")
                logger.info(
                    f"  [{icon}] {tc['id']} — {tc['name']}: "
                    f"{outcome.compliance_label}"
                )
                if outcome.evidence:
                    logger.debug(f"      Evidencia: {outcome.evidence}")
                if outcome.notes:
                    logger.debug(f"      Notas: {outcome.notes}")

            logger.info(
                f"  → Promedio D{dim_id[-1]}: {summary.avg_score}/3 | "
                f"Tasa aprobación: {summary.pass_rate}%"
            )
            summaries.append(summary)

        return summaries

    def _run_test_case(self, tc: dict, base_url: str, dry_run: bool) -> CheckOutcome:
        """Obtiene la página necesaria y ejecuta la verificación del caso de prueba."""
        url_path      = tc.get("url_path")
        check_type    = tc.get("check_type", "")
        tc_id         = tc["id"]
        dim_id        = tc_id.split(".")[0]

        # En dry_run, retorna resultado neutro sin hacer requests
        if dry_run:
            return CheckOutcome(
                test_case_id   = tc_id,
                test_case_name = tc["name"],
                dimension_id   = dim_id,
                passed         = False,
                partial        = True,
                notes          = "Modo dry-run: sin verificación real",
            )

        # Para casos que no tienen url_path definida, usar la raíz
        if url_path is None:
            url_path = "/"

        url           = urljoin(base_url, url_path)
        soup          = None
        response_code = 0
        response_time = 0.0

        if check_type == "performance":
            response_time = self.fetcher.measure_response_time(url)
        elif check_type in ("response_code",):
            resp = self.fetcher.get_response(url)
            if resp is not None:
                response_code = resp.status_code
        else:
            t0   = time.monotonic()
            soup = self.fetcher.get(url)
            response_time = time.monotonic() - t0
            response_code = 200 if soup else 0

        outcome = self.checker.check(
            test_case     = tc,
            soup          = soup,
            url           = url,
            response_code = response_code,
            response_time = response_time,
        )

        # Opción B: reverificación con navegador real, EXCLUSIVA para
        # indicadores "No cumple" en check_types que dependen del HTML/DOM.
        reverificables = set(JS_RENDER_CONFIG.get("check_types_reverificables", []))
        if check_type in reverificables and outcome.compliance == 1:
            outcome = self._reverificar_con_js(tc, url, outcome)

        return outcome
