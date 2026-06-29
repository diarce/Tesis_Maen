# Herramienta de Auditoría de Proceso de Compra — Mayoristas de Consumo Masivo

## Descripción

Sistema de auditoría académica que combina técnicas de **Quality Assurance (QA)**
y **web scraping ético** para relevar y evaluar el proceso de compra en plataformas
de comercio electrónico mayorista.

Implementa el plan de relevamiento en 5 fases descrito en el proyecto de
investigación, con 8 dimensiones de análisis y más de 30 casos de prueba.

---

## Estructura del proyecto

```
majorista_audit/
├── main.py               ← Punto de entrada / CLI
├── config.py             ← Configuración: sitios, parámetros, casos de prueba
├── requirements.txt
├── modules/
│   ├── ethics.py         ← Resguardos éticos (robots.txt, rate limit, log)
│   ├── scraper.py        ← Motor de scraping de catálogo
│   ├── auditor.py        ← Motor de auditoría QA
│   ├── storage.py        ← Persistencia SQLite + exportación CSV
│   ├── reporter.py       ← Generación de informes (consola / CSV / HTML)
│   └── demo.py           ← Demostración con datos simulados
└── outputs/
    ├── audit.db          ← Base de datos SQLite
    ├── logs/             ← Logs de ejecución y acceso ético
    ├── csv/              ← Exportaciones CSV
    ├── reports/          ← Informes HTML
    └── snapshots/        ← Capturas de pantalla (opcional)
```

---

## Instalación

```bash
# 1. Clonar o copiar el directorio del proyecto
cd majorista_audit

# 2. Crear entorno virtual (recomendado)
python -m venv .venv
source .venv/bin/activate        # Linux/Mac
.venv\Scripts\activate           # Windows

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. (Opcional) Para sitios con JavaScript dinámico
playwright install chromium
```

---

## Uso rápido

### Demostración (sin conexión a internet)
```bash
python main.py demo
```
Genera datos simulados de 3 sitios mayoristas y produce el informe completo.

### Listar sitios configurados
```bash
python main.py list-sites
```

### Auditoría QA (requiere conectividad)
```bash
# Auditar todos los sitios configurados en config.py
python main.py audit

# Auditar un sitio específico
python main.py audit --site SITE001

# Solo una dimensión (ej: Ficha de producto)
python main.py audit --dimension D3

# Simular sin hacer requests reales
python main.py audit --dry-run
```

### Scraping de catálogo
```bash
# Primer snapshot temporal (día 0)
python main.py scrape --snapshot 1

# Segundo snapshot (día 7)
python main.py scrape --snapshot 2

# Tercer snapshot (día 14)
python main.py scrape --snapshot 3
```

### Generar informes
```bash
python main.py report              # Todos los formatos
python main.py report --format html    # Solo HTML
python main.py report --format csv     # Solo CSV
python main.py report --format console # Solo consola
```

---

## Configuración de sitios

Editar `config.py` → sección `SITES`. Cada sitio requiere:

```python
{
    "id"       : "SITE001",            # Identificador único
    "name"     : "Nombre del sitio",
    "base_url" : "https://www.sitio.com.ar",
    "dynamic"  : False,                # True si usa JavaScript para renderizar
    "platform" : "VTEX",               # Plataforma e-commerce
    "region"   : "Nacional",
    "selectors": {
        "product_card" : ".product-item",    # Selector CSS de tarjeta de producto
        "product_name" : ".product-name",
        "product_price": ".price",
        # ... (ver config.py para todos los campos)
    }
}
```

---

## Dimensiones de auditoría

| ID | Dimensión                        | Peso |
|----|----------------------------------|------|
| D1 | Estructura y navegación          | 1.0  |
| D2 | Registro y autenticación         | 1.5  |
| D3 | Ficha de producto                | 2.0  |
| D4 | Carrito de compras               | 1.5  |
| D5 | Proceso de checkout              | 2.0  |
| D6 | Medios de pago                   | 1.5  |
| D7 | Comunicación de errores          | 1.0  |
| D8 | Desempeño técnico                | 1.0  |

### Escala de cumplimiento

| Valor | Etiqueta            |
|-------|---------------------|
| 3     | Cumple plenamente   |
| 2     | Cumple parcialmente |
| 1     | No cumple           |
| 0     | No aplica / N/V     |

---

## Protocolo ético de scraping

El sistema implementa los siguientes resguardos en `modules/ethics.py`:

1. **Verificación de `robots.txt`**: antes de cada acceso, se consulta el
   archivo de restricciones del sitio. Si el acceso está denegado, se omite.

2. **Rate limiting**: pausa mínima configurable entre requests (default: 3 s)
   más jitter aleatorio (±1.5 s) para evitar patrones predecibles.

3. **User-Agent académico**: el bot se identifica con propósito académico
   y datos de contacto del investigador.

4. **Log de transparencia**: todos los accesos se registran en
   `outputs/logs/access_log_*.csv` con URL, código HTTP y tiempo de respuesta.

5. **Límites de extracción**: máximo configurable de productos por sitio
   y por categoría para no sobrecargar el servidor auditado.

---

## Salidas del sistema

| Archivo                         | Descripción                              |
|---------------------------------|------------------------------------------|
| `outputs/audit.db`              | Base de datos SQLite con todos los datos |
| `outputs/csv/products_*.csv`    | Catálogo de productos extraídos          |
| `outputs/csv/audit_results_*.csv` | Resultados de auditoría QA             |
| `outputs/csv/price_history_*.csv` | Historial de precios (3 snapshots)     |
| `outputs/csv/price_variation_*.csv` | Variación % entre cortes temporales  |
| `outputs/reports/informe_*.html`| Informe HTML con gráficos radar          |
| `outputs/logs/run_*.log`        | Log de ejecución                         |
| `outputs/logs/access_log_*.csv` | Log de transparencia ética               |

---

## Cita académica

Si este sistema es utilizado en publicaciones académicas, citar como:

> Sistema de auditoría de proceso de compra en mayoristas de consumo masivo.
> Herramienta de investigación académica — metodología mixta (QA + web scraping).
> [Nombre del investigador], [Institución], [Año].

---

## Consideraciones legales y éticas

- El sistema opera exclusivamente sobre información pública disponible sin autenticación.
- No realiza compras reales ni almacena datos de medios de pago.
- Respeta las restricciones del archivo `robots.txt` de cada sitio.
- Los datos se usan exclusivamente con fines de investigación académica.
- Se recomienda revisar los términos y condiciones de cada sitio antes de ejecutar.
