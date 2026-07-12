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


# ── ICC: única fuente de verdad ────────────────────────────────────────────────
def calcular_icc_ponderado(dim_data: dict, pesos: dict) -> float:
    """
    Única función de cálculo del Indice de Calidad Compuesto (ICC) para todo
    el sistema (informe HTML, vistas previas SVG y panel en vivo de la app).

    Formula: ICC = Σ(S_k × w_k) / Σw_k, sobre las dimensiones k presentes.

    dim_data: {dimension_id: {"avg_compliance": float, ...}} o
              {dimension_id: float} — admite ambas formas.
    pesos   : {dimension_id: peso}

    IMPORTANTE: toda sección que muestre un "ICC" o "Índice" debe llamar a esta
    función. Antes de esta unificación existían 3 implementaciones divergentes
    (una ponderada correcta y dos que usaban promedio aritmético simple),
    que producían valores distintos para el mismo sitio en distintas vistas
    del mismo informe — ver auditoría de coherencia previa.
    """
    def _valor(v):
        return v["avg_compliance"] if isinstance(v, dict) else v

    presentes = [d for d in pesos if d in dim_data]
    if not presentes:
        return 0.0
    wsum = sum(_valor(dim_data[d]) * pesos[d] for d in presentes)
    pw   = sum(pesos[d] for d in presentes)
    return round(wsum / pw, 2) if pw else 0.0


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

    def generate(self, site_ids: list[str] | None = None) -> Path:
        """
        site_ids: lista opcional de site_id a incluir en el informe (la
        selección/corrida ACTUAL del usuario). Si se omite (None), se
        conserva el comportamiento historico: todos los sitios con
        resultados en la base de datos (uso desde CLI sin selección
        explícita — ver nota en _build_html).
        """
        ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_file = self.output_dir / f"informe_auditoria_{ts}.html"
        html     = self._build_html(site_ids=site_ids)
        out_file.write_text(html, encoding="utf-8")
        logger.info(f"[HTML] Informe generado: {out_file}"
                    + (f" (acotado a {len(site_ids)} sitio(s))" if site_ids is not None else ""))
        return out_file

    # ── Construcción del HTML ──────────────────────────────────────────────────

    def _build_html(self, site_ids: list[str] | None = None) -> str:
        sites    = self.db.get_sites()
        scores   = self.db.get_dimension_scores()
        results  = self.db.get_audit_results()
        products = self.db.get_products()
        history  = self.db.get_price_history()
        ts_str   = datetime.now().strftime("%d/%m/%Y %H:%M")

        by_site_scores: dict[str, dict] = {}
        for row in scores:
            by_site_scores.setdefault(row["site_id"], {})[row["dimension_id"]] = row

        # CRÍTICO: solo incluir sitios que tienen resultados reales en la BD.
        # Evita que registros huérfanos de sesiones anteriores aparezcan en el informe.
        ids_con_resultados = set(by_site_scores.keys())

        # CRÍTICO (coherencia con el requerimiento del usuario): si se indica
        # explícitamente el conjunto de sitios de la corrida ACTUAL (site_ids),
        # el informe se acota exclusivamente a esos sitios, aunque existan en
        # la base de datos otros sitios con resultados de corridas anteriores.
        # Si site_ids es None (p. ej. CLI 'report' sin selección explícita),
        # se conserva el comportamiento previo: todos los sitios con
        # resultados reales. El tratamiento integral de históricos multi-sesión
        # queda pendiente para una próxima iteración.
        if site_ids is not None:
            ids_objetivo = ids_con_resultados & set(site_ids)
        else:
            ids_objetivo = ids_con_resultados

        sites          = [s for s in sites if s["id"] in ids_objetivo]
        by_site_scores = {sid: d for sid, d in by_site_scores.items() if sid in ids_objetivo}
        scores         = [row for row in scores if row["site_id"] in ids_objetivo]
        results        = [r for r in results if r["site_id"] in ids_objetivo]
        products       = [p for p in products if p["site_id"] in ids_objetivo]
        history        = [h for h in history if h["site_id"] in ids_objetivo]

        n_casos  = len(set(r["test_case_id"] for r in results)) if results else 0

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
{self._section_barras_icc(sites, by_site_scores)}
{self._section_radar_multi(sites, by_site_scores)}
{self._section_matriz(sites, by_site_scores)}
{self._section_heatmap_casos(sites, results)}
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
            icc = calcular_icc_ponderado(dim_data, pesos) if vals else 0
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
        # ICC promedio (misma función compartida, sobre los promedios por dimensión)
        prom_por_dim = {d: (sum(col_sumas[d]) / len(col_sumas[d]))
                        for d in dim_ids if col_sumas[d]}
        icc_prom = calcular_icc_ponderado(prom_por_dim, pesos) if prom_por_dim else 0
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

    def _section_barras_icc(self, sites: list, by_site_scores: dict) -> str:
        """Grafico de barras horizontales del Indice de Calidad Compuesto."""
        if not by_site_scores:
            return ""
        site_map = build_anon_map(sites)
        pesos    = {d: QA_DIMENSIONS[d]["weight"] for d in QA_DIMENSIONS}

        items = []
        for sid, dim_data in sorted(by_site_scores.items()):
            icc = calcular_icc_ponderado(dim_data, pesos)
            items.append((site_map.get(sid, sid), icc))

        # SVG
        bw, bh, gap = 380, 28, 10
        pad_l = 130
        escala = bw / 3.0
        total_h = (bh + gap) * len(items) + 60
        vw = pad_l + bw + 80

        barras = ""
        for i, (nombre, icc) in enumerate(items):
            y    = 30 + i * (bh + gap)
            ancho= round(icc * escala, 1)
            fill = "#1a1a1a" if icc >= 2.5 else ("#666" if icc >= 1.5 else "#bbb")
            txt_col = "white" if icc >= 1.5 else "#333"
            barras += f'''
  <text x="{pad_l - 6}" y="{y + bh//2 + 4}" text-anchor="end"
        font-size="11" fill="#333">{nombre}</text>
  <rect x="{pad_l}" y="{y}" width="{ancho}" height="{bh}"
        fill="{fill}" rx="2"/>
  <text x="{pad_l + ancho + 5}" y="{y + bh//2 + 4}"
        font-size="11" fill="#1a1a1a" font-weight="bold">{icc:.2f}</text>'''

        # Lineas de referencia en 1, 1.5, 2, 2.5, 3
        refs = ""
        for v in [1.0, 1.5, 2.0, 2.5, 3.0]:
            xr = pad_l + round(v * escala)
            refs += f'''
  <line x1="{xr}" y1="15" x2="{xr}" y2="{total_h - 30}"
        stroke="{'#999' if v in (1.5,2.5) else '#ddd'}"
        stroke-width="{'1.5' if v in (1.5,2.5) else '0.8'}"
        stroke-dasharray="{'4,3' if v in (1.5,2.5) else 'none'}"/>
  <text x="{xr}" y="12" text-anchor="middle" font-size="9" fill="#888">{v:.1f}</text>'''

        # Leyenda de rangos
        leyenda = f"""
  <rect x="{pad_l}" y="{total_h - 22}" width="{round(1.5*escala)}" height="10" fill="#bbb"/>
  <text x="{pad_l + 4}" y="{total_h - 14}" font-size="8" fill="#555">Critico (&lt;1,5)</text>
  <rect x="{pad_l + round(1.5*escala) + 60}" y="{total_h - 22}" width="{round(escala)}" height="10" fill="#666"/>
  <text x="{pad_l + round(1.5*escala) + 64}" y="{total_h - 14}" font-size="8" fill="#555">Parcial (1,5–2,5)</text>
  <rect x="{pad_l + round(2.5*escala) + 130}" y="{total_h - 22}" width="{round(0.5*escala)}" height="10" fill="#1a1a1a"/>
  <text x="{pad_l + round(2.5*escala) + 134}" y="{total_h - 14}" font-size="8" fill="#555">Pleno (≥2,5)</text>"""

        svg = f"""<svg viewBox="0 0 {vw} {total_h}" width="100%"
     xmlns="http://www.w3.org/2000/svg" role="img"
     aria-label="Grafico de barras del Indice de Calidad Compuesto por plataforma">
  {refs}
  {barras}
  {leyenda}
</svg>"""
        return f"""
<div class="seccion">
  <div class="sec-num">3.</div>
  <div class="sec-titulo">Indice de Calidad Compuesto (ICC) por plataforma</div>
  <div class="sec-desc">El ICC es la media ponderada de los ocho scores dimensionales.
  Formula: ICC(i) = &sum;(S&#7522;&#8317;k&#8318; &times; w&#7522;) / &sum;w&#7522;,
  donde la suma de pesos es 11,5. Ninguna plataforma alcanza cumplimiento pleno (≥ 2,5).</div>
  <div class="vis-wrap">{svg}</div>
  <div class="nota">Lineas de referencia: 1,5 = umbral critico / parcial | 2,5 = umbral parcial / pleno.
  Barras mas oscuras indican mayor nivel de cumplimiento.</div>
</div>"""

    def _section_radar_multi(self, sites: list, by_site_scores: dict) -> str:
        """Grafico de radar con todas las plataformas superpuestas."""
        if not by_site_scores:
            return ""

        site_map = build_anon_map(sites)
        dim_ids  = sorted(QA_DIMENSIONS.keys())
        pesos_radar = {d: QA_DIMENSIONS[d]["weight"] for d in dim_ids}
        N        = len(dim_ids)
        cx, cy   = 220, 215
        r_max    = 140

        angles = [math.pi / 2 - 2 * math.pi * i / N for i in range(N)]

        # Anillos de referencia
        rings = ""
        for lvl in [1, 2, 3]:
            pts = " ".join(
                f"{cx + r_max*(lvl/3)*math.cos(a):.1f},"
                f"{cy - r_max*(lvl/3)*math.sin(a):.1f}"
                for a in angles
            )
            lw = "1" if lvl == 3 else "0.7"
            lc = "#ccc" if lvl < 3 else "#999"
            rings += f'<polygon points="{pts}" fill="none" stroke="{lc}" stroke-width="{lw}"/>'
            yr   = cy - r_max * (lvl/3) - 3
            rings += f'<text x="{cx+4}" y="{yr:.0f}" font-size="8" fill="#aaa">{lvl}</text>'

        # Ejes y etiquetas
        axes = ""
        for a, did in zip(angles, dim_ids):
            x2  = cx + r_max * math.cos(a)
            y2  = cy - r_max * math.sin(a)
            axes += f'<line x1="{cx}" y1="{cy}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#ddd" stroke-width="0.8"/>'
            lx  = cx + (r_max + 22) * math.cos(a)
            ly  = cy - (r_max + 22) * math.sin(a)
            ca  = math.cos(a)
            ta  = "middle" if abs(ca) < 0.25 else ("start" if ca > 0 else "end")
            nombre_corto = QA_DIMENSIONS.get(did, {}).get("name", did)[:10]
            axes += (f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="9" fill="#222" '
                     f'text-anchor="{ta}" font-weight="bold">{did}</text>')
            axes += (f'<text x="{lx:.1f}" y="{ly+11:.1f}" font-size="7.5" fill="#555" '
                     f'text-anchor="{ta}">{nombre_corto}</text>')

        # Estilos por plataforma (grayscale, distinguibles en impresion)
        estilos = [
            ("rgba(20,20,20,0.12)", "#1a1a1a", "2",   "none",    "circle",  "#1a1a1a"),
            ("rgba(80,80,80,0.10)", "#555555", "1.8", "6,3",     "square",  "#555555"),
            ("rgba(140,140,140,0.10)", "#999",  "1.5", "3,3",    "diamond", "#999999"),
        ]

        poligonos = ""
        leyenda_items = ""

        for idx, (sid, dim_data) in enumerate(sorted(by_site_scores.items())):
            fill_col, stk_col, sw, dash, symbol, leg_col = estilos[idx % len(estilos)]
            values = [dim_data.get(d, {}).get("avg_compliance", 0) for d in dim_ids]
            pts = " ".join(
                f"{cx + r_max*(v/3)*math.cos(a):.1f},{cy - r_max*(v/3)*math.sin(a):.1f}"
                for a, v in zip(angles, values)
            )
            da  = f'stroke-dasharray="{dash}"' if dash != "none" else ""
            poligonos += (f'<polygon points="{pts}" '
                          f'fill="{fill_col}" stroke="{stk_col}" '
                          f'stroke-width="{sw}" {da}/>')

            # Puntos en los vértices
            for a, v in zip(angles, values):
                xp = cx + r_max * (v/3) * math.cos(a)
                yp = cy - r_max * (v/3) * math.sin(a)
                poligonos += f'<circle cx="{xp:.1f}" cy="{yp:.1f}" r="3" fill="{stk_col}"/>'

            nombre = site_map.get(sid, sid)
            icc    = calcular_icc_ponderado(dim_data, pesos_radar)
            ly_leg = 55 + idx * 28
            da_leg = f'stroke-dasharray="{dash}"' if dash != "none" else ""
            leyenda_items += (
                f'<line x1="460" y1="{ly_leg}" x2="500" y2="{ly_leg}" '
                f'stroke="{stk_col}" stroke-width="{sw}" {da_leg}/>'
                f'<circle cx="480" cy="{ly_leg}" r="3" fill="{stk_col}"/>'
                f'<text x="506" y="{ly_leg+4}" font-size="10" fill="#222">'
                f'{nombre}</text>'
                f'<text x="506" y="{ly_leg+16}" font-size="9" fill="#555">'
                f'ICC: {icc:.2f}</text>'
            )

        # Promedio general
        prom_vals = []
        for d in dim_ids:
            vals_d = [dim_data.get(d, {}).get("avg_compliance", 0)
                      for dim_data in by_site_scores.values()]
            prom_vals.append(sum(vals_d)/len(vals_d) if vals_d else 0)
        pts_prom = " ".join(
            f"{cx + r_max*(v/3)*math.cos(a):.1f},{cy - r_max*(v/3)*math.sin(a):.1f}"
            for a, v in zip(angles, prom_vals)
        )
        poligonos += (f'<polygon points="{pts_prom}" fill="none" stroke="#333" '
                      f'stroke-width="2.5" stroke-dasharray="8,3" opacity="0.6"/>')
        prom_icc = calcular_icc_ponderado(dict(zip(dim_ids, prom_vals)), pesos_radar)
        leyenda_items += (
            f'<line x1="460" y1="145" x2="500" y2="145" stroke="#333" '
            f'stroke-width="2.5" stroke-dasharray="8,3" opacity="0.6"/>'
            f'<text x="506" y="149" font-size="10" fill="#222">Promedio general</text>'
            f'<text x="506" y="161" font-size="9" fill="#555">ICC: {prom_icc:.2f}</text>'
        )

        svg = f"""<svg viewBox="0 0 700 440" width="100%"
     xmlns="http://www.w3.org/2000/svg" role="img"
     aria-label="Grafico de radar multisitio con 8 dimensiones de auditoria QA">
  {rings}
  {axes}
  {poligonos}
  {leyenda_items}
  <text x="220" y="420" text-anchor="middle" font-size="9" fill="#777"
        font-style="italic">
    Escala 0-3 | Cuanto mas grande el poligono, mayor nivel de cumplimiento
  </text>
</svg>"""

        return f"""
<div class="seccion">
  <div class="sec-num">4.</div>
  <div class="sec-titulo">Perfil de cumplimiento por dimension — Grafico de radar</div>
  <div class="sec-desc">Cada poligono representa el perfil de una plataforma auditada
  en las ocho dimensiones de analisis. Las plataformas con mayor superficie ocupada
  presentan mayor madurez funcional. La linea discontinua gruesa representa el
  promedio del conjunto relevado.</div>
  <div class="vis-wrap">{svg}</div>
  <div class="nota">Anillos de referencia: 1 (critico), 2 (parcial), 3 (pleno).
  Los poligonos se diferencian por tipo de linea para facilitar la lectura en impresion en escala de grises.</div>
</div>"""

    def _section_heatmap_casos(self, sites: list, results: list) -> str:
        """Mapa de calor: casos de prueba (filas) x plataformas (columnas)."""
        if not results:
            return ""

        site_map = build_anon_map(sites)
        site_ids = sorted({r["site_id"] for r in results})
        site_cols= [site_map.get(sid, sid) for sid in site_ids]

        # Organizar: {dim_id: {test_case_id: {site_id: compliance}}}
        # y metodo de verificacion por celda: {dim: {tc: {site: metodo}}}
        datos: dict = {}
        metodos: dict = {}
        nombres_tc: dict = {}
        for r in results:
            datos.setdefault(r["dimension_id"], {})\
                 .setdefault(r["test_case_id"], {})[r["site_id"]] = r["compliance"]
            metodos.setdefault(r["dimension_id"], {})\
                   .setdefault(r["test_case_id"], {})[r["site_id"]] = \
                   r.get("verification_method", "estatico")
            nombres_tc[r["test_case_id"]] = r["test_case_name"][:28]

        # Conteo global por metodo (para la nota de transparencia)
        n_total       = len(results)
        n_reclasif    = sum(1 for r in results
                            if r.get("verification_method") == "js_rendered")
        n_confirmados = sum(1 for r in results
                            if r.get("verification_method") == "estatico_confirmado_js")

        # Colores de la escala (azul academico: mas oscuro = mayor cumplimiento)
        colores  = {0: "#f0f0f0", 1: "#c8d8e8", 2: "#5a8fb5", 3: "#1a4a6e"}
        txt_cols = {0: "#888",    1: "#333",    2: "#fff",    3: "#fff"}

        # CSS de cabeceras rotadas y tabla compacta
        col_w    = max(80, min(130, 600 // max(len(site_ids), 1)))
        leyenda_html = "".join(
            f'<span style="display:inline-block;width:14px;height:14px;'
            f'background:{colores[v]};border:1px solid #ccc;'
            f'vertical-align:middle;margin-right:3px;"></span>'
            f'<span style="font-size:11px;margin-right:12px;">{t}</span>'
            for v, t in [(3,"Pleno (3)"),(2,"Parcial (2)"),(1,"No cumple (1)"),(0,"N/A (0)")]
        )

        tablas_html = ""
        for did in sorted(datos.keys()):
            dim_nombre = QA_DIMENSIONS.get(did, {}).get("name", did)
            filas = ""
            for tcid in sorted(datos[did].keys()):
                nombre_tc = nombres_tc.get(tcid, tcid)
                celdas = ""
                for sid in site_ids:
                    v   = datos[did][tcid].get(sid)
                    if v is None:
                        celdas += f'<td class="hm-cell" style="background:#f8f8f8;color:#ccc;">-</td>'
                    else:
                        bg  = colores.get(v, "#f0f0f0")
                        fc  = txt_cols.get(v, "#333")
                        tip = ["N/A","No cumple","Parcial","Pleno"][v]
                        met = metodos[did][tcid].get(sid, "estatico")
                        # Marcadores de transparencia metodologica:
                        #  * = reclasificado (solo detectable con JS renderizado)
                        #  † = "No cumple" confirmado tambien con navegador real
                        if met == "js_rendered":
                            marca, tip = "*", tip + " — reclasificado tras renderizado JS"
                        elif met == "estatico_confirmado_js":
                            marca, tip = "&dagger;", tip + " — confirmado con navegador real"
                        else:
                            marca = ""
                        celdas += (f'<td class="hm-cell" style="background:{bg};color:{fc};" '
                                   f'title="{tip}">{v}{marca}</td>')
                filas += f'<tr><td class="hm-tc">{tcid}</td><td class="hm-nombre">{nombre_tc}</td>{celdas}</tr>'

            enc = "".join(
                f'<th class="hm-th" style="min-width:{col_w}px">{col}</th>'
                for col in site_cols
            )
            tablas_html += f"""
<div class="bloque-dim">
  <div class="dim-titulo">{did} — {dim_nombre}</div>
  <div class="tabla-scroll">
  <table class="hm-table">
    <thead><tr>
      <th class="hm-tc" style="text-align:left">ID</th>
      <th class="hm-nombre" style="text-align:left">Indicador</th>
      {enc}
    </tr></thead>
    <tbody>{filas}</tbody>
  </table>
  </div>
</div>"""

        # Nota de transparencia metodologica sobre el metodo de verificacion
        if n_reclasif or n_confirmados:
            nota_metodo = (
                f'<div class="nota"><b>Método de verificación:</b> relevamiento '
                f'estático (requests + análisis de HTML) con reverificación mediante '
                f'navegador real (Playwright/Chromium, con ejecución de JavaScript) '
                f'para los indicadores DOM-dependientes clasificados inicialmente '
                f'como "No cumple". De {n_total} observaciones: '
                f'{n_reclasif} indicador(es) reclasificados tras el renderizado '
                f'(marcados con *, falsos negativos del método estático) y '
                f'{n_confirmados} indicador(es) "No cumple" confirmados también '
                f'con navegador real (marcados con &dagger;).</div>'
            )
        else:
            nota_metodo = (
                '<div class="nota"><b>Método de verificación:</b> relevamiento '
                'estático únicamente (requests + análisis de HTML, sin ejecución '
                'de JavaScript). Limitación metodológica: en plataformas que '
                'renderizan contenido del lado del cliente (SPA), los indicadores '
                'DOM-dependientes clasificados como "No cumple" pueden incluir '
                'falsos negativos. La reverificación con navegador real puede '
                'habilitarse en los parámetros metodológicos de la aplicación.</div>'
            )

        return f"""
<div class="seccion">
  <div class="sec-num">6.</div>
  <div class="sec-titulo">Mapa de calor — Detalle de indicadores por plataforma</div>
  <div class="sec-desc">Cada celda indica el valor de cumplimiento obtenido por cada
  plataforma en cada indicador evaluado. La intensidad del color refleja el nivel
  de cumplimiento: azul oscuro = pleno, azul medio = parcial, azul claro = no cumple,
  gris = no aplica.</div>
  <div style="margin:8px 0 14px">{leyenda_html}</div>
  {tablas_html}
  {nota_metodo}
  <div class="nota">Los valores 0 corresponden a indicadores no verificables en la sesion
  de relevamiento (p. ej. paginas que requieren autenticacion previa para ser auditadas).</div>
</div>"""


    # ── Métodos SVG puros para renderizado en Streamlit ───────────────────────

    def _seccion_barras_svg(self, sites: list, by_site_scores: dict) -> str:
        """Solo el SVG del gráfico de barras ICC (sin wrapper .seccion)."""
        if not by_site_scores:
            return "<p>Sin datos.</p>"
        site_map = build_anon_map(sites)
        pesos    = {d: QA_DIMENSIONS[d]["weight"] for d in QA_DIMENSIONS}

        items = []
        for sid, dim_data in sorted(by_site_scores.items()):
            icc = calcular_icc_ponderado(dim_data, pesos)
            items.append((site_map.get(sid, sid), icc))

        bw, bh, gap = 360, 30, 12
        pad_l = 140
        escala  = bw / 3.0
        total_h = (bh + gap) * len(items) + 70
        vw      = pad_l + bw + 80

        barras = ""
        for i, (nombre, icc) in enumerate(items):
            y     = 30 + i * (bh + gap)
            ancho = round(icc * escala, 1)
            fill  = "#1a1a1a" if icc >= 2.5 else ("#666" if icc >= 1.5 else "#bbb")
            barras += (
                f'<text x="{pad_l-8}" y="{y+bh//2+4}" text-anchor="end" '
                f'font-size="11" fill="#333">{nombre}</text>'
                f'<rect x="{pad_l}" y="{y}" width="{ancho}" height="{bh}" '
                f'fill="{fill}" rx="2"/>'
                f'<text x="{pad_l+ancho+5}" y="{y+bh//2+4}" '
                f'font-size="11" fill="#1a1a1a" font-weight="bold">{icc:.2f}</text>'
            )

        refs = ""
        for v in [1.0, 1.5, 2.0, 2.5, 3.0]:
            xr = pad_l + round(v * escala)
            dash = "4,3" if v in (1.5, 2.5) else "none"
            col  = "#888" if v in (1.5, 2.5) else "#ddd"
            refs += (
                f'<line x1="{xr}" y1="18" x2="{xr}" y2="{total_h-25}" '
                f'stroke="{col}" stroke-width="1" stroke-dasharray="{dash}"/>'
                f'<text x="{xr}" y="14" text-anchor="middle" font-size="9" fill="#999">{v:.1f}</text>'
            )

        return (
            f'<svg viewBox="0 0 {vw} {total_h}" width="100%" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f'{refs}{barras}'
            f'<text x="{pad_l}" y="{total_h-8}" font-size="9" fill="#888" font-style="italic">'
            f'Escala 0-3 | Referencia: 1,5 critico/parcial — 2,5 parcial/pleno</text>'
            f'</svg>'
        )

    def _seccion_radar_svg(self, sites: list, by_site_scores: dict) -> str:
        """Solo el SVG del radar multi-sitio (sin wrapper .seccion)."""
        if not by_site_scores:
            return "<p>Sin datos.</p>"
        site_map = build_anon_map(sites)
        dim_ids  = sorted(QA_DIMENSIONS.keys())
        pesos    = {d: QA_DIMENSIONS[d]["weight"] for d in dim_ids}
        N        = len(dim_ids)
        cx, cy   = 210, 205
        r_max    = 135

        angles = [math.pi / 2 - 2 * math.pi * i / N for i in range(N)]

        rings = ""
        for lvl in [1, 2, 3]:
            pts = " ".join(
                f"{cx+r_max*(lvl/3)*math.cos(a):.1f},{cy-r_max*(lvl/3)*math.sin(a):.1f}"
                for a in angles
            )
            rings += (f'<polygon points="{pts}" fill="none" '
                      f'stroke="{"#bbb" if lvl<3 else "#999"}" stroke-width="0.8"/>')
            rings += (f'<text x="{cx+4}" y="{cy-r_max*(lvl/3)-3:.0f}" '
                      f'font-size="8" fill="#aaa">{lvl}</text>')

        axes = ""
        for a, did in zip(angles, dim_ids):
            x2, y2 = cx+r_max*math.cos(a), cy-r_max*math.sin(a)
            axes += f'<line x1="{cx}" y1="{cy}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#ddd" stroke-width="0.8"/>'
            lx = cx+(r_max+20)*math.cos(a)
            ly = cy-(r_max+20)*math.sin(a)
            ca = math.cos(a)
            ta = "middle" if abs(ca)<0.25 else ("start" if ca>0 else "end")
            nm = QA_DIMENSIONS.get(did,{}).get("name","")[:10]
            axes += (f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="9" fill="#222" '
                     f'text-anchor="{ta}" font-weight="bold">{did}</text>')
            axes += (f'<text x="{lx:.1f}" y="{ly+11:.1f}" font-size="7.5" fill="#555" '
                     f'text-anchor="{ta}">{nm}</text>')

        estilos = [
            ("rgba(20,20,20,.12)",  "#1a1a1a", "2",   "none"),
            ("rgba(80,80,80,.10)",  "#555",    "1.8", "6,3"),
            ("rgba(140,140,140,.10)","#999",   "1.5", "3,3"),
        ]
        poligs = ""
        leyenda = ""
        for idx, (sid, dim_data) in enumerate(sorted(by_site_scores.items())):
            fc, stk, sw, dash = estilos[idx % len(estilos)]
            vals = [dim_data.get(d,{}).get("avg_compliance",0) for d in dim_ids]
            pts  = " ".join(
                f"{cx+r_max*(v/3)*math.cos(a):.1f},{cy-r_max*(v/3)*math.sin(a):.1f}"
                for a,v in zip(angles,vals)
            )
            da = f'stroke-dasharray="{dash}"' if dash!="none" else ""
            poligs += (f'<polygon points="{pts}" fill="{fc}" stroke="{stk}" '
                       f'stroke-width="{sw}" {da}/>')
            for a,v in zip(angles,vals):
                xp,yp = cx+r_max*(v/3)*math.cos(a), cy-r_max*(v/3)*math.sin(a)
                poligs += f'<circle cx="{xp:.1f}" cy="{yp:.1f}" r="3" fill="{stk}"/>'
            icc    = calcular_icc_ponderado(dim_data, pesos)
            nombre = site_map.get(sid,sid)
            ly_l   = 50 + idx*28
            da_l   = f'stroke-dasharray="{dash}"' if dash!="none" else ""
            leyenda += (
                f'<line x1="440" y1="{ly_l}" x2="470" y2="{ly_l}" '
                f'stroke="{stk}" stroke-width="{sw}" {da_l}/>'
                f'<circle cx="455" cy="{ly_l}" r="3" fill="{stk}"/>'
                f'<text x="476" y="{ly_l+4}" font-size="10" fill="#222">{nombre}</text>'
                f'<text x="476" y="{ly_l+16}" font-size="9" fill="#666">ICC: {icc:.2f}</text>'
            )

        prom_vals = [
            sum(by_site_scores[sid].get(d,{}).get("avg_compliance",0)
                for sid in by_site_scores) / len(by_site_scores)
            for d in dim_ids
        ]
        pts_p = " ".join(
            f"{cx+r_max*(v/3)*math.cos(a):.1f},{cy-r_max*(v/3)*math.sin(a):.1f}"
            for a,v in zip(angles,prom_vals)
        )
        prom_icc = round(sum(prom_vals)/len(prom_vals),2)
        poligs  += (f'<polygon points="{pts_p}" fill="none" stroke="#333" '
                    f'stroke-width="2.5" stroke-dasharray="8,3" opacity=".6"/>')
        leyenda += (
            f'<line x1="440" y1="145" x2="470" y2="145" stroke="#333" '
            f'stroke-width="2.5" stroke-dasharray="8,3" opacity=".6"/>'
            f'<text x="476" y="149" font-size="10" fill="#222">Promedio</text>'
            f'<text x="476" y="161" font-size="9" fill="#666">ICC: {prom_icc:.2f}</text>'
        )
        return (
            f'<svg viewBox="0 0 660 420" width="100%" xmlns="http://www.w3.org/2000/svg">'
            f'{rings}{axes}{poligs}{leyenda}'
            f'<text x="210" y="408" text-anchor="middle" font-size="9" fill="#888" '
            f'font-style="italic">Escala 0-3 | Mayor superficie = mayor madurez funcional</text>'
            f'</svg>'
        )

    def _seccion_heatmap_html(self, sites: list, results: list) -> str:
        """Solo la tabla HTML del heatmap (sin wrapper .seccion)."""
        if not results:
            return "<p>Sin datos.</p>"
        site_map = build_anon_map(sites)
        site_ids = sorted({r["site_id"] for r in results})
        cols     = [site_map.get(sid, sid) for sid in site_ids]

        datos: dict = {}
        nombres: dict = {}
        for r in results:
            datos.setdefault(r["dimension_id"],{})                 .setdefault(r["test_case_id"],{})[r["site_id"]] = r["compliance"]
            nombres[r["test_case_id"]] = r["test_case_name"][:30]

        colores  = {0:"#f0f0f0",1:"#c8d8e8",2:"#5a8fb5",3:"#1a4a6e"}
        txt_cols = {0:"#999",   1:"#333",   2:"#fff",   3:"#fff"}

        leyenda = "".join(
            f'<span style="display:inline-flex;align-items:center;gap:4px;margin-right:14px">'
            f'<span style="width:14px;height:14px;background:{colores[v]};border:1px solid #ccc;display:inline-block"></span>'
            f'<span style="font-size:11px">{t}</span></span>'
            for v,t in [(3,"Pleno (3)"),(2,"Parcial (2)"),(1,"No cumple (1)"),(0,"N/A")]
        )

        tablas = ""
        for did in sorted(datos.keys()):
            dim_nombre = QA_DIMENSIONS.get(did,{}).get("name",did)
            enc = "".join(
                f'<th style="background:#1a1a1a;color:#fff;padding:5px 10px;'
                f'font-size:10px;text-align:center">{c}</th>' for c in cols
            )
            filas = ""
            for tcid in sorted(datos[did].keys()):
                celdas = ""
                for sid in site_ids:
                    v  = datos[did][tcid].get(sid)
                    bg = colores.get(v,"#f0f0f0") if v is not None else "#f8f8f8"
                    fc = txt_cols.get(v,"#aaa")   if v is not None else "#ccc"
                    vt = str(v) if v is not None else "-"
                    tp = ["N/A","No cumple","Parcial","Pleno"][v] if v is not None else "nd"
                    celdas += (f'<td title="{tp}" style="background:{bg};color:{fc};'
                               f'text-align:center;padding:4px 10px;font-family:monospace;'
                               f'font-size:11px;font-weight:bold;border-bottom:1px solid #eee">'
                               f'{vt}</td>')
                filas += (f'<tr><td style="font-family:monospace;font-size:10px;'
                          f'padding:4px 6px;white-space:nowrap;border-bottom:1px solid #eee">'
                          f'{tcid}</td>'
                          f'<td style="font-size:11px;padding:4px 8px;min-width:180px;'
                          f'border-bottom:1px solid #eee">{nombres.get(tcid,"")}</td>'
                          f'{celdas}</tr>')
            tablas += (
                f'<div style="margin-bottom:20px">'
                f'<div style="font-size:13px;font-weight:bold;background:#f2f2f2;'
                f'padding:6px 10px;border-left:3px solid #1a1a1a;margin-bottom:6px">'
                f'{did} — {dim_nombre}</div>'
                f'<div style="overflow-x:auto"><table style="border-collapse:collapse;'
                f'font-size:12px;width:auto"><thead><tr>'
                f'<th style="background:#1a1a1a;color:#fff;padding:5px 6px;font-size:10px;'
                f'text-align:left">ID</th>'
                f'<th style="background:#1a1a1a;color:#fff;padding:5px 8px;font-size:10px;'
                f'text-align:left">Indicador</th>'
                f'{enc}</tr></thead><tbody>{filas}</tbody></table></div></div>'
            )
        return f'<div style="margin-bottom:8px">{leyenda}</div>{tablas}'


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

.vis-wrap      { margin: 14px 0; overflow-x: auto; }
.vis-wrap svg  { max-width: 100%; height: auto; display: block; }
.hm-table      { border-collapse: collapse; font-size: 11px; width: auto; }
.hm-table thead th { background: #1a1a1a; color: #fff;
                      padding: 6px 8px; font-size: 10px; }
.hm-tc         { font-family: monospace; font-size: 10px; padding: 4px 6px;
                  white-space: nowrap; border-bottom: 1px solid #eee; }
.hm-nombre     { font-size: 11px; padding: 4px 8px; border-bottom: 1px solid #eee;
                  min-width: 180px; }
.hm-cell       { text-align: center; padding: 4px 10px; font-family: monospace;
                  font-size: 11px; font-weight: bold;
                  border-bottom: 1px solid #eee; cursor: default; }
.hm-th         { text-align: center !important; font-size: 10px !important; }
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

    def generate(self, fmt: str = "all", site_ids: list[str] | None = None) -> None:
        """
        Genera los informes según el formato solicitado.
        fmt: 'console' | 'csv' | 'html' | 'all'
        site_ids: sitios de la corrida ACTUAL a incluir en el informe HTML
                  (ver HTMLReporter._build_html). None = comportamiento
                  historico sin cambios (uso desde CLI).
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
            html_file = self.html_reporter.generate(site_ids=site_ids)
            print(f"\n  Informe HTML: {html_file}\n")
