"""
config.py — Configuración central del sistema de auditoría
=============================================================
Proyecto : Auditoría del proceso de compra en sitios mayoristas de consumo masivo
Contexto : Investigación académica (metodología mixta: QA + web scraping ético)
Versión  : 1.0.0
"""

from pathlib import Path

# ── Directorios del proyecto ───────────────────────────────────────────────────
BASE_DIR      = Path(__file__).parent
OUTPUT_DIR    = BASE_DIR / "outputs"
LOGS_DIR      = OUTPUT_DIR / "logs"
CSV_DIR       = OUTPUT_DIR / "csv"
REPORTS_DIR   = OUTPUT_DIR / "reports"
SNAPSHOTS_DIR = OUTPUT_DIR / "snapshots"
DB_PATH       = OUTPUT_DIR / "audit.db"

for d in [OUTPUT_DIR, LOGS_DIR, CSV_DIR, REPORTS_DIR, SNAPSHOTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
# CONTEXTO DE INVESTIGACIÓN
# ══════════════════════════════════════════════════════════════════════════════
# Provincia  : Misiones
# Localidades: Posadas · Garupá · Itaembé Guazú
# Mercado    : Mayoristas de bienes de consumo masivo
# ══════════════════════════════════════════════════════════════════════════════

RESEARCH_CONTEXT = {
    "provincia"   : "Misiones",
    "localidades" : ["Posadas", "Garupá", "Itaembé Guazú"],
    "mercado"     : "Mayoristas de bienes de consumo masivo",
    "region"      : "NEA — Noreste Argentino",
}

# ── Muestra inicial de sitios a auditar ────────────────────────────────────────
# Representa los sitios con presencia digital en el mercado mayorista de Misiones.
# Las entradas con base_url vacía corresponden a sitios locales pendientes de
# identificación en la Fase 1 del relevamiento de campo.
SITES = [
    {
        "id"      : "MIS001",
        "name"    : "Makro Posadas",
        "base_url": "https://www.makro.com.ar",
        "dynamic" : True,
        "platform": "VTEX",
        "region"  : "Misiones · Posadas / Garupá / Itaembé Guazú",
        "notes"   : "Mayorista nacional con cobertura en Misiones. VTEX. Requiere CUIT.",
        "selectors": {
            "category_links"  : "nav a[href*='/category'], nav a[href*='/c']",
            "product_card"    : ".vtex-product-summary, [class*='productSummary']",
            "product_name"    : "[class*='productBrand'], [class*='nameContainer']",
            "product_price"   : "[class*='sellingPrice'], [class*='spotPrice']",
            "product_image"   : "[class*='productImage'] img",
            "stock_indicator" : "[class*='availability'], [class*='stock']",
            "search_input"    : "input[class*='searchInput'], input[placeholder*='busca']",
            "add_to_cart"     : "button[class*='buyButton'], button[class*='add-to-cart']",
            "breadcrumb"      : "[class*='breadcrumb']",
            "cart_count"      : "[class*='cartQuantity'], [class*='minicart-badge']",
        },
    },
    {
        "id"      : "MIS002",
        "name"    : "DIA% Mayorista",
        "base_url": "https://diaonline.supermercadosdia.com.ar",
        "dynamic" : True,
        "platform": "Custom",
        "region"  : "Misiones · Posadas / Garupá / Itaembé Guazú",
        "notes"   : "Modalidad mayorista online con despacho al NEA.",
        "selectors": {
            "category_links"  : "a[href*='/categoria'], a[href*='/c/']",
            "product_card"    : ".product-summary, [class*='product-card']",
            "product_name"    : "[class*='product-name'], h2.name",
            "product_price"   : "[class*='product-price'], .price",
            "product_image"   : ".product-image img",
            "stock_indicator" : "[class*='stock-status']",
            "search_input"    : "input[type='search'], input[placeholder*='busca']",
            "add_to_cart"     : "button[class*='add-to-cart']",
            "breadcrumb"      : "nav[aria-label*='bread']",
            "cart_count"      : "[class*='cart-count']",
        },
    },
    {
        "id"      : "MIS003",
        "name"    : "Vital Mayorista NEA",
        "base_url": "https://www.vital.com.ar",
        "dynamic" : False,
        "platform": "Magento / Custom",
        "region"  : "Misiones · Posadas / Garupá / Itaembé Guazú",
        "notes"   : "Distribuidor regional NEA. Verificar si requiere login para ver precios.",
        "selectors": {
            "category_links"  : "#nav a, .nav-primary a",
            "product_card"    : ".product-item, li.item.product",
            "product_name"    : ".product-item-name, .product-name",
            "product_price"   : ".price, [data-price-type='finalPrice']",
            "product_image"   : ".product-image-photo",
            "stock_indicator" : ".stock, .availability",
            "search_input"    : "#search, input[name='q']",
            "add_to_cart"     : "button.tocart, #product-addtocart-button",
            "breadcrumb"      : ".breadcrumbs, nav.breadcrumb",
            "cart_count"      : ".counter-number, .minicart-qty",
        },
    },
    # ─────────────────────────────────────────────────────────────────────────
    # Entradas pendientes: completar base_url con el sitio identificado en campo
    # ─────────────────────────────────────────────────────────────────────────
    # {
    #     "id"      : "MIS004",
    #     "name"    : "Distribuidora Local Posadas",
    #     "base_url": "",          ← completar con la URL real
    #     "dynamic" : False,
    #     "platform": "Custom",
    #     "region"  : "Misiones · Posadas / Garupá / Itaembé Guazú",
    #     "selectors": { ... },
    # },
]


# ── Parámetros de scraping ético ───────────────────────────────────────────────
SCRAPING_CONFIG = {
    # Identificación académica transparente del bot
    "user_agent": (
        "AcademicAuditBot/1.0 "
        "(Investigacion academica - Auditoria de e-commerce mayorista; "
        "no-comercial; contacto: investigacion@universidad.edu.ar)"
    ),
    # Control de tasa de acceso (cadencia académica: no impactar el servidor)
    "rate_limit_seconds"      : 3.0,   # Pausa base entre requests
    "rate_limit_jitter"       : 1.5,   # Variación aleatoria máxima adicional (±)
    "max_retries"             : 3,
    "retry_backoff_seconds"   : 5,
    "timeout_seconds"         : 30,
    # Límites de extracción (evitar sobrecarga del servidor)
    "max_products_per_site"   : 200,
    "max_products_per_category": 50,
    # Cortes temporales para monitoreo de variaciones
    "snapshot_intervals_days" : [0, 7, 14],
    # Cumplimiento de robots.txt (mandatorio en este protocolo)
    "respect_robots_txt"      : True,
    # Cabeceras HTTP estándar
    "headers": {
        "Accept-Language": "es-AR,es;q=0.9,en;q=0.5",
        "Accept"         : "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "DNT"            : "1",
    },
}


# ── Dimensiones de auditoría QA ────────────────────────────────────────────────
# Cada dimensión tiene un peso relativo en el índice de calidad compuesto.
QA_DIMENSIONS = {
    "D1": {
        "name"       : "Estructura y navegación",
        "description": "Arquitectura de información, menús, buscador interno y filtros.",
        "weight"     : 1.0,
    },
    "D2": {
        "name"       : "Registro y autenticación",
        "description": "Alta de cuenta, validación de CUIT, tipos de perfil mayorista.",
        "weight"     : 1.5,
    },
    "D3": {
        "name"       : "Ficha de producto",
        "description": "Completitud informacional: precios, unidades, stock, código EAN.",
        "weight"     : 2.0,
    },
    "D4": {
        "name"       : "Carrito de compras",
        "description": "Comportamiento del carrito, mínimos de compra, subtotales.",
        "weight"     : 1.5,
    },
    "D5": {
        "name"       : "Proceso de checkout",
        "description": "Flujo de pasos, formularios, opciones de entrega y logística.",
        "weight"     : 2.0,
    },
    "D6": {
        "name"       : "Medios de pago",
        "description": "Métodos disponibles, cuotas, costos financieros y transparencia.",
        "weight"     : 1.5,
    },
    "D7": {
        "name"       : "Comunicación de errores y feedback",
        "description": "Mensajes de validación, confirmaciones y manejo de estados.",
        "weight"     : 1.0,
    },
    "D8": {
        "name"       : "Desempeño técnico",
        "description": "Velocidad de carga, adaptación móvil, accesibilidad básica.",
        "weight"     : 1.0,
    },
}


# ── Casos de prueba por dimensión ──────────────────────────────────────────────
# check_type posibles: element_exists | text_pattern | response_code |
#                      performance | url_check | element_attribute | accessibility
QA_TEST_CASES = {
    "D1": [
        {
            "id"          : "D1.1",
            "name"        : "Menú de navegación principal visible en cabecera",
            "url_path"    : "/",
            "check_type"  : "element_exists",
            "selectors"   : ["nav", "header nav", ".nav-menu", "#main-nav", "[role='navigation']"],
            "instructions": "Verificar que exista un menú de navegación principal en la cabecera del sitio.",
        },
        {
            "id"          : "D1.2",
            "name"        : "Buscador interno de productos presente",
            "url_path"    : "/",
            "check_type"  : "element_exists",
            "selectors"   : ["input[type='search']", "input[name='q']", "input[name='buscar']",
                             ".search-input", "#searchbox", "input[placeholder*='busca']"],
            "instructions": "Verificar que exista un campo de búsqueda de productos accesible desde la página de inicio.",
        },
        {
            "id"          : "D1.3",
            "name"        : "Árbol de categorías accesible desde la página de inicio",
            "url_path"    : "/",
            "check_type"  : "element_exists",
            "selectors"   : [".category-menu", ".departments", "aside nav", ".vtex-menu",
                             "[class*='categoryMenu']", "[class*='category-tree']"],
            "instructions": "Verificar que las categorías de productos estén visibles o accesibles desde el inicio.",
        },
        {
            "id"          : "D1.4",
            "name"        : "Breadcrumbs presentes en páginas de producto",
            "url_path"    : None,
            "check_type"  : "element_exists",
            "selectors"   : ["nav[aria-label*='breadcrumb']", ".breadcrumb", "[class*='breadcrumb']",
                             "[itemtype*='BreadcrumbList']"],
            "instructions": "Navegar a una ficha de producto y verificar la presencia de ruta de navegación (migas de pan).",
        },
        {
            "id"          : "D1.5",
            "name"        : "Filtros de ordenamiento en resultados de búsqueda",
            "url_path"    : None,
            "check_type"  : "element_exists",
            "selectors"   : ["select[name*='sort']", ".sort-options", "[class*='orderBy']",
                             ".filter-panel", "[class*='searchFilter']"],
            "instructions": "Ejecutar una búsqueda y verificar la disponibilidad de filtros y opciones de ordenamiento.",
        },
    ],
    "D2": [
        {
            "id"          : "D2.1",
            "name"        : "Enlace o botón de registro de cuenta visible",
            "url_path"    : "/",
            "check_type"  : "element_exists",
            "selectors"   : ["a[href*='register']", "a[href*='registro']", "a[href*='cadastro']",
                             ".register-link", "[class*='registerLink']"],
            "instructions": "Verificar que exista un acceso visible para registrar una cuenta nueva.",
        },
        {
            "id"          : "D2.2",
            "name"        : "Campo CUIT/CUIL en formulario de alta",
            "url_path"    : None,
            "check_type"  : "element_exists",
            "selectors"   : ["input[name*='cuit']", "input[name*='cuil']", "input[id*='cuit']",
                             "input[placeholder*='CUIT']", "input[placeholder*='CUIL']"],
            "instructions": "En el formulario de registro, verificar el campo de ingreso de CUIT o CUIL.",
        },
        {
            "id"          : "D2.3",
            "name"        : "Diferenciación de tipo de cuenta (mayorista/minorista)",
            "url_path"    : None,
            "check_type"  : "text_pattern",
            "pattern"     : r"(mayorista|revendedor|distribuidor|comerciante|tipo de cuenta)",
            "instructions": "Verificar si el formulario permite seleccionar el tipo de cliente.",
        },
        {
            "id"          : "D2.4",
            "name"        : "Formulario de inicio de sesión funcional",
            "url_path"    : None,
            "check_type"  : "element_exists",
            "selectors"   : ["input[type='email']", "input[name='email']", "input[name='usuario']",
                             "input[name='login']"],
            "instructions": "Acceder a la página de login y verificar que el formulario de autenticación esté presente.",
        },
    ],
    "D3": [
        {
            "id"          : "D3.1",
            "name"        : "Precio de venta visible en ficha de producto",
            "url_path"    : None,
            "check_type"  : "element_exists",
            "selectors"   : [".price", "[class*='price']", "[itemprop='price']",
                             ".product-price", "[class*='sellingPrice']"],
            "instructions": "En la página de producto, verificar la presencia del precio de venta.",
        },
        {
            "id"          : "D3.2",
            "name"        : "Precio por bulto, pack o caja indicado",
            "url_path"    : None,
            "check_type"  : "text_pattern",
            "pattern"     : r"(por (bulto|caja|pack|unidad)|precio (bulto|caja)|x\d+\s*un)",
            "instructions": "Verificar si se indica el precio del bulto o pack completo.",
        },
        {
            "id"          : "D3.3",
            "name"        : "Unidad de medida especificada",
            "url_path"    : None,
            "check_type"  : "text_pattern",
            "pattern"     : r"\d+[\.,]?\d*\s*(kg|g|gr|lt|lts|l|ml|cc|un|und|unid|pack|caja|bulto)",
            "instructions": "Verificar que la ficha de producto incluya la unidad de medida.",
        },
        {
            "id"          : "D3.4",
            "name"        : "Indicador de disponibilidad de stock",
            "url_path"    : None,
            "check_type"  : "element_exists",
            "selectors"   : ["[class*='stock']", "[class*='availability']", "[class*='disponib']",
                             ".in-stock", ".out-of-stock", "[class*='stockMessage']"],
            "instructions": "Verificar que se indique si el producto está disponible o sin stock.",
        },
        {
            "id"          : "D3.5",
            "name"        : "Descuento por volumen o escala visible",
            "url_path"    : None,
            "check_type"  : "text_pattern",
            "pattern"     : r"(descuento|oferta|precio especial|por mayor|x\d+\s*(un|packs?))",
            "instructions": "Verificar si se muestran precios diferenciados por cantidad de compra.",
        },
        {
            "id"          : "D3.6",
            "name"        : "Imagen de producto con atributo alt descriptivo",
            "url_path"    : None,
            "check_type"  : "element_attribute",
            "selectors"   : [".product-image img", "[class*='product'] img", "[class*='gallery'] img"],
            "attribute"   : "alt",
            "instructions": "Verificar imagen de producto con texto alternativo (accesibilidad y SEO).",
        },
    ],
    "D4": [
        {
            "id"          : "D4.1",
            "name"        : "Botón de agregar al carrito presente y visible",
            "url_path"    : None,
            "check_type"  : "element_exists",
            "selectors"   : ["button[class*='cart']", "button[class*='add']", ".add-to-cart",
                             "[class*='buyButton']", "button[class*='comprar']"],
            "instructions": "Verificar la presencia del botón para agregar productos al carrito.",
        },
        {
            "id"          : "D4.2",
            "name"        : "Cantidad mínima de compra comunicada",
            "url_path"    : None,
            "check_type"  : "text_pattern",
            "pattern"     : r"(m[ií]nimo|cant\. m[ií]n|min\s*\d|compra m[ií]nima|desde \d+ (un|packs?))",
            "instructions": "Verificar si el sitio comunica el mínimo de compra exigido.",
        },
        {
            "id"          : "D4.3",
            "name"        : "Selector de cantidad de unidades en carrito",
            "url_path"    : None,
            "check_type"  : "element_exists",
            "selectors"   : ["input[type='number']", ".quantity-selector", "[class*='quantity']",
                             "[class*='quantitySelector']", "input[name*='qty']"],
            "instructions": "Verificar que sea posible ajustar la cantidad de cada ítem en el carrito.",
        },
        {
            "id"          : "D4.4",
            "name"        : "Subtotal actualizado visible en carrito",
            "url_path"    : None,
            "check_type"  : "element_exists",
            "selectors"   : [".cart-subtotal", "[class*='subtotal']", "[class*='orderTotal']",
                             "[class*='cartTotal']"],
            "instructions": "Verificar que el carrito muestre el subtotal actualizado.",
        },
    ],
    "D5": [
        {
            "id"          : "D5.1",
            "name"        : "Indicador de etapas de progreso en checkout",
            "url_path"    : None,
            "check_type"  : "element_exists",
            "selectors"   : [".checkout-steps", "[class*='step']", "ol.steps",
                             ".progress-bar", "[class*='checkoutStep']"],
            "instructions": "Verificar que el checkout muestre indicador de etapas o progreso.",
        },
        {
            "id"          : "D5.2",
            "name"        : "Opción de envío a domicilio disponible",
            "url_path"    : None,
            "check_type"  : "text_pattern",
            "pattern"     : r"(env[ií]o|entrega a domicilio|despacho|delivery)",
            "instructions": "Verificar la presencia de opción de envío o entrega a domicilio en el checkout.",
        },
        {
            "id"          : "D5.3",
            "name"        : "Opción de retiro en sucursal disponible",
            "url_path"    : None,
            "check_type"  : "text_pattern",
            "pattern"     : r"(retiro|retirar en (local|sucursal|despacho)|pick[\s\-]?up|retiro gratis)",
            "instructions": "Verificar la presencia de opción de retiro en local o depósito.",
        },
        {
            "id"          : "D5.4",
            "name"        : "Formulario de dirección de entrega presente",
            "url_path"    : None,
            "check_type"  : "element_exists",
            "selectors"   : ["input[name*='address']", "input[name*='calle']",
                             "input[placeholder*='direc']", "input[id*='street']"],
            "instructions": "Verificar la existencia del formulario para ingresar dirección de entrega.",
        },
    ],
    "D6": [
        {
            "id"          : "D6.1",
            "name"        : "Medios de pago listados en el sitio",
            "url_path"    : "/",
            "check_type"  : "text_pattern",
            "pattern"     : r"(visa|mastercard|mercado pago|transferencia|tarjeta|pago)",
            "instructions": "Verificar que el sitio comunique los medios de pago aceptados.",
        },
        {
            "id"          : "D6.2",
            "name"        : "Opción de transferencia bancaria disponible",
            "url_path"    : None,
            "check_type"  : "text_pattern",
            "pattern"     : r"(transferencia bancaria|transfer|cbu|cvu|banco)",
            "instructions": "Verificar disponibilidad de pago por transferencia.",
        },
        {
            "id"          : "D6.3",
            "name"        : "Información de HTTPS y seguridad",
            "url_path"    : "/",
            "check_type"  : "url_check",
            "condition"   : "https",
            "instructions": "Verificar que el sitio opere bajo protocolo HTTPS.",
        },
        {
            "id"          : "D6.4",
            "name"        : "Factura tipo A disponible para revendedores",
            "url_path"    : None,
            "check_type"  : "text_pattern",
            "pattern"     : r"(factura [aAB]|comprobante fiscal|monotributista|responsable inscripto)",
            "instructions": "Verificar si el sitio comunica los tipos de comprobante fiscal disponibles.",
        },
    ],
    "D7": [
        {
            "id"          : "D7.1",
            "name"        : "Confirmación visual al agregar producto al carrito",
            "url_path"    : None,
            "check_type"  : "element_exists",
            "selectors"   : ["[class*='toast']", "[class*='notification']", "[role='alert']",
                             "[class*='addToCartMessage']", ".cart-notification"],
            "instructions": "Al agregar un producto, verificar que aparezca un mensaje de confirmación.",
        },
        {
            "id"          : "D7.2",
            "name"        : "Mensajes de error en formularios (validación)",
            "url_path"    : None,
            "check_type"  : "element_exists",
            "selectors"   : ["[class*='error']", ".field-error", "[aria-invalid='true']",
                             ".invalid-feedback", "[class*='validationMessage']"],
            "instructions": "Introducir datos inválidos y verificar que el sistema muestre mensajes de error claros.",
        },
        {
            "id"          : "D7.3",
            "name"        : "Página de error 404 con navegación útil",
            "url_path"    : "/pagina-inexistente-audit-test-xyz",
            "check_type"  : "response_code",
            "expected_code": 404,
            "instructions": "Acceder a URL inexistente y verificar que se muestre una página de error informativa.",
        },
    ],
    "D8": [
        {
            "id"          : "D8.1",
            "name"        : "Tiempo de respuesta del servidor < 5 segundos",
            "url_path"    : "/",
            "check_type"  : "performance",
            "threshold_seconds": 5.0,
            "instructions": "Medir el tiempo de respuesta del servidor para la página de inicio.",
        },
        {
            "id"          : "D8.2",
            "name"        : "Meta viewport para adaptación móvil presente",
            "url_path"    : "/",
            "check_type"  : "element_exists",
            "selectors"   : ["meta[name='viewport']"],
            "instructions": "Verificar la presencia de la etiqueta meta viewport.",
        },
        {
            "id"          : "D8.3",
            "name"        : "Conexión HTTPS activa",
            "url_path"    : "/",
            "check_type"  : "url_check",
            "condition"   : "https",
            "instructions": "Verificar que el sitio principal use protocolo HTTPS.",
        },
        {
            "id"          : "D8.4",
            "name"        : "Imágenes del catálogo con atributo alt",
            "url_path"    : None,
            "check_type"  : "accessibility",
            "rule"        : "img_alt",
            "instructions": "Verificar que las imágenes tengan atributos alt descriptivos (WCAG 1.1.1).",
        },
    ],
}


# ── Escala de cumplimiento ─────────────────────────────────────────────────────
COMPLIANCE_SCALE = {
    3: "Cumple plenamente",
    2: "Cumple parcialmente",
    1: "No cumple",
    0: "No aplica / No verificable",
}
