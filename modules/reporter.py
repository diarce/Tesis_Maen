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
        n_casos  = len(set(r["test_case_id"] for r in results)) if results else 0

        by_site_scores: dict[str, dict] = {}
        for row in scores:
            by_site_scores.setdefault(row["site_id"], {})[row["dimension_id"]] = row

        return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Informe de Auditoria - Mayoristas de Consumo Masivo</title>
{self._css()}
</head>
<body>
<div class="portada">
  <div class="portada-titulo">Informe de Relevamiento y Auditoria</div>
  <div class="portada-subtitulo">Proceso de Compra en Plataformas Mayoristas de Consumo Masivo</div>
  <div class="portada-region">Provincia de Misiones - NEA - Argentina</div>
  <div class="portada-meta">
    Fecha de generacion: {ts_str}<br>
    Plataformas relevadas: {len(sites)}<br>
    Indicadores evaluados: {n_casos} por plataforma<br>
    Productos relevados: {len(products)}
  </div>
  <div class="nota-anon">Los nombres de las organizaciones auditadas han sido reemplazados
  por identificadores genericos (Sitio Auditado N) conforme a los principios eticos
  de la investigacion academica. Los identificadores son asignados en forma arbitraria
  y no permiten inferir la identidad de las organizaciones.</div>
</div>
<div class="contenido">
{self._section_distribucion(results)}
{self._section_dims_agregado(scores)}
{self._section_matriz(sites, by_site_scores)}
{self._section_detalle_casos(sites, results)}
{self._section_catalogo_agregado(sites, products)}
{self._section_precios_agregado(sites, history)}
</div>
<div class="pie">
  Documento generado por el sistema de auditoria academica AuditMayorista.
  Uso exclusivo en investigacion. No reproducir con fines comerciales.
</div>
</body>
</html>"""

    # ── Secciones del informe ──────────────────────────────────────────────────

    def _section_distribucion(self, results: list) -> str:
        """Distribucion global de los valores de cumplimiento."""
        if not results:
            return ""
        total  = len(results)
        dist   = {0: 0, 1: 0, 2: 0, 3: 0}
        for r in results:
            dist[r["compliance"]] = dist.get(r["compliance"], 0) + 1

        filas = ""
        etiquetas = {3: "Cumple plenamente", 2: "Cumple parcialmente",
                     1: "No cumple", 0: "No aplica / No verificable"}
        for v in [3, 2, 1, 0]:
            n   = dist[v]
            pct = round(n / total * 100, 1) if total else 0
            filas += f"<tr><td>{v}</td><td>{etiquetas[v]}</td><td class='num'>{n}</td><td class='num'>{pct}%</td></tr>"

        return f"""
<div class="seccion">
  <div class="sec-num">1.</div>
  <div class="sec-titulo">Distribucion global del cumplimiento</div>
  <div class="sec-desc">Total de observaciones evaluadas en el conjunto de plataformas: {total}.</div>
  <table>
    <thead><tr><th>Valor</th><th>Categoria</th><th>Cantidad</th><th>Porcentaje</th></tr></thead>
    <tbody>{filas}</tbody>
  </table>
  <div class="nota">Escala de medicion: 3 = Cumple plenamente, 2 = Cumple parcialmente,
  1 = No cumple, 0 = No aplica o no verificable. Los casos con valor 0 se excluyen
  del calculo de promedios dimensionales.</div>
</div>"""

    def _section_dims_agregado(self, scores: list) -> str:
        """Resultados agregados por dimension: promedio, min, max, tasa de aprobacion."""
        if not scores:
            return ""
        from collections import defaultdict
        por_dim: dict[str, list] = defaultdict(list)
        for row in scores:
            por_dim[row["dimension_id"]].append(row["avg_compliance"])

        filas = ""
        for did in sorted(QA_DIMENSIONS.keys()):
            if did not in por_dim:
                continue
            vals     = por_dim[did]
            n        = len(vals)
            prom     = round(sum(vals) / n, 2)
            minimo   = round(min(vals), 2)
            maximo   = round(max(vals), 2)
            aprobados= sum(1 for v in vals if v >= 2.0)
            tasa     = round(aprobados / n * 100, 1)
            nombre   = QA_DIMENSIONS[did]["name"]
            peso     = QA_DIMENSIONS[did]["weight"]
            filas += (
                f"<tr><td>{did}</td><td>{nombre}</td><td class='num'>{peso}</td>"
                f"<td class='num'>{prom:.2f}</td><td class='num'>{minimo:.2f}</td>"
                f"<td class='num'>{maximo:.2f}</td><td class='num'>{tasa}%</td></tr>"
            )

        return f"""
