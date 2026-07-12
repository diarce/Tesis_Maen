"""
app.py — Sistema de Auditoría de Comercio Electrónico Mayorista
===============================================================
Interfaz Streamlit con diseño de dos columnas:
  - Columna izquierda : actividades agrupadas por etapa metodológica
  - Columna derecha   : resultados en presentación académica

Ejecución:  streamlit run app.py
"""

import json
import logging
import sys
import traceback
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# ── Configuración de página ────────────────────────────────────────────────────
st.set_page_config(
    page_title = "Auditoria Mayorista — Herramienta Académica",
    page_icon  = "",
    layout     = "wide",
    initial_sidebar_state = "collapsed",
)

# ── Estilos: presentación académica ───────────────────────────────────────────
st.markdown("""
<style>
/* Ocultar sidebar y botón de colapso */
section[data-testid="stSidebar"]        { display: none; }
[data-testid="collapsedControl"]        { display: none; }

/* Tipografía base */
html, body, [class*="css"] {
    font-family: "Georgia", "Times New Roman", serif;
    font-size: 14px;
    color: #1a1a1a;
}

/* Contenedor principal */
.block-container {
    padding-top: 2.4rem !important;
    padding-bottom: 2rem !important;
    max-width: 1280px;
}

/* Encabezado de página */
.pag-titulo {
    border-bottom: 2px solid #1a1a2e;
    padding-bottom: 8px;
    margin-bottom: 4px;
    font-size: 18px;
    font-weight: bold;
    letter-spacing: .01em;
}
.pag-subtitulo {
    font-size: 12px;
    color: #555;
    font-style: italic;
    margin-bottom: 16px;
}

/* Encabezados de grupo en columna izquierda */
.grupo {
    font-size: 11px;
    font-weight: bold;
    letter-spacing: .09em;
    text-transform: uppercase;
    color: #1a1a2e;
    border-bottom: 1px solid #1a1a2e;
    padding-bottom: 3px;
    margin: 18px 0 10px 0;
}

/* Línea divisoria de sección en columna derecha */
.res-seccion {
    font-size: 13px;
    font-weight: bold;
    border-bottom: 1px solid #888;
    padding-bottom: 3px;
    margin: 0 0 10px 0;
    color: #1a1a2e;
}

/* Estado del proceso */
.estado-ok  { color: #155724; font-size: 12px; font-family: monospace; }
.estado-pen { color: #856404; font-size: 12px; font-family: monospace; }

/* Empresa en lista */
.empresa-item {
    font-size: 12px;
    padding: 4px 0;
    border-bottom: 1px dotted #ccc;
    line-height: 1.4;
}
.empresa-url { color: #555; font-style: italic; font-size: 11px; }

/* Aviso de anonimización */
.aviso-anon {
    font-size: 11px;
    font-style: italic;
    color: #555;
    border-left: 3px solid #888;
    padding-left: 8px;
    margin: 8px 0;
}

/* Log monoespaciado */
.log-pre {
    font-family: monospace;
    font-size: 11px;
    background: #f5f5f5;
    border: 1px solid #ccc;
    padding: 10px;
    max-height: 340px;
    overflow-y: auto;
    white-space: pre-wrap;
    line-height: 1.5;
}

/* Nota metodológica */
.nota-met {
    font-size: 11px;
    color: #444;
    background: #f9f9f9;
    border: 1px solid #ddd;
    padding: 8px 10px;
    margin-top: 10px;
}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# CARGA DE DATOS (cacheada)
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data
def load_provincias() -> dict:
    with open(ROOT / "data" / "provincias_localidades.json", encoding="utf-8") as f:
        return json.load(f)

@st.cache_data
def load_empresas_base() -> list:
    with open(ROOT / "data" / "empresas_mayoristas.json", encoding="utf-8") as f:
        return json.load(f)

PROVINCIAS    = load_provincias()
EMPRESAS_BASE = load_empresas_base()

DIMS_LABEL = {
    "D1": "D1 · Estructura y navegación",
    "D2": "D2 · Registro y autenticación",
    "D3": "D3 · Ficha de producto",
    "D4": "D4 · Carrito de compras",
    "D5": "D5 · Proceso de checkout",
    "D6": "D6 · Medios de pago",
    "D7": "D7 · Comunicación de errores",
    "D8": "D8 · Desempeño técnico",
}

COMPLIANCE_TEXTO = {3: "Pleno", 2: "Parcial", 1: "No cumple", 0: "N/A"}


# ══════════════════════════════════════════════════════════════════════════════
# ESTADO DE SESIÓN
# ══════════════════════════════════════════════════════════════════════════════

def init_state():
    defaults = {
        "companies"     : [],
        "audit_done"    : False,
        "scrape_done"   : False,
        "audit_log"     : [],
        "selected_dims" : list(DIMS_LABEL.keys()),
        "rate_limit"    : 3.0,
        "max_products"  : 50,
        "provincia_sel" : "Misiones",   # Contexto del estudio: NEA — Misiones
        "panel"         : "qa",
        "localidades_default": ["Posadas", "Garupá", "Itaembé Guazú"],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()


# ══════════════════════════════════════════════════════════════════════════════
# LOG HANDLER
# ══════════════════════════════════════════════════════════════════════════════

class StreamlitLogHandler(logging.Handler):
    """Redirige logging estándar de Python al log de sesión de Streamlit."""
    def emit(self, record):
        icons = {logging.DEBUG: "·", logging.INFO: "ℹ",
                 logging.WARNING: "⚠", logging.ERROR: "✗"}
        ts   = datetime.now().strftime("%H:%M:%S")
        icon = icons.get(record.levelno, "·")
        st.session_state.audit_log.append(f"[{ts}] {icon} {self.format(record)}")


def install_log_handler():
    root = logging.getLogger()
    root.handlers = [h for h in root.handlers
                     if not isinstance(h, StreamlitLogHandler)]
    handler = StreamlitLogHandler()
    handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def add_log(msg: str, level: str = "INFO"):
    icons = {"INFO": "ℹ", "OK": "✓", "WARN": "⚠", "ERR": "✗"}
    ts    = datetime.now().strftime("%H:%M:%S")
    st.session_state.audit_log.append(
        f"[{ts}] {icons.get(level, '·')} {msg}"
    )
    if len(st.session_state.audit_log) > 300:
        st.session_state.audit_log = st.session_state.audit_log[-300:]


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS DE CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════════════════════

def build_runtime_sites() -> list:
    """Construye la lista de sitios a partir de las empresas seleccionadas."""
    return [
        {
            "id"       : c["id"],
            "name"     : c["name"],
            "base_url" : c["base_url"],
            "dynamic"  : c.get("dynamic", False),
            "platform" : c.get("platform", "Custom"),
            "region"   : c.get("region", ""),
            "notes"    : c.get("descripcion", ""),
            "selectors": c.get("selectors", {}),
        }
        for c in st.session_state.companies
        if c.get("base_url", "").startswith("http")
    ]


def inject_config(sites: list, cfg: dict):
    """Actualiza config.SITES y SCRAPING_CONFIG en memoria."""
    import config
    config.SITES.clear()
    config.SITES.extend(sites)
    config.SCRAPING_CONFIG["rate_limit_seconds"]    = cfg["rate_limit"]
    config.SCRAPING_CONFIG["max_products_per_site"] = cfg["max_products"]


def write_runtime_json(sites: list) -> Path:
    """Persiste la configuración activa en runtime_sites.json."""
    out = ROOT / "runtime_sites.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(sites, f, ensure_ascii=False, indent=2)
    return out


def preview_config_py(sites: list, cfg: dict) -> str:
    """Genera el texto Python equivalente de config.SITES."""
    lines = [
        "# Configuracion generada por AuditMayorista",
        "# " + datetime.now().isoformat(), "",
        "SITES = [",
    ]
    for s in sites:
        sel = json.dumps(s.get("selectors", {}), ensure_ascii=False)
        lines += [
            "    {",
            "        'id'       : " + repr(str(s["id"]))              + ",",
            "        'name'     : " + repr(str(s["name"]))            + ",",
            "        'base_url' : " + repr(str(s["base_url"]))        + ",",
            "        'dynamic'  : " + str(bool(s.get("dynamic", False))) + ",",
            "        'platform' : " + repr(str(s.get("platform", "")))+ ",",
            "        'region'   : " + repr(str(s.get("region", "")))  + ",",
            "        'selectors': " + sel                              + ",",
            "    },",
        ]
    lines += ["]", "", "# Parametros de scraping",
              "SCRAPING_CONFIG['rate_limit_seconds']    = " + str(cfg["rate_limit"]),
              "SCRAPING_CONFIG['max_products_per_site'] = " + str(cfg["max_products"])]
    return chr(10).join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# ACCIONES PRINCIPALES
# ══════════════════════════════════════════════════════════════════════════════

def _remove_company(idx: int):
    st.session_state.companies.pop(idx)
    st.rerun()


def _save_config():
    sites = build_runtime_sites()
    if not sites:
        st.error("No hay empresas con URL válida configuradas.")
        return
    out = write_runtime_json(sites)
    inject_config(sites, {
        "rate_limit"  : st.session_state.rate_limit,
        "max_products": st.session_state.max_products,
    })
    add_log(f"Configuración guardada: {len(sites)} sitio(s) → {out.name}", "OK")


def _run_demo():
    """
    Modo demostración: genera datos simulados representativos del mercado
    mayorista de Misiones (Posadas, Garupá, Itaembé Guazú) sin requerir
    conexión a internet ni acceso a sitios externos.
    Uso recomendado cuando los sitios reales bloquean el acceso automatizado.
    """
    st.session_state.audit_log = []
    install_log_handler()
    add_log("Iniciando modo demostración — datos simulados del mercado mayorista de Misiones.", "INFO")
    try:
        from modules.storage import DatabaseManager
        from modules.demo    import run_demo, _SIMULATED_SITES
        from config          import DB_PATH

        db = DatabaseManager(DB_PATH)
        # Limpiar solo los sitios del demo (MIS*), preservar cualquier dato real
        for s in _SIMULATED_SITES:
            db.clear_site_results(s["id"])
        add_log(f"Generando datos para {len(_SIMULATED_SITES)} plataformas simuladas.", "INFO")

        run_demo(db)

        # Verificar resultados generados
        productos = db.get_products()
        resultados= db.get_audit_results()
        add_log(f"Demo completado: {len(resultados)} resultados QA, {len(productos)} productos.", "OK")
        add_log("Los datos simulan el proceso de compra en plataformas mayoristas de consumo masivo.", "OK")

        st.session_state.audit_done  = True
        st.session_state.scrape_done = True
        st.session_state.panel       = "qa"
    except Exception as exc:
        add_log(f"Error en demo: {exc}", "ERR")
        add_log(traceback.format_exc(), "ERR")
        st.session_state.panel = "log"
    st.rerun()


def _run_audit():
    sites = build_runtime_sites()
    if not sites:
        st.error("Agregue al menos una empresa con URL válida.")
        return
    st.session_state.audit_log = []
    install_log_handler()
    inject_config(sites, {
        "rate_limit"  : st.session_state.rate_limit,
        "max_products": st.session_state.max_products,
    })
    add_log(f"Iniciando auditoría QA — {len(sites)} sitio(s).", "INFO")
    try:
        from modules.storage import DatabaseManager
        from modules.auditor import AuditEngine
        from config          import DB_PATH
        db = DatabaseManager(DB_PATH)
        # Purgar resultados previos de cada sitio para evitar duplicación
        for s in sites:
            db.upsert_site(s)
            db.clear_site_results(s["id"])
            add_log(f"Datos previos eliminados: {s['id']}", "INFO")
        AuditEngine(db).run(
            dimension_filter = st.session_state.get("selected_dims") or None,
            dry_run          = False,
            sites_override   = sites,
        )
        st.session_state.audit_done = True
        st.session_state.panel      = "qa"
        add_log("Auditoría QA finalizada.", "OK")
    except Exception as exc:
        add_log(f"Error: {exc}", "ERR")
        add_log(traceback.format_exc(), "ERR")
    st.rerun()


def _run_scraping():
    sites = build_runtime_sites()
    if not sites:
        st.error("Agregue al menos una empresa con URL válida.")
        return
    st.session_state.audit_log = []
    install_log_handler()
    inject_config(sites, {
        "rate_limit"  : st.session_state.rate_limit,
        "max_products": st.session_state.max_products,
    })
    add_log(f"Iniciando scraping — {len(sites)} sitio(s).", "INFO")
    try:
        from modules.storage import DatabaseManager
        from modules.scraper import ScrapingEngine
        from config          import DB_PATH

        db       = DatabaseManager(DB_PATH)
        site_ids = {s["id"] for s in sites}

        # Registrar sitios sin limpiar aún (los datos previos se conservan
        # hasta confirmar que el nuevo scraping produjo resultados)
        for s in sites:
            db.upsert_site(s)
            add_log(f"Sitio registrado: {s['id']} — {s['name']}", "INFO")

        ScrapingEngine(db).run(
            snapshot_number = 1,
            sites_override  = sites,
        )

        # Verificar si el scraping produjo productos
        todos_prods = db.get_products()
        nuevos = [p for p in todos_prods if p["site_id"] in site_ids]

        if nuevos:
            # Hay resultados: ahora sí limpiar duplicados y conservar solo los nuevos
            for s in sites:
                db.clear_site_results(s["id"])
            ScrapingEngine(db).run(snapshot_number=1, sites_override=sites)
            st.session_state.scrape_done = True
            st.session_state.panel       = "catalogo"
            add_log(f"Scraping completado: {len(nuevos)} productos obtenidos.", "OK")
        else:
            add_log("El scraping no obtuvo productos.", "WARN")
            add_log("Causas probables:", "WARN")
            for s in sites:
                from modules.ethics import RobotsChecker
                from config         import SCRAPING_CONFIG
                rc      = RobotsChecker(SCRAPING_CONFIG["user_agent"])
                allowed = rc.is_allowed(s["base_url"] + "/")
                estado  = "acceso PERMITIDO por robots.txt" if allowed else "BLOQUEADO por robots.txt"
                add_log(f"  {s['id']} ({s['name']}): {estado}", "WARN")
            add_log("Sugerencia: ejecute el modo Demo para datos representativos.", "WARN")
            st.session_state.panel = "log"

    except Exception as exc:
        add_log(f"Error: {exc}", "ERR")
        add_log(traceback.format_exc(), "ERR")
        st.session_state.panel = "log"
    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# COLUMNA IZQUIERDA — ACTIVIDADES
# ══════════════════════════════════════════════════════════════════════════════

def _grupo_muestra():
    """Grupo 1: Selección de la muestra de análisis."""
    st.markdown('<div class="grupo">1. Selección de la muestra</div>',
                unsafe_allow_html=True)

    # ── Zona geográfica ──────────────────────────────────────────────────────
    provincia = st.selectbox(
        "Provincia",
        options = sorted(PROVINCIAS.keys()),
        index   = sorted(PROVINCIAS.keys()).index(st.session_state.provincia_sel),
        key     = "sel_provincia",
    )
    st.session_state.provincia_sel = provincia

    localidades = PROVINCIAS.get(provincia, [])
    locs_default = [
        loc for loc in st.session_state.get("localidades_default", [])
        if loc in localidades
    ] or ([localidades[0]] if localidades else [])

    st.multiselect(
        "Localidad/es del estudio",
        options     = localidades,
        default     = locs_default,
        placeholder = "Seleccionar…",
        key         = "sel_localidades",
    )

    # ── Modo de carga ─────────────────────────────────────────────────────────
    modo = st.radio(
        "Modo de incorporación",
        ["Desde base de datos", "Ingreso manual"],
        horizontal       = True,
        label_visibility = "visible",
        key              = "modo_empresa",
    )

    if modo == "Desde base de datos":
        _empresas_base(provincia)
    else:
        _empresa_manual(provincia)

    # ── Lista de empresas en la muestra ──────────────────────────────────────
    n = len(st.session_state.companies)
    if n:
        st.caption(f"Muestra actual: {n} empresa(s)")
        for i, c in enumerate(st.session_state.companies):
            col_n, col_b = st.columns([5, 1])
            with col_n:
                st.markdown(
                    f'<div class="empresa-item"><b>{c["name"]}</b>'
                    f'<br><span class="empresa-url">{c["base_url"]}</span>'
                    f'<br><span style="font-size:11px;color:#777">'
                    f'{c.get("platform","—")} · {c.get("region","—")}</span></div>',
                    unsafe_allow_html=True,
                )
            with col_b:
                if st.button("X", key=f"rm_{i}", help="Eliminar"):
                    _remove_company(i)
    else:
        st.caption("Sin empresas en la muestra.")


def _empresas_base(provincia: str):
    """
    Lista de empresas filtradas por provincia y, cuando el dato existe,
    por localidad. Las empresas sin dato de localidad se incluyen por
    cobertura provincial (ausencia de dato no implica exclusión).

    La/s localidad/es seleccionada/s se registran como contexto
    geográfico del estudio en el campo region de cada sitio auditado.
    """
    localidades_sel = st.session_state.get("sel_localidades", [])

    # Filtro 1: cobertura provincial
    por_provincia = [
        e for e in EMPRESAS_BASE
        if "todas" in e.get("provincias", [])
        or provincia in e.get("provincias", [])
    ]

    # Filtro 2: localidad — solo cuando la empresa tiene el dato y hay selección
    if localidades_sel:
        disponibles = []
        for e in por_provincia:
            locs = e.get("localidades", [])
            if not locs:
                # Sin dato de localidad: se incluye (cobertura provincial asumida)
                disponibles.append((e, False))
            elif any(loc in locs for loc in localidades_sel):
                # Con dato confirmado para alguna localidad seleccionada
                disponibles.append((e, True))
            # Si tiene dato y ninguna localidad coincide: se excluye
    else:
        disponibles = [(e, False) for e in por_provincia]

    if not disponibles:
        st.caption(f"Sin empresas con cobertura en {provincia}.")
        return

    if localidades_sel:
        locs_str = ", ".join(localidades_sel[:3])
        st.markdown(
            f'<div class="nota-met">Empresas con cobertura en <b>{provincia}</b>. '
            f'Los registros marcados con (*) no tienen dato de localidad en la base '
            f'y se incluyen por cobertura provincial. La/s localidad/es '
            f'<i>{locs_str}</i> se registran como contexto geográfico del estudio.</div>',
            unsafe_allow_html=True,
        )

    for emp, confirmada in disponibles:
        ya     = any(c["id"] == emp["id"] for c in st.session_state.companies)
        sufijo = "" if confirmada else (" *" if localidades_sel else "")
        col_e, col_b = st.columns([4, 1])
        with col_e:
            st.markdown(
                f'<span style="font-size:12px"><b>{emp["name"]}{sufijo}</b>'
                f'<br><span class="empresa-url">{emp["base_url"]}</span>'
                f'<br><span style="font-size:11px;color:#777">'
                f'{emp.get("tipo","—")} · {emp.get("rubro","")}</span></span>',
                unsafe_allow_html=True,
            )
        with col_b:
            if st.button("Agregar" if not ya else "(agregado)",
                         key      = f"add_{emp['id']}",
                         disabled = ya,
                         help     = "Agregar a la muestra"):
                c = dict(emp)
                c["region"] = provincia + (
                    f" · {chr(44).join(localidades_sel[:3])}" if localidades_sel else ""
                )
                st.session_state.companies.append(c)
                st.rerun()


def _empresa_manual(provincia: str):
    """Formulario de ingreso manual de empresa."""
    with st.form("form_manual", clear_on_submit=True):
        name     = st.text_input("Nombre *",    placeholder="Distribuidora XYZ S.A.")
        base_url = st.text_input("URL del sitio *", placeholder="https://www.empresa.com.ar")
        platform = st.selectbox("Plataforma",
                                ["VTEX","Magento","WooCommerce","Shopify","Custom","Desconocida"])
        tipo     = st.selectbox("Alcance", ["Nacional", "Regional", "Local"])
        dynamic  = st.checkbox("Sitio con renderizado JavaScript",
                               help="Activar si el catálogo no aparece sin JS.")
        ok = st.form_submit_button("Agregar empresa")

    if ok:
        if not name or not base_url:
            st.error("Nombre y URL son obligatorios.")
        elif not base_url.startswith("http"):
            st.error("La URL debe comenzar con http:// o https://")
        else:
            nuevo_id = f"USR{len(st.session_state.companies)+1:03d}"
            locs     = st.session_state.get("sel_localidades", [])
            st.session_state.companies.append({
                "id"         : nuevo_id,
                "name"       : name,
                "base_url"   : base_url.rstrip("/"),
                "platform"   : platform,
                "tipo"       : tipo,
                "dynamic"    : dynamic,
                "region"     : f"{provincia} · {', '.join(locs[:2])}",
                "descripcion": f"Empresa ingresada manualmente ({tipo})",
                "provincias" : [provincia],
                "selectors"  : {
                    "product_card"    : ".product-item, [class*='product']",
                    "product_name"    : "h2, h3, .product-name",
                    "product_price"   : ".price, [class*='price'], [itemprop='price']",
                    "product_image"   : "img",
                    "stock_indicator" : "[class*='stock'], [class*='avail']",
                    "search_input"    : "input[type='search'], input[name='q']",
                    "add_to_cart"     : "button[class*='cart'], button[class*='add']",
                    "breadcrumb"      : ".breadcrumb",
                    "category_links"  : "nav a",
                    "cart_count"      : "[class*='cart']",
                },
            })
            st.rerun()


def _grupo_parametros():
    """Grupo 2: Parámetros metodológicos del relevamiento."""
    st.markdown('<div class="grupo">2. Parametros metodológicos</div>',
                unsafe_allow_html=True)

    st.session_state.selected_dims = st.multiselect(
        "Dimensiones QA a evaluar",
        options      = list(DIMS_LABEL.keys()),
        default      = st.session_state.selected_dims,
        format_func  = lambda d: DIMS_LABEL[d],
    )

    st.session_state.rate_limit = st.slider(
        "Intervalo entre solicitudes (segundos)",
        min_value = 1.0, max_value = 10.0,
        value     = st.session_state.rate_limit,
        step      = 0.5,
        help      = "Pausa mínima entre requests. Valor recomendado: ≥ 3 s.",
    )

    st.session_state.max_products = st.slider(
        "Máx. productos por sitio (scraping)",
        min_value = 10, max_value = 200,
        value     = st.session_state.max_products,
        step      = 10,
    )

    st.markdown(
        '<div class="nota-met">'
        'El sistema respeta el archivo <code>robots.txt</code> de cada sitio. '
        'Si un sitio bloquea el acceso automatizado, el scraping no extraerá datos. '
        'En ese caso, utilice el <b>modo Demo</b> para trabajar con datos '
        'representativos del mercado mayorista de Misiones sin requerir acceso externo.'
        '</div>',
        unsafe_allow_html=True,
    )


def _grupo_ejecucion():
    """Grupo 3: Ejecución del proceso de relevamiento."""
    st.markdown('<div class="grupo">3. Ejecucion</div>',
                unsafe_allow_html=True)

    n    = len(st.session_state.companies)
    ok   = n > 0
    nota = f"{n} empresa(s) en la muestra." if ok else "Agregue empresas para continuar."
    st.caption(nota)

    # Guardar configuración
    if st.button("Guardar configuración", use_container_width=True, disabled=not ok):
        _save_config()
        st.success("Configuración guardada.")

    st.write("")

    # Auditoría QA
    if st.button("Iniciar auditoría QA",
                 type             = "primary",
                 use_container_width = True,
                 disabled         = not ok):
        _run_audit()

    # Scraping
    if st.button("Iniciar scraping de catálogo",
                 use_container_width = True,
                 disabled = not ok):
        _run_scraping()

    # Demo
    if st.button("Ejecutar demo (sin internet)",
                 use_container_width = True):
        _run_demo()

    # Estado
    st.write("")
    qa_icon  = "✓" if st.session_state.audit_done  else "–"
    sc_icon  = "✓" if st.session_state.scrape_done else "–"
    qa_cls   = "estado-ok" if st.session_state.audit_done  else "estado-pen"
    sc_cls   = "estado-ok" if st.session_state.scrape_done else "estado-pen"
    st.markdown(
        f'<span class="{qa_cls}">{qa_icon} Auditoría QA</span>&nbsp;&nbsp;'
        f'<span class="{sc_cls}">{sc_icon} Scraping</span>',
        unsafe_allow_html=True,
    )

    # Descarga de configuración
    if ok:
        sites = build_runtime_sites()
        cfg   = {"rate_limit": st.session_state.rate_limit,
                 "max_products": st.session_state.max_products}
        st.download_button(
            "Descargar configuracion (config.py)",
            data      = preview_config_py(sites, cfg),
            file_name = "runtime_config.py",
            mime      = "text/plain",
            use_container_width = True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# COLUMNA DERECHA — RESULTADOS
# ══════════════════════════════════════════════════════════════════════════════

def _anon_map(sites: list) -> dict:
    """Mapeo determinístico site_id → 'Sitio Auditado N' (anonimización)."""
    from modules.reporter import build_anon_map
    return build_anon_map(sites)


def _panel_bienvenida():
    st.markdown('<div class="res-seccion">Estado del relevamiento</div>',
                unsafe_allow_html=True)
    st.markdown("""
Seleccione las empresas en el panel izquierdo y ejecute el proceso para
visualizar los resultados aquí.

**Flujo de trabajo:**
1. Defina la muestra geográfica y empresarial (Grupo 1)
2. Configure los parámetros metodológicos (Grupo 2)
3. Inicie la auditoría QA y/o el scraping de catálogo (Grupo 3)
4. Los resultados se presentarán en las secciones de esta columna

El modo *demo* permite verificar el funcionamiento completo del sistema
con datos simulados, sin requerir conexión a internet.
""")


def _panel_qa():
    """Resultados de auditoría QA — tabla académica."""
    st.markdown('<div class="res-seccion">Resultados de la auditoría QA</div>',
                unsafe_allow_html=True)

    try:
        from modules.storage import DatabaseManager
        from config          import DB_PATH, QA_DIMENSIONS
        db      = DatabaseManager(DB_PATH)
        sites   = db.get_sites()
        scores  = db.get_dimension_scores()
        results = db.get_audit_results()
    except Exception as exc:
        st.error(f"Error al acceder a los datos: {exc}")
        return

    if not scores:
        st.info("Sin datos de auditoría. Ejecute el proceso.")
        return

    anon    = _anon_map(sites)
    dim_ids = sorted(QA_DIMENSIONS.keys())

    # ── Anonimización ─────────────────────────────────────────────────────────
    usar_anon = st.toggle(
        "Presentación anónima (modo publicación)",
        value = True,
        help  = "Reemplaza los nombres reales por identificadores genéricos.",
    )
    site_map = anon if usar_anon else {s["id"]: s["name"] for s in sites}

    if usar_anon:
        st.markdown(
            '<div class="aviso-anon">Los nombres de las organizaciones han sido '
            'sustituidos por identificadores secuenciales conforme a los principios '
            'éticos de la investigación académica.</div>',
            unsafe_allow_html=True,
        )

    # ── Sitios a mostrar ─────────────────────────────────────────────────────
    # Si hay empresas en sesión Y alguna coincide con la BD → mostrar esas.
    # En cualquier otro caso (demo, sin selección, IDs distintos) → mostrar todas.
    company_ids   = {c["id"] for c in st.session_state.companies}
    ids_cruzados  = {s["id"] for s in sites if s["id"] in company_ids}
    ids_activos   = ids_cruzados if ids_cruzados else {s["id"] for s in sites}
    sites_activos = [s for s in sites if s["id"] in ids_activos]

    anon     = _anon_map(sites_activos)
    site_map = anon if usar_anon else {s["id"]: s["name"] for s in sites_activos}

    # ── Matriz de cumplimiento ─────────────────────────────────────────────────
    by_site: dict[str, dict] = {}
    for row in scores:
        if row["site_id"] in ids_activos:          # solo sitios del estudio activo
            by_site.setdefault(row["site_id"], {})[row["dimension_id"]] = row

    if not by_site:
        st.info("Sin datos de auditoría. Ejecute el proceso primero.")
        return

    matriz = []
    for sid, dims in by_site.items():
        fila  = {"Sitio": site_map.get(sid, sid)}
        vals  = []
        for d in dim_ids:
            if d in dims:
                v = round(dims[d]["avg_compliance"], 2)
                fila[d] = v
                vals.append(v)
            else:
                fila[d] = None
        fila["Índice"] = round(sum(vals) / len(vals), 2) if vals else 0.0
        matriz.append(fila)

    df_m = pd.DataFrame(matriz)

    def _estilo_score(v):
        """Escala de grises académica: sin colores vivos."""
        if pd.isna(v) or v == 0:
            return "color: #888;"
        if v >= 2.5:
            return "background-color: #e8e8e8; font-weight: bold;"
        if v >= 1.5:
            return "background-color: #f2f2f2;"
        return "color: #555; font-style: italic;"

    cols_num = [c for c in df_m.columns if c not in ("Sitio",)]
    styled = (
        df_m.style
        .map(_estilo_score, subset=cols_num)
        .format({c: "{:.2f}" for c in cols_num}, na_rep="—")
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)

    st.markdown(
        '<div class="nota-met">'
        'Escala de cumplimiento: 3 = Pleno · 2 = Parcial · 1 = No cumple · 0 = N/A. '
        'El Índice es el promedio aritmético de los scores de todas las dimensiones '
        'evaluadas para el sitio. Los casos con valor 0 se excluyen del cálculo.'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── Detalle por dimensión ─────────────────────────────────────────────────
    if sites:
        st.write("")
        st.markdown('<div class="res-seccion">Detalle por dimensión</div>',
                    unsafe_allow_html=True)

        site_sel = st.selectbox(
            "Seleccionar sitio:",
            options      = [s["id"] for s in sites],
            format_func  = lambda sid: site_map.get(sid, sid),
        )

        by_site_dim: dict[str, list] = {}
        for r in results:
            if r["site_id"] == site_sel:
                by_site_dim.setdefault(r["dimension_id"], []).append(r)

        for did in sorted(by_site_dim.keys()):
            casos   = by_site_dim[did]
            avg_d   = round(
                sum(c["compliance"] for c in casos if c["compliance"] > 0)
                / max(1, sum(1 for c in casos if c["compliance"] > 0)), 2
            )
            from config import QA_DIMENSIONS
            dim_nombre = QA_DIMENSIONS.get(did, {}).get("name", did)

            with st.expander(
                f"{did} — {dim_nombre}   [promedio: {avg_d:.2f}/3.00]",
                expanded=False,
            ):
                filas = [{
                    "ID"         : c["test_case_id"],
                    "Caso de prueba": c["test_case_name"],
                    "Resultado"  : COMPLIANCE_TEXTO.get(c["compliance"], "—"),
                    "Valor"      : c["compliance"],
                    "Observación": (c.get("evidence") or c.get("notes") or "")[:70],
                } for c in casos]

                df_d = pd.DataFrame(filas)

                def _estilo_res(v):
                    if v == "Pleno":     return "font-weight: bold;"
                    if v == "No cumple": return "color: #555; font-style: italic;"
                    return ""

                st.dataframe(
                    df_d.style.map(_estilo_res, subset=["Resultado"]),
                    hide_index        = True,
                    use_container_width = True,
                )


def _panel_catalogo():
    """Datos de catálogo extraídos por scraping."""
    st.markdown('<div class="res-seccion">Datos del catálogo (scraping)</div>',
                unsafe_allow_html=True)

    try:
        from modules.storage import DatabaseManager
        from config          import DB_PATH
        db       = DatabaseManager(DB_PATH)
        sites    = db.get_sites()
        products = db.get_products()
        history  = db.get_price_history()
    except Exception as exc:
        st.error(str(exc))
        return

    if not products:
        st.info("Sin datos de productos. Ejecute el scraping.")
        return

    # Sitios a mostrar: cruce con sesión; si no hay cruce, mostrar todos
    company_ids   = {c["id"] for c in st.session_state.companies}
    ids_cruzados  = {s["id"] for s in sites if s["id"] in company_ids}
    ids_activos   = ids_cruzados if ids_cruzados else {s["id"] for s in sites}
    sites_activos = [s for s in sites if s["id"] in ids_activos]

    anon     = _anon_map(sites_activos)
    site_map = anon   # catálogo siempre anonimizado

    df = pd.DataFrame(products)
    df = df[df["site_id"].isin(ids_activos)].copy()

    if df.empty:
        st.warning(
            "No se encontraron productos para los sitios seleccionados.\n\n"
            "**Causa más frecuente:** los sitios configurados bloquean el acceso "
            "automatizado mediante `robots.txt`. El sistema respeta esta directiva "
            "como parte del protocolo ético de scraping.\n\n"
            "**Alternativas:**\n"
            "- Ejecute el **modo Demo** para trabajar con datos representativos "
            "del mercado mayorista de Misiones (sin acceso a internet).\n"
            "- Agregue sitios que permitan acceso automatizado o solicite "
            "autorización explícita a las organizaciones a relevar.\n"
            "- Revise el log de ejecución para ver qué sitios fueron bloqueados."
        )
        if st.session_state.audit_log:
            with st.expander("Ver log de la última ejecución"):
                st.code("\n".join(st.session_state.audit_log[-40:]), language=None)
        return

    df["Sitio"]     = df["site_id"].map(site_map)
    df["Descuento"] = df["has_discount"].apply(lambda x: "Sí" if x else "No")

    # ── Resumen ───────────────────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    prices = df[df["price_unit"] > 0]["price_unit"]
    col1.metric("Total productos",  len(df))
    col2.metric("Categorías",       df["category"].nunique())
    col3.metric("Con descuento",    int(df["has_discount"].sum()))
    col4.metric("Precio promedio",  f"$ {prices.mean():,.0f}" if len(prices) else "—")

    # ── Filtros ───────────────────────────────────────────────────────────────
    cf1, cf2 = st.columns(2)
    with cf1:
        sitios_f = st.multiselect(
            "Filtrar por sitio",
            options      = df["site_id"].unique().tolist(),
            format_func  = lambda x: site_map.get(x, x),
        )
    with cf2:
        cats_f = st.multiselect(
            "Filtrar por categoría",
            options = sorted(df["category"].dropna().unique().tolist()),
        )

    dv = df.copy()
    if sitios_f: dv = dv[dv["site_id"].isin(sitios_f)]
    if cats_f:   dv = dv[dv["category"].isin(cats_f)]

    st.dataframe(
        dv[["Sitio", "name", "brand", "category",
            "price_unit", "unit_measure", "stock_status", "Descuento"]]
        .rename(columns={
            "name": "Producto", "brand": "Marca", "category": "Categoría",
            "price_unit": "Precio unit. ($)", "unit_measure": "Unidad",
            "stock_status": "Stock",
        }),
        use_container_width = True,
        hide_index          = True,
        height              = 320,
    )
    st.caption(f"Mostrando {len(dv):,} de {len(df):,} registros.")

    # ── Variación de precios ──────────────────────────────────────────────────
    if history:
        st.write("")
        st.markdown('<div class="res-seccion">Variación de precios entre cortes temporales</div>',
                    unsafe_allow_html=True)

        hp = {}
        for r in history:
            hp.setdefault((r["site_id"], r["product_url"]), {})\
              .update({r["snapshot_number"]: r["price_unit"]})

        rows = []
        for (sid, url), snaps in hp.items():
            p1, p2, p3 = snaps.get(1), snaps.get(2), snaps.get(3)
            var = round((p2 - p1) / p1 * 100, 2) if p1 and p2 and p1 > 0 else None
            name = next(
                (r["product_name"] for r in history
                 if r["site_id"] == sid and r["product_url"] == url), url.split("/")[-1]
            )
            rows.append({
                "Sitio"    : site_map.get(sid, sid),
                "Producto" : name[:40],
                "Snap. 1 ($)": p1,
                "Snap. 2 ($)": p2 or "—",
                "Snap. 3 ($)": p3 or "—",
                "Var. % (1→2)": f"{var:+.1f}%" if var is not None else "—",
            })

        df_var = pd.DataFrame(rows).dropna(subset=["Snap. 1 ($)"])
        st.dataframe(df_var, use_container_width=True, hide_index=True, height=260)
        st.markdown(
            '<div class="nota-met">'
            'Variación porcentual calculada como: (P₂ − P₁) / P₁ × 100. '
            'Los tres cortes corresponden a los días 0, 7 y 14 del período de relevamiento. '
            'Casos con P₁ = 0 excluidos del cálculo.'
            '</div>',
            unsafe_allow_html=True,
        )


def _panel_log():
    """Log de ejecución del proceso."""
    st.markdown('<div class="res-seccion">Registro de ejecución</div>',
                unsafe_allow_html=True)

    if not st.session_state.audit_log:
        st.info("El registro se completará al iniciar la auditoría o el scraping.")
        return

    log_text = "\n".join(st.session_state.audit_log[-120:])
    st.markdown(
        f'<div class="log-pre">{log_text}</div>',
        unsafe_allow_html=True,
    )

    st.download_button(
        "Descargar log completo",
        data      = "\n".join(st.session_state.audit_log),
        file_name = f"log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
        mime      = "text/plain",
    )


def _panel_exportar():
    """Opciones de exportación de datos e informes."""
    st.markdown('<div class="res-seccion">Exportación de datos e informes</div>',
                unsafe_allow_html=True)

    try:
        from modules.storage import DatabaseManager
        from config          import DB_PATH
        db      = DatabaseManager(DB_PATH)
        sites   = db.get_sites()
        results = db.get_audit_results()
        prods   = db.get_products()
    except Exception as exc:
        st.error(str(exc))
        return

    if not results and not prods:
        st.info("Sin datos disponibles para exportar. Ejecute el proceso primero.")
        return

    st.write("**Informe académico HTML**")
    if st.button("Generar informe HTML", use_container_width=True):
        try:
            from modules.reporter import HTMLReporter
            path = HTMLReporter(db).generate()
            st.download_button(
                "Descargar informe HTML",
                data      = path.read_text(encoding="utf-8"),
                file_name = path.name,
                mime      = "text/html",
                use_container_width = True,
            )
        except Exception as exc:
            st.error(str(exc))

    st.write("")
    st.write("**Exportaciones CSV**")

    col_c1, col_c2 = st.columns(2)
    with col_c1:
        if results:
            df_r = pd.DataFrame(results)
            st.download_button(
                "Resultados QA (.csv)",
                data      = df_r.to_csv(index=False, encoding="utf-8"),
                file_name = f"audit_results_{datetime.now().strftime('%Y%m%d')}.csv",
                mime      = "text/csv",
                use_container_width = True,
            )
    with col_c2:
        if prods:
            df_p = pd.DataFrame(prods)
            st.download_button(
                "Catálogo de productos (.csv)",
                data      = df_p.to_csv(index=False, encoding="utf-8"),
                file_name = f"productos_{datetime.now().strftime('%Y%m%d')}.csv",
                mime      = "text/csv",
                use_container_width = True,
            )

    st.write("")
    st.write("**Exportación completa de la base de datos**")
    if st.button("Exportar todas las tablas a CSV", use_container_width=True):
        try:
            from modules.reporter import CSVReporter
            from config          import CSV_DIR
            archivos = CSVReporter(db).export_all()
            st.success(f"{len(archivos)} archivo(s) generados en outputs/csv/")
        except Exception as exc:
            st.error(str(exc))

    st.markdown(
        '<div class="nota-met">'
        'Los informes HTML y los CSV exportados presentan los datos en formato '
        'anónimo. La base de datos local (outputs/audit.db) conserva los nombres '
        'reales para uso interno del equipo investigador.'
        '</div>',
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# COMPOSICIÓN PRINCIPAL — DOS COLUMNAS
# ══════════════════════════════════════════════════════════════════════════════

# ── Encabezado de página ──────────────────────────────────────────────────────
st.markdown(
    '<div class="pag-titulo">'
    'Sistema de Auditoría del Proceso de Compra — Comercio Electrónico Mayorista'
    '</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="pag-subtitulo">'
    'Relevamiento académico · Provincia de Misiones (NEA) · '
    'Posadas · Garupá · Itaembé Guazú · Mayoristas de consumo masivo'
    '</div>',
    unsafe_allow_html=True,
)

# ── Cuerpo: dos columnas ──────────────────────────────────────────────────────
col_izq, col_der = st.columns([2, 3], gap="large")

with col_izq:
    _grupo_muestra()
    _grupo_parametros()
    _grupo_ejecucion()

with col_der:
    # Navegación de vistas
    vista_opts = {
        "Resultados QA"     : "qa",
        "Datos del catálogo": "catalogo",
        "Log de ejecución"  : "log",
        "Exportar"          : "exportar",
    }
    vista_idx = list(vista_opts.values()).index(
        st.session_state.get("panel", "qa")
        if st.session_state.get("panel", "qa") in vista_opts.values()
        else "qa"
    )
    vista_sel = st.radio(
        "Sección:",
        options          = list(vista_opts.keys()),
        index            = vista_idx,
        horizontal       = True,
        label_visibility = "collapsed",
        key              = "radio_panel",
    )
    st.session_state.panel = vista_opts[vista_sel]
    st.divider()

    # Despacho de la vista activa
    if   st.session_state.panel == "qa":
        if st.session_state.audit_done:
            _panel_qa()
        else:
            _panel_bienvenida()
    elif st.session_state.panel == "catalogo":
        if st.session_state.scrape_done:
            _panel_catalogo()
        else:
            _panel_bienvenida()
    elif st.session_state.panel == "log":
        _panel_log()
    elif st.session_state.panel == "exportar":
        _panel_exportar()
