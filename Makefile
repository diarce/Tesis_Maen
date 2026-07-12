# Makefile — AuditMayorista
# ==========================
# Comandos: make [target]
# Requiere: Python 3.10+, pip

.PHONY: all web demo audit scrape report install clean help

PYTHON  = python3
STREAM  = $(PYTHON) -m streamlit

help:           ## Muestra esta ayuda
	@echo ""
	@echo "  🛒  AuditMayorista — Comandos disponibles"
	@echo "  ─────────────────────────────────────────"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'
	@echo ""

install:        ## Instala dependencias de Python
	$(PYTHON) -m pip install -r requirements.txt

web:            ## Inicia la interfaz Streamlit en http://localhost:8501
	$(STREAM) run app.py

demo:           ## Ejecuta la demo con datos simulados (sin internet)
	$(PYTHON) main.py demo

audit:          ## Auditoría QA de todos los sitios configurados
	$(PYTHON) main.py audit

audit-dry:      ## Auditoría QA simulada (sin requests reales)
	$(PYTHON) main.py audit --dry-run

scrape:         ## Scraping de catálogo (snapshot 1 — día 0)
	$(PYTHON) main.py scrape --snapshot 1

scrape-2:       ## Scraping snapshot 2 (día 7)
	$(PYTHON) main.py scrape --snapshot 2

scrape-3:       ## Scraping snapshot 3 (día 14)
	$(PYTHON) main.py scrape --snapshot 3

report:         ## Genera todos los informes (consola + CSV + HTML)
	$(PYTHON) main.py report

report-html:    ## Genera solo el informe HTML
	$(PYTHON) main.py report --format html

report-csv:     ## Exporta solo los CSV
	$(PYTHON) main.py report --format csv

list:           ## Lista los sitios configurados en config.py
	$(PYTHON) main.py list-sites

clean:          ## Elimina la base de datos y los outputs generados
	@echo "Limpiando outputs..."
	rm -f outputs/audit.db
	rm -f outputs/csv/*.csv
	rm -f outputs/reports/*.html
	rm -f outputs/logs/*.log outputs/logs/*.csv
	rm -f runtime_sites.json
	@echo "✓ Limpieza completa"

check:          ## Verifica la instalación del sistema
	$(PYTHON) -c "\
import sys; \
sys.path.insert(0,'.'); \
from config import QA_TEST_CASES, QA_DIMENSIONS; \
from modules.storage import DatabaseManager; \
from modules.demo import run_demo; \
import json; \
p=json.load(open('data/provincias_localidades.json')); \
e=json.load(open('data/empresas_mayoristas.json')); \
total=sum(len(v) for v in QA_TEST_CASES.values()); \
print(f'✓ {len(QA_DIMENSIONS)} dimensiones | {total} casos QA | {len(p)} provincias | {len(e)} empresas base'); \
print('✓ Sistema listo')"