<div class="seccion">
  <div class="sec-num">2.</div>
  <div class="sec-titulo">Resultados por dimension de analisis</div>
  <div class="sec-desc">Estadisticas calculadas sobre el conjunto de plataformas relevadas.
  El promedio corresponde a la media aritmetica de los scores dimensionales de todos los sitios.</div>
  <table>
    <thead><tr>
      <th>ID</th><th>Dimension</th><th>Peso</th>
      <th>Promedio</th><th>Minimo</th><th>Maximo</th><th>% Aprobacion</th>
    </tr></thead>
    <tbody>{filas}</tbody>
  </table>
  <div class="nota">El porcentaje de aprobacion considera cumplimiento plenamente o
  parcialmente (valores 2 y 3). El peso es el coeficiente de ponderacion utilizado
  en el calculo del Indice de Calidad Compuesto.</div>
</div>"""

    def _section_matriz(self, sites: list, by_site_scores: dict) -> str:
        """Matriz comparativa unificada: todos los sitios x todas las dimensiones."""
        if not by_site_scores:
            return ""
        dim_ids  = sorted(QA_DIMENSIONS.keys())
        site_map = build_anon_map(sites)
        pesos    = {d: QA_DIMENSIONS[d]["weight"] for d in dim_ids}

        # Filas de sitios
        filas      = ""
        col_sumas  = {d: [] for d in dim_ids}
        for sid, dim_data in sorted(by_site_scores.items()):
            nombre = site_map.get(sid, sid)
            vals   = []
            celdas = ""
            for d in dim_ids:
                if d in dim_data:
                    v = dim_data[d]["avg_compliance"]
                    vals.append(v)
                    col_sumas[d].append(v)
                    cls = "alto" if v >= 2.5 else ("medio" if v >= 1.5 else "bajo")
                    celdas += f'<td class="num {cls}">{v:.2f}</td>'
                else:
                    celdas += '<td class="num nd">nd</td>'
            icc = round(
                sum(dim_data[d]["avg_compliance"] * pesos[d]
                    for d in dim_ids if d in dim_data)
                / sum(pesos[d] for d in dim_ids if d in dim_data), 2
            ) if vals else 0
            cls_icc = "alto" if icc >= 2.5 else ("medio" if icc >= 1.5 else "bajo")
            filas += (
                f"<tr><td>{nombre}</td>{celdas}"
                f"<td class='num {cls_icc} icc'>{icc:.2f}</td></tr>"
            )

        # Fila de promedios
        prom_celdas = ""
        for d in dim_ids:
            v = round(sum(col_sumas[d]) / len(col_sumas[d]), 2) if col_sumas[d] else 0
            prom_celdas += f'<td class="num prom">{v:.2f}</td>'
        # ICC promedio
        icc_prom = round(
            sum(
                (sum(col_sumas[d]) / len(col_sumas[d])) * pesos[d]
                for d in dim_ids if col_sumas[d]
            ) / sum(pesos[d] for d in dim_ids if col_sumas[d]), 2
        ) if any(col_sumas.values()) else 0
        filas += (
            f"<tr class='fila-prom'><td>Promedio general</td>{prom_celdas}"
            f"<td class='num prom icc'>{icc_prom:.2f}</td></tr>"
        )

        encabezados = "".join(
            f"<th>{d}<br><small>{QA_DIMENSIONS[d]['name'][:12]}</small></th>"
            for d in dim_ids
        )

        return f"""
<div class="seccion">
  <div class="sec-num">3.</div>
  <div class="sec-titulo">Matriz de cumplimiento</div>
  <div class="sec-desc">Cada celda representa el promedio de cumplimiento de una dimension
  para una plataforma. El Indice de Calidad Compuesto (ICC) es la media ponderada
  de los ocho scores dimensionales.</div>
  <div class="tabla-scroll">
  <table>
    <thead><tr><th>Plataforma</th>{encabezados}<th>ICC</th></tr></thead>
    <tbody>{filas}</tbody>
  </table>
  </div>
  <div class="leyenda-colores">
    <span class="alto">Alto (&gt;= 2.50)</span>
    <span class="medio">Medio (1.50 - 2.49)</span>
    <span class="bajo">Bajo (&lt; 1.50)</span>
  </div>
