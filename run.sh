#!/usr/bin/env bash
# run.sh — Arranque del sistema AuditMayorista
# =============================================
# Uso:
#   ./run.sh              → Inicia la interfaz web Streamlit
#   ./run.sh demo         → Ejecuta la demo en modo consola
#   ./run.sh audit        → Auditoría QA en consola
#   ./run.sh report       → Genera informe HTML
#   ./run.sh install      → Instala dependencias

set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# Colores
RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'

banner() {
  echo -e "${BLUE}"
  echo "  ╔══════════════════════════════════════════╗"
  echo "  ║  🛒  AuditMayorista — Sistema académico  ║"
  echo "  ║     Auditoría de e-commerce mayorista    ║"
  echo "  ╚══════════════════════════════════════════╝"
  echo -e "${NC}"
}

check_python() {
  if ! command -v python3 &>/dev/null; then
    echo -e "${RED}✗ Python 3 no encontrado. Instalá Python 3.10+${NC}"
    exit 1
  fi
  PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
  echo -e "${GREEN}✓ Python $PY_VER${NC}"
}

install_deps() {
  echo "Instalando dependencias..."
  python3 -m pip install -r requirements.txt --quiet
  echo -e "${GREEN}✓ Dependencias instaladas${NC}"
}

CMD="${1:-web}"

banner
check_python

case "$CMD" in
  install)
    install_deps
    ;;
  web|"")
    echo -e "${GREEN}Iniciando interfaz web en http://localhost:8501${NC}\n"
    python3 -m streamlit run app.py
    ;;
  demo)
    echo "Ejecutando demo con datos simulados..."
    python3 main.py demo
    ;;
  audit)
    echo "Ejecutando auditoría QA..."
    python3 main.py audit "${@:2}"
    ;;
  scrape)
    echo "Ejecutando scraping..."
    python3 main.py scrape "${@:2}"
    ;;
  report)
    echo "Generando informes..."
    python3 main.py report "${@:2}"
    ;;
  list)
    python3 main.py list-sites
    ;;
  *)
    echo "Uso: ./run.sh [web|demo|audit|scrape|report|list|install]"
    exit 1
    ;;
esac
