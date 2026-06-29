"""
modules/reporter.py — Motor de generación de informes
======================================================
Genera tres tipos de salida a partir de los datos en la base de datos:
  1. ConsoleReporter  : tabla ASCII coloreable en terminal
  2. CSVReporter      : archivos CSV por dimensión y por producto
  3. HTMLReporter     : informe HTML autocontenido con gráficos radar SVG

Uso:
    from modules.reporter import ReportEngine
    engine = ReportEngine(db)
    engine.generate(fmt="all")
"""

import csv
import logging
from datetime import datetime
from pathlib import Path

import math
from config import (
    QA_DIMENSIONS, COMPLIANCE_SCALE, CSV_DIR, REPORTS_DIR
)
from modules.storage import DatabaseManager

logger = logging.getLogger(__name__)



# ── Anonimización académica ────────────────────────────────────────────────────
def build_anon_map(sites: list) -> dict:
    """
    Genera un mapeo {site_id: 'Sitio Auditado N'} para anonimizar los informes.
    El orden es determinístico (alfabético por site_id) para garantizar
    consistencia entre distintos reportes del mismo estudio.
    Principio: los informes académicos no identifican a las organizaciones auditadas.
    """
    sorted_ids = sorted(s["id"] for s in sites)
    return {sid: f"Sitio Auditado {i}" for i, sid in enumerate(sorted_ids, start=1)}


# ─────────────────────────────────────────────────────────────────────────────
class ConsoleReporter:
    """Imprime en terminal una tabla de resultados por sitio y dimensión."""

    SCORE_ICONS = {3: "●●●", 2: "●●○", 1: "●○○", 0: "○○○"}
    SCORE_LABEL = {3: "PLENO", 2: "PARCIAL", 1: "FALLA", 0: "N/A"}

    def __init__(self, db: DatabaseManager):
        self.db = db

    def print_audit_summary(self) -> None:
        scores  = self.db.get_dimension_scores()
        sites   = self.db.get_sites()
        if not scores:
            print("\n  [!] Sin datos de auditoría en la base de datos.\n")
            return

        # Agrupar por sitio
        by_site: dict[str, dict] = {}
        for row in scores:
            sid = row["site_id"]
            if sid not in by_site:
                by_site[sid] = {}
            by_site[sid][row["dimension_id"]] = row

        # Cabecera de tabla
        dim_ids  = sorted(QA_DIMENSIONS.keys())
        col_w    = 10
        name_w   = 22

        print("\n" + "═" * (name_w + col_w * len(dim_ids) + 12))
        print("  MATRIZ DE CUMPLIMIENTO QA — PROCESO DE COMPRA MAYORISTA")
        print("═" * (name_w + col_w * len(dim_ids) + 12))
        header = f"  {'Sitio':<{name_w}}"
        for d in dim_ids:
            header += f" {d:>{col_w-1}}"
        header += f" {'ÍNDICE':>{col_w}}"
        print(header)
        print(f"  {'':-<{name_w}}" + "─" * (col_w * len(dim_ids) + col_w + len(dim_ids)))

        site_map = build_anon_map(sites)

        for site_id, dim_data in by_site.items():
            name   = site_map.get(site_id, site_id)[:name_w]
            row    = f"  {name:<{name_w}}"
            scores_list = []
            for d in dim_ids:
                if d in dim_data:
                    avg = dim_data[d]["avg_compliance"]
                    icon = self.SCORE_ICONS.get(round(avg), "?")
                    row += f" {icon:>{col_w-1}}"
                    scores_list.append(avg)
                else:
                    row += f" {'—':>{col_w-1}}"
            # Índice compuesto (promedio ponderado)
            if scores_list:
                idx = round(sum(scores_list) / len(scores_list), 2)
                row += f" {idx:>{col_w}.2f}"
            print(row)

        print("─" * (name_w + col_w * len(dim_ids) + 12))
        print(f"\n  Escala: {self.SCORE_ICONS[3]} Pleno  "
              f"{self.SCORE_ICONS[2]} Parcial  "
              f"{self.SCORE_ICONS[1]} Falla  "
              f"{self.SCORE_ICONS[0]} N/A\n")

    def print_product_summary(self) -> None:
        products = self.db.get_products()
        sites    = self.db.get_sites()
        site_map = build_anon_map(sites)

        if not products:
            print("\n  [!] Sin datos de productos en la base de datos.\n")
            return

        # Agrupar por sitio
        by_site: dict[str, list] = {}
        for p in products:
            by_site.setdefault(p["site_id"], []).append(p)

        print("\n" + "═" * 70)
        print("  RESUMEN DE PRODUCTOS EXTRAÍDOS POR SCRAPING")
        print("═" * 70)
        for site_id, prods in by_site.items():
            name      = site_map.get(site_id, site_id)
            cats      = len(set(p["category"] for p in prods))
            with_disc = sum(1 for p in prods if p["has_discount"])
            prices    = [p["price_unit"] for p in prods if p["price_unit"] and p["price_unit"] > 0]
            avg_price = round(sum(prices) / len(prices), 2) if prices else 0
            no_stock  = sum(1 for p in prods if p["stock_status"] == "sin stock")

            print(f"\n  {name} [{site_id}]")
            print(f"    Total productos   : {len(prods)}")
            print(f"    Categorías        : {cats}")
            print(f"    Con descuento     : {with_disc} ({round(with_disc/len(prods)*100)}%)")
            print(f"    Sin stock         : {no_stock}")
            print(f"    Precio prom. unit.: $ {avg_price:,.2f}")
        print()