</div>"""

    def _section_detalle_casos(self, sites: list, results: list) -> str:
        """
        Detalle de casos de prueba con todas las plataformas en columnas.
        Vista agregada: los casos son las filas, las plataformas son las columnas.
        """
        if not results:
            return ""
        site_map  = build_anon_map(sites)
        site_ids  = sorted({r["site_id"] for r in results})
        site_cols = [site_map.get(sid, sid) for sid in site_ids]

        # Organizar resultados: {dim_id: {test_case_id: {site_id: compliance}}}
        datos: dict = {}
        nombres_caso: dict = {}
        for r in results:
            did  = r["dimension_id"]
            tcid = r["test_case_id"]
            datos.setdefault(did, {}).setdefault(tcid, {})[r["site_id"]] = r["compliance"]
            nombres_caso[tcid] = r["test_case_name"]

        encabezados = "".join(f"<th>{col}</th>" for col in site_cols)
        html_dims   = ""

        for did in sorted(datos.keys()):
            dim_nombre = QA_DIMENSIONS.get(did, {}).get("name", did)
            filas_dim  = ""
            for tcid in sorted(datos[did].keys()):
                nombre_tc = nombres_caso.get(tcid, tcid)
                celdas    = ""
                for sid in site_ids:
                    v   = datos[did][tcid].get(sid)
                    if v is None:
                        celdas += "<td class='num nd'>nd</td>"
                    else:
                        lbl = COMPLIANCE_SCALE.get(v, str(v))
                        cls = "alto" if v == 3 else ("medio" if v == 2 else ("bajo" if v == 1 else "nd"))
                        celdas += f'<td class="num {cls}" title="{lbl}">{v}</td>'
                filas_dim += f"<tr><td class='caso-id'>{tcid}</td><td>{nombre_tc}</td>{celdas}</tr>"
            html_dims += f"""
<div class="bloque-dim">
  <div class="dim-titulo">{did} — {dim_nombre}</div>
  <div class="tabla-scroll">
  <table>
    <thead><tr><th>ID</th><th>Indicador evaluado</th>{encabezados}</tr></thead>
    <tbody>{filas_dim}</tbody>
  </table>
  </div>
</div>"""

        return f"""
<div class="seccion">
  <div class="sec-num">4.</div>
  <div class="sec-titulo">Detalle de indicadores por dimension</div>
  <div class="sec-desc">Cada fila representa un indicador evaluado. Las columnas muestran
  el valor de cumplimiento obtenido por cada plataforma auditada. Escala: 3 Pleno,
  2 Parcial, 1 No cumple, 0 No aplica.</div>
  {html_dims}
</div>"""

    def _section_catalogo_agregado(self, sites: list, products: list) -> str:
        """Catalogo de productos relevados: estadisticas agregadas del conjunto."""
        if not products:
            return ""
        site_map    = build_anon_map(sites)
        total       = len(products)
        con_dto     = sum(1 for p in products if p["has_discount"])
        sin_stock   = sum(1 for p in products if p["stock_status"] == "sin stock")
        categorias  = len(set(p["category"] for p in products if p["category"]))
        precios     = [p["price_unit"] for p in products if p["price_unit"] and p["price_unit"] > 0]
        prom_p      = round(sum(precios) / len(precios), 2) if precios else 0
        min_p       = round(min(precios), 2) if precios else 0
        max_p       = round(max(precios), 2) if precios else 0

        resumen = f"""
<table>
  <thead><tr><th>Indicador</th><th>Valor</th></tr></thead>
  <tbody>
    <tr><td>Total de productos relevados</td><td class='num'>{total}</td></tr>
    <tr><td>Categorias identificadas</td><td class='num'>{categorias}</td></tr>
    <tr><td>Productos con descuento</td><td class='num'>{con_dto} ({round(con_dto/total*100,1) if total else 0}%)</td></tr>
    <tr><td>Productos sin stock</td><td class='num'>{sin_stock} ({round(sin_stock/total*100,1) if total else 0}%)</td></tr>
    <tr><td>Precio unitario promedio</td><td class='num'>$ {prom_p:,.2f}</td></tr>
    <tr><td>Precio unitario minimo</td><td class='num'>$ {min_p:,.2f}</td></tr>
    <tr><td>Precio unitario maximo</td><td class='num'>$ {max_p:,.2f}</td></tr>
  </tbody>
