#!/usr/bin/env python3
"""
main.py — Punto de entrada de la herramienta de auditoría académica
====================================================================
Herramienta de relevamiento y auditoría del proceso de compra en sitios
mayoristas de consumo masivo.

Uso:
  python main.py demo                          # Demostración con datos simulados
  python main.py list-sites                    # Listar sitios configurados
  python main.py audit                         # Auditoría QA de todos los sitios
  python main.py audit --site SIM001           # Auditar un sitio específico
  python main.py audit --dimension D3          # Solo auditar una dimensión
  python main.py audit --dry-run               # Simular sin requests reales
  python main.py scrape --site SIM001          # Scraping de catálogo
  python main.py scrape --snapshot 2           # Segundo corte temporal
  python main.py report                        # Generar todos los informes
  python main.py report --format html          # Solo informe HTML
  python main.py report --format console       # Solo reporte en consola
  python main.py report --format csv           # Solo exportación CSV
"""

import sys
import argparse
import logging
from pathlib import Path
from datetime import datetime

# ── Añadir directorio raíz al path (permite imports sin instalar) ──────────────
sys.path.insert(0, str(Path(__file__).parent))

from config import DB_PATH, LOGS_DIR, SITES
from modules.storage import DatabaseManager


# ─────────────────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog        = "auditoria-mayoristas",
        description = "Herramienta académica de auditoría QA + scraping para sitios mayoristas",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Contexto académico:
  Implementa el plan de relevamiento definido en 5 fases para auditar
  el proceso de compra en plataformas mayoristas de consumo masivo,
  combinando técnicas de QA y web scraping ético (respeto de robots.txt,
  rate limiting y registro de transparencia de acceso).

Configuración:
  Los sitios a auditar se definen en config.py → SITES.
  Los casos de prueba QA se definen en config.py → QA_TEST_CASES.
        """
    )
    sub = parser.add_subparsers(dest="command", metavar="COMANDO")

    # ── demo ──────────────────────────────────────────────────────────────────
    sub.add_parser(
        "demo",
        help="Ejecutar demostración completa con datos simulados (no requiere red)"
    )

    # ── list-sites ────────────────────────────────────────────────────────────
    sub.add_parser("list-sites", help="Listar sitios configurados en config.py")

    # ── audit ─────────────────────────────────────────────────────────────────
    p_audit = sub.add_parser("audit", help="Ejecutar auditoría QA del proceso de compra")
    p_audit.add_argument(
        "--site", "-s",
        metavar="ID_O_NOMBRE",
        help="ID o nombre del sitio a auditar (omitir = todos los sitios)"
    )
    p_audit.add_argument(
        "--dimension", "-d",
        metavar="D1..D8",
        help="Auditar solo una dimensión específica (ej: D3)"
    )
    p_audit.add_argument(
        "--dry-run",
        action="store_true",
        help="Simular ejecución sin realizar requests HTTP reales"
    )

    # ── scrape ────────────────────────────────────────────────────────────────
    p_scrape = sub.add_parser("scrape", help="Ejecutar scraping de catálogo de productos")
    p_scrape.add_argument(
        "--site", "-s",
        metavar="ID_O_NOMBRE",
        help="ID o nombre del sitio (omitir = todos)"
    )
    p_scrape.add_argument(
        "--snapshot",
        type=int,
        choices=[1, 2, 3],
        default=1,
        metavar="1|2|3",
        help="Número de corte temporal (1=inicial, 2=7 días, 3=14 días). Default: 1"
    )

    # ── report ────────────────────────────────────────────────────────────────
    p_report = sub.add_parser("report", help="Generar informes a partir de los datos en BD")
    p_report.add_argument(
        "--format", "-f",
        choices=["all", "console", "csv", "html"],
        default="all",
        metavar="all|console|csv|html",
        help="Formato del informe (default: all)"
    )

    return parser


# ─────────────────────────────────────────────────────────────────────────────
def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level   = level,
        format  = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt = "%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOGS_DIR / f"run_{ts}.log", encoding="utf-8"),
        ],
    )
    # Silenciar loggers externos ruidosos
    for noisy in ("urllib3", "requests", "charset_normalizer", "bs4"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# ─────────────────────────────────────────────────────────────────────────────
def cmd_demo(db: DatabaseManager) -> None:
    from modules.demo import run_demo
    run_demo(db)
    # Generar informe inmediatamente después
    from modules.reporter import ReportEngine
    engine = ReportEngine(db)
    engine.generate(fmt="all")


def cmd_list_sites() -> None:
    print(f"\n{'ID':<10} {'Nombre':<28} {'Plataforma':<14} {'URL'}")
    print("─" * 80)
    for s in SITES:
        print(f"  {s['id']:<8} {s['name']:<28} {s.get('platform',''):<14} {s['base_url']}")
    print()


def cmd_audit(db: DatabaseManager, args: argparse.Namespace) -> None:
    from modules.auditor import AuditEngine
    engine = AuditEngine(db)
    try:
        results = engine.run(
            site_filter     = args.site,
            dimension_filter= args.dimension,
            dry_run         = args.dry_run,
        )
    finally:
        engine.close()
    if results:
        print(f"\n  [✓] Auditoría completada. {sum(len(v) for v in results.values())} dimensiones evaluadas.")
        print("  Ejecute 'report' para generar el informe completo.\n")


def cmd_scrape(db: DatabaseManager, args: argparse.Namespace) -> None:
    from modules.scraper import ScrapingEngine
    engine = ScrapingEngine(db)
    engine.run(
        site_filter     = args.site,
        snapshot_number = args.snapshot,
    )
    print("\n  [✓] Scraping completado. Ejecute 'report' para generar el informe.\n")


def cmd_report(db: DatabaseManager, args: argparse.Namespace) -> None:
    from modules.reporter import ReportEngine
    engine = ReportEngine(db)
    engine.generate(fmt=args.format)


# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = build_parser()
    # Parámetro global de verbosidad
    parser.add_argument("--verbose", "-v", action="store_true", help="Logging detallado")
    args = parser.parse_args()

    setup_logging(verbose=getattr(args, "verbose", False))

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    logger = logging.getLogger("main")
    logger.info(f"Iniciando comando: {args.command}")

    # Inicializar base de datos (crea esquema si no existe)
    db = DatabaseManager(DB_PATH)

    # Despachar comando
    dispatch = {
        "demo"      : lambda: cmd_demo(db),
        "list-sites": cmd_list_sites,
        "audit"     : lambda: cmd_audit(db, args),
        "scrape"    : lambda: cmd_scrape(db, args),
        "report"    : lambda: cmd_report(db, args),
    }
    handler = dispatch.get(args.command)
    if handler:
        try:
            handler()
        except KeyboardInterrupt:
            print("\n\n  [!] Operación interrumpida por el usuario.\n")
            sys.exit(0)
        except Exception as exc:
            logger.exception(f"Error inesperado: {exc}")
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