# ─────────────────────────────────────────────────────────────────────────────
class CSVReporter:
    """Exporta todos los datos de la BD a archivos CSV."""

    def __init__(self, db: DatabaseManager, output_dir: Path = CSV_DIR):
        self.db         = db
        self.output_dir = output_dir

    def export_all(self) -> list[Path]:
        ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
        files   = self.db.export_all_csv(self.output_dir)
        logger.info(f"[CSV] {len(files)} archivos exportados en {self.output_dir}")
        return files

    def export_price_variation(self) -> Path:
        """Genera CSV de variación de precios entre snapshots."""
        history   = self.db.get_price_history()
        ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_file  = self.output_dir / f"price_variation_{ts}.csv"

        if not history:
            logger.warning("[CSV] Sin historial de precios para exportar.")
            return out_file

        # Agrupar por producto
        by_product: dict[str, list] = {}
        for row in history:
            key = (row["site_id"], row["product_url"])
            by_product.setdefault(key, []).append(row)

        rows = []
        for (site_id, url), entries in by_product.items():
            entries_sorted = sorted(entries, key=lambda x: x["snapshot_number"])
            name       = entries_sorted[0]["product_name"]
            prices     = {e["snapshot_number"]: e["price_unit"] for e in entries_sorted}
            p1         = prices.get(1, 0)
            p2         = prices.get(2, 0)
            p3         = prices.get(3, 0)
            var_1_2    = round((p2 - p1) / p1 * 100, 2) if p1 > 0 and p2 > 0 else None
            var_1_3    = round((p3 - p1) / p1 * 100, 2) if p1 > 0 and p3 > 0 else None
            rows.append({
                "site_id"     : site_id,
                "product_name": name,
                "product_url" : url,
                "precio_snap1": p1,
                "precio_snap2": p2 or "",
                "precio_snap3": p3 or "",
                "var_pct_1_2" : var_1_2 if var_1_2 is not None else "",
                "var_pct_1_3" : var_1_3 if var_1_3 is not None else "",
            })

        with open(out_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        logger.info(f"[CSV] Variación de precios: {out_file}")
        return out_file


# ─────────────────────────────────────────────────────────────────────────────
class HTMLReporter:
    """
    Genera un informe HTML autocontenido con:
     - Resumen ejecutivo de cumplimiento QA
     - Tabla de resultados por dimensión
     - Gráfico radar SVG por sitio
     - Tabla de variación de precios
    """

    def __init__(self, db: DatabaseManager, output_dir: Path = REPORTS_DIR):
        self.db         = db
        self.output_dir = output_dir

    def generate(self) -> Path:
        ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_file = self.output_dir / f"informe_auditoria_{ts}.html"
        html     = self._build_html()
        out_file.write_text(html, encoding="utf-8")
        logger.info(f"[HTML] Informe generado: {out_file}")
        return out_file

    # ── Construcción del HTML ──────────────────────────────────────────────────

    def _build_html(self) -> str:
        sites    = self.db.get_sites()
        scores   = self.db.get_dimension_scores()
        results  = self.db.get_audit_results()
        products = self.db.get_products()
        history  = self.db.get_price_history()
        ts_str   = datetime.now().strftime("%d/%m/%Y %H:%M")

        # Agrupar scores por sitio
        by_site_scores: dict[str, dict] = {}
        for row in scores:
            by_site_scores.setdefault(row["site_id"], {})[row["dimension_id"]] = row

        return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Informe de Auditoría — Mayoristas de Consumo Masivo</title>
{self._css()}
</head>
<body>
<header>
  <h1>Auditoría del proceso de compra</h1>
  <h2>Plataformas mayoristas de consumo masivo</h2>
  <p class="meta">Generado: {ts_str} &nbsp;|&nbsp; Sitios auditados: {len(sites)} &nbsp;|&nbsp;
     Casos evaluados: {len(set(r['test_case_id'] for r in results))} &nbsp;|&nbsp;
     Productos relevados: {len(products)}</p>
  <p class="disclaimer">⚠ Los nombres de las organizaciones auditadas han sido anonimizados
     conforme a los principios éticos de la investigación académica.
     Los identificadores <em>Sitio Auditado N</em> son asignados en forma arbitraria
     y no permiten inferir la identidad de las empresas.</p>
</header>
<main>
{self._section_resumen(sites, by_site_scores)}
{self._section_dimensiones(sites, results)}
{self._section_radares(sites, by_site_scores)}
{self._section_productos(sites, products)}
{self._section_precios(sites, history)}
</main>
<footer>
  <p>Documento generado automáticamente por el sistema de auditoría académica.
     Uso exclusivo en investigación. No reproducir con fines comerciales.</p>
</footer>
</body>
</html>"""

    def _section_resumen(self, sites, by_site_scores) -> str:
        dim_ids  = sorted(QA_DIMENSIONS.keys())
        site_map = build_anon_map(sites)
        rows_html = ""
        for site_id, dim_data in by_site_scores.items():
            name   = site_map.get(site_id, site_id)
            scores_vals = []
            cells  = ""
            for d in dim_ids:
                if d in dim_data:
                    avg = dim_data[d]["avg_compliance"]
                    scores_vals.append(avg)
                    cls = "score-high" if avg >= 2.5 else ("score-mid" if avg >= 1.5 else "score-low")
                    cells += f'<td class="{cls}">{avg:.2f}</td>'
                else:
                    cells += '<td class="score-na">—</td>'
            idx = round(sum(scores_vals)/len(scores_vals), 2) if scores_vals else 0
            idx_cls = "score-high" if idx >= 2.5 else ("score-mid" if idx >= 1.5 else "score-low")
            rows_html += f"<tr><td><strong>{name}</strong></td>{cells}<td class='{idx_cls}'><strong>{idx:.2f}</strong></td></tr>"

        header_cells = "".join(f"<th>{d}<br><small>{QA_DIMENSIONS[d]['name'][:15]}…</small></th>" for d in dim_ids)
        return f"""
<section>
  <h2>Matriz de cumplimiento QA</h2>
  <p>Escala de cumplimiento: <span class="score-high">≥ 2.5 Pleno</span> |
     <span class="score-mid">1.5–2.4 Parcial</span> |
     <span class="score-low">&lt; 1.5 Crítico</span></p>
  <div class="table-wrap">
  <table>
    <thead><tr><th>Sitio</th>{header_cells}<th>Índice</th></tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
  </div>
</section>"""

    def _section_dimensiones(self, sites, results) -> str:
        site_map = build_anon_map(sites)
        # Agrupar por sitio > dimensión > caso
        by_site: dict = {}
        for r in results:
            by_site.setdefault(r["site_id"], {}) \
                   .setdefault(r["dimension_id"], []) \
                   .append(r)
        html = "<section><h2>Resultados por dimensión</h2>"
        for site_id, dims in by_site.items():
            name = site_map.get(site_id, site_id)
            html += f"<h3>{name}</h3><div class='table-wrap'><table>"
            html += "<thead><tr><th>ID</th><th>Caso de prueba</th><th>Resultado</th><th>Evidencia / Notas</th></tr></thead><tbody>"
            for dim_id in sorted(dims.keys()):
                cases = dims[dim_id]
                dim_name = QA_DIMENSIONS.get(dim_id, {}).get("name", dim_id)
                html += f'<tr class="dim-header"><td colspan="4"><strong>{dim_id} — {dim_name}</strong></td></tr>'
                for c in cases:
                    comp = c["compliance"]
                    cls  = "score-high" if comp == 3 else ("score-mid" if comp == 2 else "score-low")
                    lbl  = COMPLIANCE_SCALE.get(comp, "")
                    evi  = (c.get("evidence") or c.get("notes") or "")[:80]
                    html += f"<tr><td>{c['test_case_id']}</td><td>{c['test_case_name']}</td>"
                    html += f"<td class='{cls}'>{lbl}</td><td class='evidence'>{evi}</td></tr>"
            html += "</tbody></table></div>"
        html += "</section>"
        return html

    def _section_radares(self, sites, by_site_scores) -> str:
        if not by_site_scores:
            return ""
        html = "<section><h2>Perfil de cumplimiento por sitio</h2><div class='radares'>"
        site_map = build_anon_map(sites)
        dim_ids  = sorted(QA_DIMENSIONS.keys())
        for site_id, dim_data in by_site_scores.items():
            name   = site_map.get(site_id, site_id)
            values = [dim_data.get(d, {}).get("avg_compliance", 0) for d in dim_ids]
            html  += self._radar_svg(name, dim_ids, values)
        html += "</div></section>"
        return html

    def _radar_svg(self, title: str, labels: list, values: list) -> str:
        """Genera un gráfico de radar SVG para un sitio."""
        n      = len(labels)
        cx, cy = 130, 130
        r_max  = 90
        angles = [math.pi / 2 + 2 * math.pi * i / n for i in range(n)]
        # Puntos de la malla (escala 0-3)
        def point(angle, val, scale=3):
            frac = val / scale
            x    = cx + r_max * frac * math.cos(angle)
            y    = cy - r_max * frac * math.sin(angle)
            return x, y
        # Polígono de datos
        pts = [point(angles[i], values[i]) for i in range(n)]
        poly_pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        # Ejes
        axes_svg = ""
        for i, (a, lbl) in enumerate(zip(angles, labels)):
            x2  = cx + r_max * math.cos(a)
            y2  = cy - r_max * math.sin(a)
            axes_svg += f'<line x1="{cx}" y1="{cy}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#ccc" stroke-width="0.8"/>'
            # Etiqueta
            lx  = cx + (r_max + 16) * math.cos(a)
            ly  = cy - (r_max + 16) * math.sin(a)
            dim_name = QA_DIMENSIONS.get(lbl, {}).get("name", lbl)[:12]
            axes_svg += f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" dominant-baseline="central" font-size="8" fill="#555">{lbl}<tspan dy="9" x="{lx:.1f}" font-size="7" fill="#888">{dim_name}</tspan></text>'
        # Anillos de referencia
        rings_svg = ""
        for lvl in [1, 2, 3]:
            ring_pts = " ".join(
                f"{cx + r_max*(lvl/3)*math.cos(a):.1f},{cy - r_max*(lvl/3)*math.sin(a):.1f}"
                for a in angles
            )
            rings_svg += f'<polygon points="{ring_pts}" fill="none" stroke="#ddd" stroke-width="0.6"/>'
            rings_svg += f'<text x="{cx+4:.0f}" y="{cy - r_max*(lvl/3):.0f}" font-size="7" fill="#aaa">{lvl}</text>'

        score = round(sum(values) / len(values), 2) if values else 0
        color = "#22c55e" if score >= 2.5 else ("#f59e0b" if score >= 1.5 else "#ef4444")

        return f"""<div class="radar-card">
  <svg viewBox="0 0 260 260" width="260" height="260">
    {rings_svg}
    {axes_svg}
    <polygon points="{poly_pts}" fill="{color}" fill-opacity="0.25" stroke="{color}" stroke-width="1.5"/>
    {"".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{color}"/>' for x,y in pts)}
    <text x="130" y="246" text-anchor="middle" font-size="11" font-weight="bold" fill="#333">{title[:28]}</text>
    <text x="130" y="258" text-anchor="middle" font-size="9" fill="{color}">Índice: {score:.2f} / 3.00</text>
  </svg>
</div>"""

    def _section_productos(self, sites, products) -> str:
        if not products:
            return ""
        site_map = build_anon_map(sites)
        by_site: dict[str, list] = {}
        for p in products:
            by_site.setdefault(p["site_id"], []).append(p)

        html = "<section><h2>Productos relevados por scraping</h2>"
        for site_id, prods in by_site.items():
            name       = site_map.get(site_id, site_id)
            with_disc  = sum(1 for p in prods if p["has_discount"])
            no_stock   = sum(1 for p in prods if p["stock_status"] == "sin stock")
            prices     = [p["price_unit"] for p in prods if p["price_unit"] and p["price_unit"] > 0]
            avg_p      = round(sum(prices)/len(prices), 2) if prices else 0
            html += f"<h3>{name} — {len(prods)} productos</h3>"
            html += f"<p>Con descuento: <strong>{with_disc}</strong> | Sin stock: <strong>{no_stock}</strong> | Precio prom.: <strong>$ {avg_p:,.2f}</strong></p>"
            html += "<div class='table-wrap'><table><thead><tr><th>Nombre</th><th>Categoría</th><th>Precio unit.</th><th>Medida</th><th>Stock</th><th>Dto.</th></tr></thead><tbody>"
            for p in prods[:50]:
                disc_cell = f"{p['discount_pct']:.0f}%" if p["has_discount"] else "—"
                html += (
                    f"<tr><td>{p['name'] or '—'}</td><td>{p['category'] or '—'}</td>"
                    f"<td>$ {p['price_unit']:,.2f}</td><td>{p['unit_measure'] or '—'}</td>"
                    f"<td>{p['stock_status']}</td><td>{disc_cell}</td></tr>"
                )
            if len(prods) > 50:
                html += f"<tr><td colspan='6' style='text-align:center;color:#888'>…y {len(prods)-50} más en la base de datos</td></tr>"
            html += "</tbody></table></div>"
        html += "</section>"
        return html

    def _section_precios(self, sites, history) -> str:
        if not history:
            return ""
        by_prod: dict = {}
        for row in history:
            key = (row["site_id"], row["product_url"])
            by_prod.setdefault(key, []).append(row)

        # Filtrar solo los que tienen variación
        varied = {k: v for k, v in by_prod.items() if len(v) > 1}
        if not varied:
            return ""

        site_map = build_anon_map(sites)
        html = "<section><h2>Variación de precios entre snapshots</h2>"
        html += "<div class='table-wrap'><table><thead><tr><th>Sitio</th><th>Producto</th><th>Snap 1</th><th>Snap 2</th><th>Snap 3</th><th>Var. %</th></tr></thead><tbody>"
        for (site_id, url), entries in list(varied.items())[:30]:
            entries_s  = sorted(entries, key=lambda x: x["snapshot_number"])
            prices_map = {e["snapshot_number"]: e["price_unit"] for e in entries_s}
            name       = entries_s[0]["product_name"] or url.split("/")[-1]
            p1, p2, p3 = prices_map.get(1), prices_map.get(2), prices_map.get(3)
            var        = round((p2-p1)/p1*100, 1) if p1 and p2 else ""
            var_cls    = "score-low" if isinstance(var, float) and var > 5 else ("score-mid" if var else "")
            site_name  = site_map.get(site_id, site_id)
            html += (
                f"<tr><td>{site_name}</td><td>{name[:40]}</td>"
                f"<td>${p1:,.2f}</td><td>{'$'+f'{p2:,.2f}' if p2 else '—'}</td>"
                f"<td>{'$'+f'{p3:,.2f}' if p3 else '—'}</td>"
                f"<td class='{var_cls}'>{f'{var:+.1f}%' if var != '' else '—'}</td></tr>"
            )
        html += "</tbody></table></div></section>"
        return html

    def _css(self) -> str:
        return """<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', Arial, sans-serif; background: #f8f9fa; color: #212529; font-size: 14px; }
header { background: #1e3a5f; color: white; padding: 28px 40px; }
header h1 { font-size: 24px; font-weight: 700; margin-bottom: 4px; }
header h2 { font-size: 16px; font-weight: 400; opacity: .85; margin-bottom: 8px; }
.meta { font-size: 12px; opacity: .7; }
main { max-width: 1100px; margin: 32px auto; padding: 0 20px; }
section { background: white; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,.08); padding: 28px; margin-bottom: 24px; }
h2 { font-size: 18px; color: #1e3a5f; border-bottom: 2px solid #e9ecef; padding-bottom: 10px; margin-bottom: 18px; }
h3 { font-size: 15px; color: #495057; margin: 18px 0 10px; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { background: #1e3a5f; color: white; padding: 10px 12px; text-align: center; font-weight: 600; }
td { padding: 8px 12px; border-bottom: 1px solid #f0f0f0; }
tr:hover td { background: #f8f9fa; }
.dim-header td { background: #eef2f7; font-weight: 600; color: #1e3a5f; padding: 7px 12px; }
.score-high { background: #dcfce7; color: #166534; font-weight: 600; }
.score-mid  { background: #fef9c3; color: #854d0e; font-weight: 600; }
.score-low  { background: #fee2e2; color: #991b1b; font-weight: 600; }
.score-na   { color: #9ca3af; }
.evidence   { color: #6b7280; font-size: 12px; font-style: italic; }
.radares    { display: flex; flex-wrap: wrap; gap: 20px; justify-content: center; }
.radar-card { border: 1px solid #e9ecef; border-radius: 8px; padding: 12px; background: white; }
footer { text-align: center; padding: 20px; color: #9ca3af; font-size: 12px; margin-top: 20px; }
.disclaimer { font-size: 11px; background: rgba(255,255,255,.15); border-radius: 6px;
  padding: 6px 12px; margin-top: 10px; border-left: 3px solid rgba(255,255,255,.5); }
</style>"""


# ─────────────────────────────────────────────────────────────────────────────
class ReportEngine:
    """
    Orquestador de informes. Invocado desde main.py con el comando 'report'.
    """

    def __init__(self, db: DatabaseManager):
        self.db           = db
        self.console      = ConsoleReporter(db)
        self.csv_reporter = CSVReporter(db)
        self.html_reporter= HTMLReporter(db)

    def generate(self, fmt: str = "all") -> None:
        """
        Genera los informes según el formato solicitado.
        fmt: 'console' | 'csv' | 'html' | 'all'
        """
        if fmt in ("console", "all"):
            logger.info("[REPORT] Generando reporte de consola…")
            self.console.print_audit_summary()
            self.console.print_product_summary()

        if fmt in ("csv", "all"):
            logger.info("[REPORT] Exportando CSV…")
            files = self.csv_reporter.export_all()
            self.csv_reporter.export_price_variation()
            for f in files:
                print(f"  CSV: {f}")

        if fmt in ("html", "all"):
            logger.info("[REPORT] Generando informe HTML…")
            html_file = self.html_reporter.generate()
            print(f"\n  Informe HTML: {html_file}\n")