</table>"""

        # Tabla completa de productos (todos juntos)
        filas_prod = ""
        for p in products[:200]:
            sitio    = site_map.get(p["site_id"], p["site_id"])
            dto_cell = f"{p['discount_pct']:.0f}%" if p["has_discount"] else "No"
            filas_prod += (
                f"<tr><td>{sitio}</td><td>{p['name'] or 'nd'}</td>"
                f"<td>{p['category'] or 'nd'}</td>"
                f"<td class='num'>$ {p['price_unit']:,.2f}</td>"
                f"<td>{p['unit_measure'] or 'nd'}</td>"
                f"<td>{p['stock_status']}</td>"
                f"<td class='num'>{dto_cell}</td></tr>"
            )
        if len(products) > 200:
            filas_prod += f"<tr><td colspan='7' class='nota-fila'>Se muestran 200 de {len(products)} registros.</td></tr>"

        tabla_prod = f"""
<div class="tabla-scroll">
<table>
  <thead><tr>
    <th>Plataforma</th><th>Producto</th><th>Categoria</th>
    <th>Precio unit.</th><th>Medida</th><th>Stock</th><th>Descuento</th>
  </tr></thead>
  <tbody>{filas_prod}</tbody>
</table>
</div>"""

        return f"""
<div class="seccion">
  <div class="sec-num">5.</div>
  <div class="sec-titulo">Catalogo de productos relevados</div>
  <div class="sec-desc">Productos extraidos del catalogo publico de las plataformas
  auditadas. Los datos corresponden al primer corte temporal del relevamiento.</div>
  {resumen}
  <div class="subtitulo-tabla">Listado consolidado de productos</div>
  {tabla_prod}
</div>"""

    def _section_precios_agregado(self, sites: list, history: list) -> str:
        """Variacion de precios entre cortes temporales: vista agregada."""
        if not history:
            return ""
        site_map = build_anon_map(sites)

        # Calcular variaciones
        por_prod: dict = {}
        for row in history:
            key = (row["site_id"], row["product_url"])
            por_prod.setdefault(key, {})[row["snapshot_number"]] = {
                "price": row["price_unit"],
                "name" : row["product_name"],
            }

        variaciones = []
        for (sid, url), snaps in por_prod.items():
            p1  = snaps.get(1, {}).get("price")
            p2  = snaps.get(2, {}).get("price")
            p3  = snaps.get(3, {}).get("price")
            nom = snaps.get(1, {}).get("name") or url.split("/")[-1]
            var12 = round((p2 - p1) / p1 * 100, 2) if p1 and p2 and p1 > 0 else None
            var13 = round((p3 - p1) / p1 * 100, 2) if p1 and p3 and p1 > 0 else None
            variaciones.append({
                "site": site_map.get(sid, sid),
                "nombre": nom,
                "p1": p1, "p2": p2, "p3": p3,
                "var12": var12, "var13": var13,
            })

        # Estadisticas agregadas de variacion
        vars12 = [v["var12"] for v in variaciones if v["var12"] is not None]
        prom_var = round(sum(vars12) / len(vars12), 2) if vars12 else 0
        sobre5   = sum(1 for v in vars12 if v > 5)
        bajo0    = sum(1 for v in vars12 if v < 0)

        resumen_var = f"""
<table>
  <thead><tr><th>Indicador</th><th>Valor</th></tr></thead>
  <tbody>
    <tr><td>Pares de precios comparados (Snap. 1 vs. 2)</td><td class='num'>{len(vars12)}</td></tr>
    <tr><td>Variacion promedio</td><td class='num'>{prom_var:+.2f}%</td></tr>
    <tr><td>Productos con variacion mayor al 5%</td><td class='num'>{sobre5} ({round(sobre5/len(vars12)*100,1) if vars12 else 0}%)</td></tr>
    <tr><td>Productos con reduccion de precio</td><td class='num'>{bajo0}</td></tr>
  </tbody>
</table>"""

        filas_var = ""
        for v in variaciones[:150]:
            var12_txt = f"{v['var12']:+.1f}%" if v["var12"] is not None else "nd"
            var13_txt = f"{v['var13']:+.1f}%" if v["var13"] is not None else "nd"
            cls12 = "bajo" if isinstance(v["var12"], float) and v["var12"] > 5 else ""
            p1_str = f"$ {v['p1']:,.2f}" if v["p1"] else "nd"
            p2_str = f"$ {v['p2']:,.2f}" if v["p2"] else "nd"
            p3_str = f"$ {v['p3']:,.2f}" if v["p3"] else "nd"
            filas_var += (
                f"<tr><td>{v['site']}</td><td>{v['nombre'][:40]}</td>"
                f"<td class='num'>{p1_str}</td>"
                f"<td class='num'>{p2_str}</td>"
                f"<td class='num'>{p3_str}</td>"
                f"<td class='num {cls12}'>{var12_txt}</td>"
                f"<td class='num'>{var13_txt}</td></tr>"
            )

        tabla_var = f"""
