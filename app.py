"""
app.py — Frontend Streamlit del sistema de auditoría académica
==============================================================
Interfaz gráfica para:
  1. Selección geográfica (Provincia → Localidad)
  2. Gestión de empresas mayoristas a auditar
  3. Configuración de parámetros de auditoría y scraping
  4. Ejecución del proceso con seguimiento en tiempo real
  5. Visualización de resultados y exportación

Ejecución:
    streamlit run app.py
"""

import json
import logging
import sys
import time
import traceback
from datetime import datetime
from io import StringIO
from pathlib import Path

import pandas as pd
import streamlit as st

# ── Setup de paths ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# ── Configuración de página ────────────────────────────────────────────────────
st.set_page_config(
    page_title="AuditMayorista",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS personalizado ──────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Tipografía y base */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

/* Header principal */
.app-header {
    background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%);
    color: white; border-radius: 12px; padding: 24px 32px;
    margin-bottom: 24px;
}
.app-header h1 { font-size: 26px; font-weight: 700; margin: 0 0 4px; }
.app-header p  { font-size: 14px; opacity: .8; margin: 0; }

/* Cards de métricas */
.metric-card {
    background: white; border: 1px solid #e2e8f0;
    border-radius: 10px; padding: 18px 20px;
    text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,.06);
}
.metric-card .value { font-size: 32px; font-weight: 700; color: #1e3a5f; }
.metric-card .label { font-size: 12px; color: #64748b; margin-top: 2px; }

/* Etiquetas de cumplimiento */
.badge-full    { background:#dcfce7;color:#166534;border-radius:20px;padding:2px 10px;font-size:12px;font-weight:600; }
.badge-partial { background:#fef9c3;color:#854d0e;border-radius:20px;padding:2px 10px;font-size:12px;font-weight:600; }
.badge-fail    { background:#fee2e2;color:#991b1b;border-radius:20px;padding:2px 10px;font-size:12px;font-weight:600; }
.badge-na      { background:#f1f5f9;color:#64748b;border-radius:20px;padding:2px 10px;font-size:12px;font-weight:600; }

/* Steps del sidebar */
.step-header {
    background: #f8fafc; border-left: 4px solid #2563eb;
    padding: 8px 12px; border-radius: 0 6px 6px 0;
    font-weight: 600; font-size: 13px; color: #1e3a5f;
    margin: 16px 0 10px;
}

/* Log de proceso */
.log-box {
    background: #0f172a; color: #94a3b8;
    font-family: 'JetBrains Mono', monospace; font-size: 12px;
    padding: 14px; border-radius: 8px; max-height: 300px;
    overflow-y: auto; white-space: pre-wrap;
}

/* Tabla de empresas */
.empresa-card {
    border: 1px solid #e2e8f0; border-radius: 8px;
    padding: 12px 16px; margin-bottom: 8px;
    background: white;
}
.empresa-card .name { font-weight: 600; color: #1e3a5f; }
.empresa-card .url  { font-size: 12px; color: #64748b; }

/* Botones de acción */
/* Botón primario — estilo manejado por Streamlit type="primary" */

/* Score bars */
.score-bar-wrap { background: #f1f5f9; border-radius: 6px; height: 8px; margin: 2px 0; }
.score-bar      { background: #2563eb; border-radius: 6px; height: 8px; transition: width .3s; }

[data-testid="stSidebar"] { background: #f8fafc; }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# CARGA DE DATOS
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data
def load_provincias() -> dict:
    path = ROOT / "data" / "provincias_localidades.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)

@st.cache_data
def load_empresas_base() -> list:
    path = ROOT / "data" / "empresas_mayoristas.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)

PROVINCIAS     = load_provincias()
EMPRESAS_BASE  = load_empresas_base()

# ══════════════════════════════════════════════════════════════════════════════
# ESTADO DE SESIÓN
# ══════════════════════════════════════════════════════════════════════════════

def init_state():
    defaults = {
        "companies"        : [],          # Lista de empresas a auditar
        "audit_done"       : False,
        "scrape_done"      : False,
        "audit_log"        : [],          # Líneas de log en tiempo real
        "audit_results_db" : None,        # Path de la BD post-auditoría
        "selected_dims"    : list("D1 D2 D3 D4 D5 D6 D7 D8".split()),
        "rate_limit"       : 3.0,
        "max_products"     : 50,
        "active_tab"       : 0,
        "provincia_sel"    : list(PROVINCIAS.keys())[0],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def compliance_badge(score: float) -> str:
    if score >= 2.5:
        return f'<span class="badge-full">● {score:.2f} Pleno</span>'
    if score >= 1.5:
        return f'<span class="badge-partial">● {score:.2f} Parcial</span>'
    if score > 0:
        return f'<span class="badge-fail">● {score:.2f} Crítico</span>'
    return '<span class="badge-na">— N/A</span>'


def score_color(score: float) -> str:
    if score >= 2.5: return "#22c55e"
    if score >= 1.5: return "#f59e0b"
    return "#ef4444"


def add_log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    icon = {"INFO": "ℹ", "OK": "✓", "WARN": "⚠", "ERR": "✗"}.get(level, "·")
    st.session_state.audit_log.append(f"[{ts}] {icon} {msg}")
    if len(st.session_state.audit_log) > 200:
        st.session_state.audit_log = st.session_state.audit_log[-200:]


class StreamlitLogHandler(logging.Handler):
    """Redirige logs Python al estado de sesión de Streamlit."""
    def emit(self, record):
        level_map = {
            logging.DEBUG   : "·",
            logging.INFO    : "ℹ",
            logging.WARNING : "⚠",
            logging.ERROR   : "✗",
        }
        ts   = datetime.now().strftime("%H:%M:%S")
        icon = level_map.get(record.levelno, "·")
        msg  = self.format(record)
        st.session_state.audit_log.append(f"[{ts}] {icon} {msg}")


def install_log_handler():
    """Instala el handler de Streamlit en el logger raíz."""
    root_logger = logging.getLogger()
    # Evitar duplicados
    root_logger.handlers = [
        h for h in root_logger.handlers
        if not isinstance(h, StreamlitLogHandler)
    ]
    handler = StreamlitLogHandler()
    handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)


def build_runtime_sites() -> list:
    """Construye la lista de sitios para inyectar en config.SITES."""
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
    """Actualiza config.SITES y SCRAPING_CONFIG en memoria (in-place)."""
    import config
    config.SITES.clear()
    config.SITES.extend(sites)
    config.SCRAPING_CONFIG["rate_limit_seconds"]    = cfg["rate_limit"]
    config.SCRAPING_CONFIG["max_products_per_site"] = cfg["max_products"]


def write_runtime_json(sites: list):
    """Guarda la configuración activa en runtime_sites.json."""
    out = ROOT / "runtime_sites.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(sites, f, ensure_ascii=False, indent=2)
    return out


def preview_config_py(sites: list, cfg: dict) -> str:
    """Genera el bloque Python equivalente de config.SITES para mostrar al usuario."""
    out = []
    out.append("# Configuracion generada por AuditMayorista")
    out.append("# " + datetime.now().isoformat())
    out.append("")
    out.append("SITES = [")
    for s in sites:
        sel_str = json.dumps(s.get("selectors", {}), ensure_ascii=False)
        out.append("    {")
        out.append("        'id'       : " + repr(str(s["id"])) + ",")
        out.append("        'name'     : " + repr(str(s["name"])) + ",")
        out.append("        'base_url' : " + repr(str(s["base_url"])) + ",")
        out.append("        'dynamic'  : " + str(bool(s.get("dynamic", False))) + ",")
        out.append("        'platform' : " + repr(str(s.get("platform", ""))) + ",")
        out.append("        'region'   : " + repr(str(s.get("region", ""))) + ",")
        out.append("        'selectors': " + sel_str + ",")
        out.append("    },")
    out.append("]")
    out.append("")
    out.append("# Parametros de scraping")
    rl  = str(cfg["rate_limit"])
    mp  = str(cfg["max_products"])
    out.append("SCRAPING_CONFIG['rate_limit_seconds']    = " + rl)
    out.append("SCRAPING_CONFIG['max_products_per_site'] = " + mp)
    return chr(10).join(out)



# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════

def render_sidebar():
    with st.sidebar:
        st.markdown("## 🛒 AuditMayorista")
        st.caption("Sistema académico de auditoría")
        st.divider()

        # ── PASO 1: ZONA GEOGRÁFICA ────────────────────────────────────────────
        st.markdown('<div class="step-header">📍 PASO 1 — Zona geográfica</div>', unsafe_allow_html=True)

        provincia = st.selectbox(
            "Provincia",
            options=sorted(PROVINCIAS.keys()),
            index=sorted(PROVINCIAS.keys()).index(st.session_state.provincia_sel),
            key="provincia_widget",
        )
        st.session_state.provincia_sel = provincia

        localidades = PROVINCIAS.get(provincia, [])
        localidades_sel = st.multiselect(
            "Localidad/es",
            options=localidades,
            default=[localidades[0]] if localidades else [],
            placeholder="Seleccionar localidades…",
            key="localidades_widget",
        )

        # ── PASO 2: EMPRESAS ───────────────────────────────────────────────────
        st.markdown('<div class="step-header">🏢 PASO 2 — Empresas a auditar</div>', unsafe_allow_html=True)

        # Sub-tab: buscar conocidas / agregar manual
        modo = st.radio(
            "Modo de carga",
            ["Base de datos", "Manual"],
            horizontal=True,
            label_visibility="collapsed",
        )

        if modo == "Base de datos":
            _sidebar_empresas_base(provincia, localidades_sel)
        else:
            _sidebar_empresa_manual(provincia, localidades_sel)

        # ── PASO 3: PARÁMETROS ─────────────────────────────────────────────────
        st.markdown('<div class="step-header">⚙️ PASO 3 — Parámetros</div>', unsafe_allow_html=True)

        st.session_state.selected_dims = st.multiselect(
            "Dimensiones a auditar",
            options=["D1","D2","D3","D4","D5","D6","D7","D8"],
            default=st.session_state.selected_dims,
            format_func=lambda d: {
                "D1":"D1 · Navegación","D2":"D2 · Registro",
                "D3":"D3 · Ficha producto","D4":"D4 · Carrito",
                "D5":"D5 · Checkout","D6":"D6 · Pagos",
                "D7":"D7 · Errores","D8":"D8 · Performance",
            }[d],
        )

        st.session_state.rate_limit = st.slider(
            "Rate limit (seg. entre requests)", 1.0, 10.0,
            st.session_state.rate_limit, 0.5,
            help="Pausa mínima entre requests al servidor auditado."
        )
        st.session_state.max_products = st.slider(
            "Máx. productos por sitio", 10, 200,
            st.session_state.max_products, 10,
        )

        st.divider()

        # ── BOTONES DE ACCIÓN ──────────────────────────────────────────────────
        n = len(st.session_state.companies)
        if n == 0:
            st.info("Agregá al menos una empresa para continuar.")
        else:
            st.success(f"**{n} empresa{'s' if n>1 else ''} lista{'s' if n>1 else ''} para auditar**")

        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("💾 Guardar config", use_container_width=True, disabled=n == 0):
                _save_config()
        with col_b:
            if st.button("🔄 Demo", use_container_width=True):
                _run_demo()

        if st.button("▶️  INICIAR AUDITORÍA", type="primary",
                     use_container_width=True, disabled=n == 0):
            _run_audit()

        if st.button("🌐  INICIAR SCRAPING", use_container_width=True, disabled=n == 0):
            _run_scraping()


def _sidebar_empresas_base(provincia: str, localidades: list):
    """Muestra empresas de la base que cubren la provincia seleccionada."""
    disponibles = [
        e for e in EMPRESAS_BASE
        if "todas" in e.get("provincias", []) or provincia in e.get("provincias", [])
    ]
    if not disponibles:
        st.caption("Sin empresas registradas para esta provincia.")
        return

    for emp in disponibles:
        ya_agregada = any(c["id"] == emp["id"] for c in st.session_state.companies)
        col1, col2 = st.columns([4, 1])
        with col1:
            st.markdown(
                f"**{emp['name']}**  \n"
                f"<span style='font-size:11px;color:#64748b'>{emp['base_url']}</span>",
                unsafe_allow_html=True,
            )
        with col2:
            label = "✓" if ya_agregada else "＋"
            if st.button(label, key=f"add_{emp['id']}", disabled=ya_agregada,
                         use_container_width=True):
                company = dict(emp)
                company["region"] = f"{provincia} · {', '.join(localidades[:2])}"
                st.session_state.companies.append(company)
                st.rerun()


def _sidebar_empresa_manual(provincia: str, localidades: list):
    """Formulario para agregar empresa manualmente."""
    with st.form("form_manual", clear_on_submit=True):
        name     = st.text_input("Nombre de la empresa *", placeholder="Ej: Distribuidora XYZ")
        base_url = st.text_input("URL del sitio *", placeholder="https://www.empresa.com.ar")
        platform = st.selectbox("Plataforma", ["VTEX","Magento","WooCommerce","Shopify","Custom","Desconocida"])
        tipo     = st.selectbox("Tipo", ["Nacional","Regional","Local"])
        rubro    = st.text_input("Rubro", placeholder="Consumo masivo / Alimentos")
        dynamic  = st.checkbox("Sitio con JavaScript dinámico", value=False,
                               help="Activo si el catálogo no aparece sin JS (requiere Playwright)")
        submitted = st.form_submit_button("➕ Agregar empresa", use_container_width=True)

    if submitted:
        if not name or not base_url:
            st.error("Nombre y URL son obligatorios.")
        elif not base_url.startswith("http"):
            st.error("La URL debe comenzar con http:// o https://")
        else:
            new_id = f"USR{len(st.session_state.companies)+1:03d}"
            st.session_state.companies.append({
                "id"         : new_id,
                "name"       : name,
                "base_url"   : base_url.rstrip("/"),
                "platform"   : platform,
                "tipo"       : tipo,
                "rubro"      : rubro,
                "dynamic"    : dynamic,
                "region"     : f"{provincia} · {', '.join(localidades[:2])}",
                "descripcion": f"Empresa agregada manualmente ({tipo})",
                "provincias" : [provincia],
                "selectors"  : {
                    "product_card"    : ".product-item, [class*='product']",
                    "product_name"    : "h2, h3, .product-name, [class*='name']",
                    "product_price"   : ".price, [class*='price'], [itemprop='price']",
                    "product_image"   : "img[class*='product'], .product-image img",
                    "stock_indicator" : "[class*='stock'], [class*='avail']",
                    "search_input"    : "input[type='search'], input[name='q']",
                    "add_to_cart"     : "button[class*='cart'], button[class*='add']",
                    "breadcrumb"      : ".breadcrumb, [aria-label*='bread']",
                    "category_links"  : "nav a",
                    "cart_count"      : "[class*='cart-count'], [class*='badge']",
                },
            })
            st.success(f"✓ {name} agregada.")
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# ACCIONES PRINCIPALES
# ══════════════════════════════════════════════════════════════════════════════

def _save_config():
    """Guarda la configuración activa en runtime_sites.json y muestra preview."""
    sites = build_runtime_sites()
    if not sites:
        st.sidebar.error("No hay empresas con URL válida.")
        return
    out = write_runtime_json(sites)
    inject_config(sites, {
        "rate_limit"  : st.session_state.rate_limit,
        "max_products": st.session_state.max_products,
    })
    st.sidebar.success(f"Configuración guardada → {out.name}")
    add_log(f"Configuración guardada: {len(sites)} sitios → {out}", "OK")


def _run_demo():
    """Ejecuta el modo demo con datos simulados."""
    st.session_state.audit_log = []
    install_log_handler()
    add_log("=== INICIANDO MODO DEMOSTRACIÓN ===", "INFO")
    try:
        from modules.storage import DatabaseManager
        from modules.demo    import run_demo
        from config          import DB_PATH
        db = DatabaseManager(DB_PATH)
        run_demo(db)
        st.session_state.audit_done  = True
        st.session_state.scrape_done = True
        add_log("Demo completado exitosamente.", "OK")
    except Exception as exc:
        add_log(f"Error en demo: {exc}", "ERR")
        st.sidebar.error(str(exc))
    st.rerun()


def _run_audit():
    """Ejecuta la auditoría QA para los sitios configurados."""
    sites = build_runtime_sites()
    if not sites:
        st.sidebar.error("Configurá al menos una empresa con URL válida.")
        return
    st.session_state.audit_log = []
    install_log_handler()
    inject_config(sites, {
        "rate_limit"  : st.session_state.rate_limit,
        "max_products": st.session_state.max_products,
    })
    add_log(f"=== INICIANDO AUDITORÍA QA — {len(sites)} sitio(s) ===", "INFO")
    try:
        from modules.storage import DatabaseManager
        from modules.auditor import AuditEngine
        from config          import DB_PATH
        db     = DatabaseManager(DB_PATH)
        engine = AuditEngine(db)
        engine.run(
            dimension_filter = st.session_state.get("selected_dims") or None,
            dry_run          = False,
            sites_override   = sites,
        )
        st.session_state.audit_done = True
        add_log("=== AUDITORÍA COMPLETADA ===", "OK")
    except Exception as exc:
        add_log(f"Error: {exc}", "ERR")
        add_log(traceback.format_exc(), "ERR")
    st.rerun()


def _run_scraping():
    """Ejecuta el scraping de catálogo para los sitios configurados."""
    sites = build_runtime_sites()
    if not sites:
        st.sidebar.error("Configurá al menos una empresa con URL válida.")
        return
    st.session_state.audit_log = []
    install_log_handler()
    inject_config(sites, {
        "rate_limit"  : st.session_state.rate_limit,
        "max_products": st.session_state.max_products,
    })
    add_log(f"=== INICIANDO SCRAPING — {len(sites)} sitio(s) ===", "INFO")
    try:
        from modules.storage import DatabaseManager
        from modules.scraper import ScrapingEngine
        from config          import DB_PATH
        db     = DatabaseManager(DB_PATH)
        engine = ScrapingEngine(db)
        engine.run(snapshot_number=1, sites_override=sites)
        st.session_state.scrape_done = True
        add_log("=== SCRAPING COMPLETADO ===", "OK")
    except Exception as exc:
        add_log(f"Error: {exc}", "ERR")
        add_log(traceback.format_exc(), "ERR")
    st.rerun()


def _remove_company(idx: int):
    st.session_state.companies.pop(idx)
    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# CONTENIDO PRINCIPAL — TABS
# ══════════════════════════════════════════════════════════════════════════════

def render_main():
    # Header
    st.markdown("""
    <div class="app-header">
      <h1>🛒 AuditMayorista</h1>
      <p>Sistema académico de relevamiento y auditoría del proceso de compra en mayoristas de consumo masivo</p>
    </div>
    """, unsafe_allow_html=True)

    tab_labels = [
        "📋 Empresas",
        "⚙️ Configuración",
        "▶️ Auditoría",
        "📊 Resultados QA",
        "🗃️ Datos Scraping",
    ]
    tabs = st.tabs(tab_labels)

    with tabs[0]: tab_empresas()
    with tabs[1]: tab_configuracion()
    with tabs[2]: tab_auditoria()
    with tabs[3]: tab_resultados()
    with tabs[4]: tab_scraping()


# ─────────────────────────────────────────────────────────────────────────────
def tab_empresas():
    st.subheader("Empresas en la muestra de auditoría")

    n = len(st.session_state.companies)
    if n == 0:
        st.info(
            "👈 Usá el panel lateral para agregar empresas mayoristas.\n\n"
            "Podés seleccionar de la base de datos de empresas conocidas "
            "o ingresar una nueva de forma manual."
        )
        return

    # Métricas rápidas
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f'<div class="metric-card"><div class="value">{n}</div><div class="label">Empresas en muestra</div></div>', unsafe_allow_html=True)
    nacionales = sum(1 for c in st.session_state.companies if c.get("tipo") == "Nacional")
    with c2:
        st.markdown(f'<div class="metric-card"><div class="value">{nacionales}</div><div class="label">Nacionales</div></div>', unsafe_allow_html=True)
    regionales = n - nacionales
    with c3:
        st.markdown(f'<div class="metric-card"><div class="value">{regionales}</div><div class="label">Regionales / Locales</div></div>', unsafe_allow_html=True)
    dinamicas = sum(1 for c in st.session_state.companies if c.get("dynamic"))
    with c4:
        st.markdown(f'<div class="metric-card"><div class="value">{dinamicas}</div><div class="label">Con JS dinámico</div></div>', unsafe_allow_html=True)

    st.markdown("---")

    # Tabla editable
    for i, company in enumerate(st.session_state.companies):
        with st.container():
            col1, col2, col3, col4, col_del = st.columns([3, 2, 2, 2, 1])
            with col1:
                st.markdown(
                    f"**{company['name']}**  \n"
                    f"<span style='font-size:11px;color:#2563eb'>{company['base_url']}</span>",
                    unsafe_allow_html=True
                )
            with col2:
                tipo_color = "#dcfce7" if company.get("tipo") == "Nacional" else "#fef9c3"
                tipo_text  = "#166534" if company.get("tipo") == "Nacional" else "#854d0e"
                st.markdown(
                    f"<span style='background:{tipo_color};color:{tipo_text};"
                    f"padding:2px 8px;border-radius:20px;font-size:12px'>"
                    f"{company.get('tipo','—')}</span>  \n"
                    f"<span style='font-size:11px;color:#64748b'>{company.get('platform','')}</span>",
                    unsafe_allow_html=True
                )
            with col3:
                st.caption(f"📍 {company.get('region','—')}")
            with col4:
                js_icon = "⚡ JS dinámico" if company.get("dynamic") else "📄 HTML estático"
                st.caption(js_icon)
            with col_del:
                if st.button("🗑", key=f"del_{i}", help="Eliminar empresa"):
                    _remove_company(i)
            st.divider()

    # Exportar lista como CSV
    df = pd.DataFrame([{
        "ID"       : c["id"],
        "Empresa"  : c["name"],
        "URL"      : c["base_url"],
        "Plataforma": c.get("platform",""),
        "Tipo"     : c.get("tipo",""),
        "Región"   : c.get("region",""),
        "Dinámico" : c.get("dynamic", False),
    } for c in st.session_state.companies])

    st.download_button(
        "⬇️  Descargar lista como CSV",
        data=df.to_csv(index=False, encoding="utf-8"),
        file_name=f"muestra_empresas_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )


# ─────────────────────────────────────────────────────────────────────────────
def tab_configuracion():
    st.subheader("Configuración activa del relevamiento")

    if not st.session_state.companies:
        st.info("Agregá empresas en el panel lateral para ver la configuración generada.")
        return

    sites = build_runtime_sites()
    cfg   = {
        "rate_limit"  : st.session_state.rate_limit,
        "max_products": st.session_state.max_products,
    }

    col_l, col_r = st.columns([1, 1])

    with col_l:
        st.markdown("#### 🗺️ Resumen de la muestra")
        for s in sites:
            st.markdown(
                f"**{s['name']}** `{s['id']}`  \n"
                f"🔗 {s['base_url']}  \n"
                f"🖥 `{s['platform']}` · {'⚡ Dinámico' if s['dynamic'] else '📄 Estático'}  \n"
                f"📍 {s.get('region','—')}"
            )
            st.markdown("---")

        st.markdown("#### ⚙️ Parámetros de scraping")
        st.markdown(f"""
| Parámetro | Valor |
|---|---|
| Rate limit | `{cfg['rate_limit']} s` |
| Máx. productos/sitio | `{cfg['max_products']}` |
| Resp. robots.txt | `Activado` |
| User-Agent | Académico |
| Snapshots temporales | `3 cortes` (0 / 7 / 14 días) |
""")
        st.markdown("#### 📐 Dimensiones seleccionadas")
        dims_desc = {
            "D1":"Estructura y navegación","D2":"Registro y autenticación",
            "D3":"Ficha de producto","D4":"Carrito de compras",
            "D5":"Proceso de checkout","D6":"Medios de pago",
            "D7":"Comunicación de errores","D8":"Desempeño técnico",
        }
        for d in st.session_state.selected_dims:
            st.markdown(f"- **{d}** — {dims_desc.get(d,'')}")

    with col_r:
        st.markdown("#### 📄 Código generado para `config.py`")
        code_preview = preview_config_py(sites, cfg)
        st.code(code_preview, language="python")

        col_copy, col_save = st.columns(2)
        with col_copy:
            st.download_button(
                "⬇️  Descargar config.py",
                data=code_preview,
                file_name="runtime_config.py",
                mime="text/plain",
                use_container_width=True,
            )
        with col_save:
            if st.button("💾 Guardar runtime_sites.json", use_container_width=True):
                _save_config()
                st.success("✓ Guardado")

        st.markdown("#### 📋 Casos de prueba QA (muestra)")
        from config import QA_TEST_CASES, QA_DIMENSIONS
        total_cases = sum(len(v) for k, v in QA_TEST_CASES.items()
                          if k in st.session_state.selected_dims)
        st.metric("Total casos de prueba", total_cases)

        dims_data = []
        for d in st.session_state.selected_dims:
            cases = QA_TEST_CASES.get(d, [])
            dims_data.append({
                "Dimensión": d,
                "Nombre"   : QA_DIMENSIONS.get(d, {}).get("name",""),
                "Casos"    : len(cases),
                "Peso"     : QA_DIMENSIONS.get(d, {}).get("weight", 1.0),
            })
        st.dataframe(pd.DataFrame(dims_data), hide_index=True, use_container_width=True)


# ─────────────────────────────────────────────────────────────────────────────
def tab_auditoria():
    st.subheader("Ejecución del proceso de auditoría")

    col_btn1, col_btn2, col_btn3 = st.columns([2, 2, 3])
    with col_btn1:
        if st.button("▶️ Auditoría QA", type="primary", use_container_width=True,
                     disabled=len(st.session_state.companies)==0):
            _run_audit()
    with col_btn2:
        if st.button("🌐 Scraping", use_container_width=True,
                     disabled=len(st.session_state.companies)==0):
            _run_scraping()
    with col_btn3:
        if st.button("🎭 Ejecutar DEMO (sin internet)", use_container_width=True):
            _run_demo()

    st.markdown("---")

    # Estado de finalización
    col_qa, col_sc = st.columns(2)
    with col_qa:
        if st.session_state.audit_done:
            st.success("✅ Auditoría QA completada")
        else:
            st.warning("⏳ Auditoría QA pendiente")
    with col_sc:
        if st.session_state.scrape_done:
            st.success("✅ Scraping completado")
        else:
            st.warning("⏳ Scraping pendiente")

    # Log en tiempo real
    st.markdown("#### 📟 Log de ejecución")
    if st.session_state.audit_log:
        log_text = "\n".join(st.session_state.audit_log[-80:])
        st.code(log_text, language=None)
        st.download_button(
            "⬇️ Descargar log completo",
            data="\n".join(st.session_state.audit_log),
            file_name=f"log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            mime="text/plain",
        )
    else:
        st.info("El log de ejecución aparecerá aquí cuando se inicie el proceso.")

    # Guía de procesos
    with st.expander("📖 ¿Qué hace cada proceso?", expanded=False):
        st.markdown("""
**Auditoría QA** (`▶️ Auditoría QA`)
- Navega el sitio usando `requests` + `BeautifulSoup`
- Verifica cada caso de prueba de las 8 dimensiones configuradas
- No realiza compras reales ni ingresa datos sensibles
- Guarda los resultados en la base de datos SQLite

**Scraping** (`🌐 Scraping`)
- Extrae el catálogo de productos (nombre, precio, categoría, stock)
- Respeta `robots.txt` y el rate limit configurado
- Almacena el primer snapshot temporal (el día 0)
- Repetir el proceso en 7 y 14 días para análisis de variación

**Demo** (`🎭 Ejecutar DEMO`)
- Genera datos simulados realistas de 3 sitios mayoristas argentinos
- No requiere conexión a internet
- Sirve para verificar el funcionamiento del sistema y el informe
        """)


# ─────────────────────────────────────────────────────────────────────────────
def tab_resultados():
    st.subheader("Resultados de la auditoría QA")

    try:
        from modules.storage import DatabaseManager
        from config import DB_PATH, QA_DIMENSIONS
        db     = DatabaseManager(DB_PATH)
        scores = db.get_dimension_scores()
        sites  = db.get_sites()
        results= db.get_audit_results()
    except Exception as exc:
        st.error(f"Error al acceder a la base de datos: {exc}")
        return

    if not scores:
        st.info(
            "Aún no hay resultados de auditoría.\n\n"
            "Iniciá el proceso desde el panel lateral o la pestaña **▶️ Auditoría**."
        )
        return

    from modules.reporter import build_anon_map
    # Toggle de anonimización — para uso interno/externo del informe
    anonimizar = st.toggle(
        "🔒 Anonimizar sitios (modo informe académico)",
        value=True,
        help="Reemplaza los nombres reales por 'Sitio Auditado N' para proteger la identidad de las organizaciones."
    )
    if anonimizar:
        site_map = build_anon_map(sites)
        st.caption("Los nombres de las organizaciones han sido anonimizados.")
    else:
        site_map = {s["id"]: s["name"] for s in sites}
        st.caption("⚠ Modo interno — mostrando nombres reales. No publicar.")
    dim_ids  = sorted(QA_DIMENSIONS.keys())

    # ── Métricas globales ──────────────────────────────────────────────────────
    total_cases = len(results)
    full_pass   = sum(1 for r in results if r["compliance"] == 3)
    partial     = sum(1 for r in results if r["compliance"] == 2)
    fail        = sum(1 for r in results if r["compliance"] == 1)
    avg_score   = round(sum(r["compliance"] for r in results if r["compliance"] > 0)
                        / max(1, sum(1 for r in results if r["compliance"] > 0)), 2)

    c1, c2, c3, c4, c5 = st.columns(5)
    metrics = [
        (len(sites), "Sitios auditados"),
        (total_cases, "Casos evaluados"),
        (full_pass, "✓ Pleno cumplimiento"),
        (partial, "~ Cumplimiento parcial"),
        (fail, "✗ No cumple"),
    ]
    for col, (val, lbl) in zip([c1,c2,c3,c4,c5], metrics):
        col.markdown(
            f'<div class="metric-card"><div class="value">{val}</div>'
            f'<div class="label">{lbl}</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # ── Matriz de cumplimiento ─────────────────────────────────────────────────
    st.markdown("#### 🧮 Matriz de cumplimiento por sitio y dimensión")

    by_site: dict[str, dict] = {}
    for row in scores:
        by_site.setdefault(row["site_id"], {})[row["dimension_id"]] = row

    matrix_rows = []
    for sid, dim_data in by_site.items():
        row = {"Sitio": site_map.get(sid, sid)}
        score_vals = []
        for d in dim_ids:
            if d in dim_data:
                avg = round(dim_data[d]["avg_compliance"], 2)
                row[d] = avg
                score_vals.append(avg)
            else:
                row[d] = None
        row["Índice"] = round(sum(score_vals)/len(score_vals), 2) if score_vals else 0
        matrix_rows.append(row)

    df_matrix = pd.DataFrame(matrix_rows)

    # Colormap para la tabla
    def color_cell(val):
        if pd.isna(val) or val == 0:
            return "background-color: #f8fafc; color: #94a3b8"
        if val >= 2.5:
            return "background-color: #dcfce7; color: #166534; font-weight:600"
        if val >= 1.5:
            return "background-color: #fef9c3; color: #854d0e; font-weight:600"
        return "background-color: #fee2e2; color: #991b1b; font-weight:600"

    styled = (
        df_matrix.style
        .map(color_cell, subset=dim_ids + ["Índice"])
        .format({d: "{:.2f}" for d in dim_ids + ["Índice"]}, na_rep="—")
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)

    # ── Detalle por dimensión ──────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 🔍 Detalle por dimensión")

    by_site_dim: dict = {}
    for r in results:
        by_site_dim.setdefault(r["site_id"], {}).setdefault(r["dimension_id"], []).append(r)

    site_sel = st.selectbox(
        "Seleccionar sitio",
        options=[s["id"] for s in sites],
        format_func=lambda sid: site_map.get(sid, sid),
    )

    if site_sel in by_site_dim:
        for dim_id in sorted(by_site_dim[site_sel].keys()):
            if dim_id not in st.session_state.selected_dims:
                continue
            dim_results = by_site_dim[site_sel][dim_id]
            dim_name    = QA_DIMENSIONS.get(dim_id, {}).get("name", dim_id)
            avg_d       = round(sum(r["compliance"] for r in dim_results if r["compliance"] > 0)
                                / max(1, sum(1 for r in dim_results if r["compliance"] > 0)), 2)

            with st.expander(f"**{dim_id}** — {dim_name}  |  Promedio: {avg_d:.2f}/3", expanded=False):
                detail_rows = [{
                    "ID"         : r["test_case_id"],
                    "Caso"       : r["test_case_name"],
                    "Resultado"  : r["compliance_label"],
                    "Puntuación" : r["compliance"],
                    "Evidencia"  : (r.get("evidence") or r.get("notes") or "")[:60],
                } for r in dim_results]
                df_detail = pd.DataFrame(detail_rows)

                def color_compliance(val):
                    if val == 3: return "background-color:#dcfce7;color:#166534"
                    if val == 2: return "background-color:#fef9c3;color:#854d0e"
                    if val == 1: return "background-color:#fee2e2;color:#991b1b"
                    return ""

                styled_d = df_detail.style.map(color_compliance, subset=["Puntuación"])
                st.dataframe(styled_d, hide_index=True, use_container_width=True)

    # ── Exportar y descargar informe ───────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 📤 Exportar informe")
    col_e1, col_e2, col_e3 = st.columns(3)

    with col_e1:
        if st.button("🌐 Generar informe HTML", use_container_width=True):
            try:
                from modules.reporter import HTMLReporter
                reporter = HTMLReporter(db)
                html_path = reporter.generate()
                with open(html_path, "r", encoding="utf-8") as f:
                    html_content = f.read()
                st.download_button(
                    "⬇️ Descargar HTML",
                    data=html_content,
                    file_name=html_path.name,
                    mime="text/html",
                    use_container_width=True,
                )
            except Exception as exc:
                st.error(str(exc))

    with col_e2:
        if st.button("📊 Exportar CSV completo", use_container_width=True):
            try:
                from modules.reporter import CSVReporter
                from config import CSV_DIR
                reporter = CSVReporter(db)
                files = reporter.export_all()
                st.success(f"✓ {len(files)} archivos CSV generados en outputs/csv/")
            except Exception as exc:
                st.error(str(exc))

    with col_e3:
        # Descarga directa de audit_results
        if results:
            df_exp = pd.DataFrame(results)
            st.download_button(
                "⬇️ Descargar resultados QA",
                data=df_exp.to_csv(index=False, encoding="utf-8"),
                file_name=f"audit_results_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True,
            )


# ─────────────────────────────────────────────────────────────────────────────
def tab_scraping():
    st.subheader("Datos extraídos por scraping")

    try:
        from modules.storage import DatabaseManager
        from config import DB_PATH
        db       = DatabaseManager(DB_PATH)
        products = db.get_products()
        history  = db.get_price_history()
        sites    = db.get_sites()
        snaps    = db.get_sites()
    except Exception as exc:
        st.error(str(exc))
        return

    if not products:
        st.info(
            "Sin datos de productos todavía.\n\n"
            "Iniciá el **Scraping** desde el panel lateral o ejecutá el **Demo**."
        )
        return

    from modules.reporter import build_anon_map
    site_map = build_anon_map(sites)
    df_prod  = pd.DataFrame(products)
    df_prod["site_name"] = df_prod["site_id"].map(site_map)

    # ── Métricas ───────────────────────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric("Total productos", len(df_prod))
    with c2:
        st.metric("Sitios con datos", df_prod["site_id"].nunique())
    with c3:
        st.metric("Categorías", df_prod["category"].nunique())
    with c4:
        n_disc = int(df_prod["has_discount"].sum())
        st.metric("Con descuento", f"{n_disc} ({round(n_disc/len(df_prod)*100)}%)")
    with c5:
        prices = df_prod[df_prod["price_unit"] > 0]["price_unit"]
        st.metric("Precio prom.", f"$ {prices.mean():,.0f}" if len(prices) else "—")

    st.markdown("---")

    # ── Filtros ────────────────────────────────────────────────────────────────
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        site_filter = st.multiselect(
            "Filtrar por sitio",
            options=df_prod["site_id"].unique().tolist(),
            format_func=lambda x: site_map.get(x, x),
        )
    with col_f2:
        cat_filter = st.multiselect(
            "Filtrar por categoría",
            options=sorted(df_prod["category"].dropna().unique().tolist()),
        )
    with col_f3:
        stock_filter = st.multiselect(
            "Estado de stock",
            options=df_prod["stock_status"].unique().tolist(),
        )

    df_view = df_prod.copy()
    if site_filter: df_view = df_view[df_view["site_id"].isin(site_filter)]
    if cat_filter:  df_view = df_view[df_view["category"].isin(cat_filter)]
    if stock_filter:df_view = df_view[df_view["stock_status"].isin(stock_filter)]

    cols_show = ["site_name","name","brand","category","price_unit",
                 "price_bulk","unit_measure","stock_status","has_discount","discount_pct"]
    cols_show = [c for c in cols_show if c in df_view.columns]

    st.dataframe(
        df_view[cols_show].rename(columns={
            "site_name"  :"Sitio","name":"Producto","brand":"Marca",
            "category"   :"Categoría","price_unit":"Precio unit.",
            "price_bulk" :"Precio bulto","unit_measure":"Unidad",
            "stock_status":"Stock","has_discount":"Dto.","discount_pct":"% Dto.",
        }),
        use_container_width=True,
        hide_index=True,
        height=380,
    )

    st.caption(f"Mostrando {len(df_view):,} de {len(df_prod):,} productos")

    # ── Variación de precios ───────────────────────────────────────────────────
    if history:
        st.markdown("---")
        st.markdown("#### 📈 Variación de precios entre snapshots")

        df_h     = pd.DataFrame(history)
        df_pivot = (
            df_h.groupby(["site_id","product_name","snapshot_number"])["price_unit"]
            .mean().reset_index()
            .pivot(index=["site_id","product_name"], columns="snapshot_number", values="price_unit")
            .reset_index()
        )
        df_pivot.columns = ["site_id","Producto"] + [f"Snap {c}" for c in df_pivot.columns[2:]]
        df_pivot["site"] = df_pivot["site_id"].map(site_map)

        # Calcular variación snap1→snap2
        if "Snap 1" in df_pivot.columns and "Snap 2" in df_pivot.columns:
            df_pivot["Var. %"] = ((df_pivot["Snap 2"] - df_pivot["Snap 1"])
                                  / df_pivot["Snap 1"].replace(0, float("nan")) * 100).round(1)

        price_cols = [c for c in df_pivot.columns if c.startswith("Snap")]
        show_cols  = ["site","Producto"] + price_cols + (["Var. %"] if "Var. %" in df_pivot.columns else [])

        def color_var(val):
            if pd.isna(val): return ""
            if val > 10:  return "color:#991b1b;font-weight:600"
            if val > 0:   return "color:#854d0e"
            if val < 0:   return "color:#166534"
            return ""

        styled_p = df_pivot[show_cols].dropna(subset=["Snap 1"]).style
        if "Var. %" in df_pivot.columns:
            styled_p = styled_p.map(color_var, subset=["Var. %"])
        st.dataframe(styled_p, hide_index=True, use_container_width=True, height=300)

    # ── Descarga ───────────────────────────────────────────────────────────────
    st.markdown("---")
    st.download_button(
        "⬇️ Descargar productos (CSV)",
        data=df_view.to_csv(index=False, encoding="utf-8"),
        file_name=f"productos_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )


# ══════════════════════════════════════════════════════════════════════════════
# PUNTO DE ENTRADA
# ══════════════════════════════════════════════════════════════════════════════

render_sidebar()
render_main()