<div class="tabla-scroll">
<table>
  <thead><tr>
    <th>Plataforma</th><th>Producto</th>
    <th>Precio Snap.1</th><th>Precio Snap.2</th><th>Precio Snap.3</th>
    <th>Var. % (1-2)</th><th>Var. % (1-3)</th>
  </tr></thead>
  <tbody>{filas_var}</tbody>
</table>
</div>"""

        return f"""
<div class="seccion">
  <div class="sec-num">6.</div>
  <div class="sec-titulo">Variacion de precios entre cortes temporales</div>
  <div class="sec-desc">Comparacion de precios entre los tres cortes temporales
  del relevamiento (dia 0, dia 7 y dia 14). Formula: Var% = (P2 - P1) / P1 x 100.</div>
  {resumen_var}
  <div class="subtitulo-tabla">Detalle por producto</div>
  {tabla_var}
</div>"""

    def _css(self) -> str:
        return """<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: Arial, Helvetica, sans-serif; font-size: 13px;
       color: #1a1a1a; background: #fff; }
.portada { border-bottom: 2px solid #1a1a1a; padding: 32px 40px 24px;
           max-width: 960px; margin: 0 auto 30px; }
.portada-titulo    { font-size: 20px; font-weight: bold; margin-bottom: 6px; }
.portada-subtitulo { font-size: 15px; margin-bottom: 4px; }
.portada-region    { font-size: 13px; color: #444; margin-bottom: 16px; }
.portada-meta      { font-size: 12px; color: #444; line-height: 1.8; margin-bottom: 14px; }
.nota-anon { font-size: 11px; color: #555; font-style: italic;
             border-left: 3px solid #888; padding-left: 10px; }
.contenido { max-width: 960px; margin: 0 auto; padding: 0 40px 40px; }
.seccion   { margin-bottom: 36px; padding-bottom: 24px;
             border-bottom: 1px solid #ccc; }
.sec-num   { font-size: 11px; font-weight: bold; letter-spacing: .08em;
             text-transform: uppercase; color: #555; margin-bottom: 3px; }
.sec-titulo { font-size: 16px; font-weight: bold; margin-bottom: 6px;
              border-bottom: 1px solid #1a1a1a; padding-bottom: 4px; }
.sec-desc   { font-size: 12px; color: #555; margin: 8px 0 12px;
              line-height: 1.6; }
.subtitulo-tabla { font-size: 13px; font-weight: bold; margin: 16px 0 6px; }
.bloque-dim     { margin-bottom: 20px; }
.dim-titulo     { font-size: 13px; font-weight: bold; background: #f2f2f2;
                  padding: 6px 10px; border-left: 3px solid #1a1a1a;
                  margin-bottom: 6px; }
.tabla-scroll   { overflow-x: auto; }
table  { width: 100%; border-collapse: collapse; font-size: 12px; margin-bottom: 6px; }
th     { background: #1a1a1a; color: #fff; padding: 8px 10px;
         text-align: left; font-weight: bold; font-size: 11px; }
td     { padding: 6px 10px; border-bottom: 1px solid #e0e0e0; }
tr:nth-child(even) td { background: #fafafa; }
.num   { text-align: right; font-family: monospace; }
.caso-id { font-family: monospace; font-size: 11px; white-space: nowrap; }
.alto  { font-weight: bold; }
.medio { }
.bajo  { color: #666; font-style: italic; }
.nd    { color: #aaa; text-align: center; }
.prom  { font-weight: bold; background: #f0f0f0; }
.icc   { border-left: 1px solid #ccc; }
.fila-prom td { background: #f0f0f0; font-weight: bold; }
.nota  { font-size: 11px; color: #555; font-style: italic; margin-top: 10px; line-height: 1.6; }
.nota-fila { text-align: center; color: #888; font-style: italic; }
.leyenda-colores { font-size: 11px; margin-top: 8px; color: #555; }
.leyenda-colores span { margin-right: 16px; }
.pie   { text-align: center; font-size: 11px; color: #888;
         border-top: 1px solid #ccc; padding: 16px 40px;
         max-width: 960px; margin: 0 auto; }
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
