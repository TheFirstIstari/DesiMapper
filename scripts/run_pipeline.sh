#!/usr/bin/env bash
# run_pipeline.sh — Full DesiMapper data pipeline
# Usage: bash scripts/run_pipeline.sh [--skip-fetch] [--skip-process]
set -euo pipefail

SKIP_FETCH=false
SKIP_PROCESS=false

for arg in "$@"; do
  case $arg in
    --skip-fetch)   SKIP_FETCH=true ;;
    --skip-process) SKIP_PROCESS=true ;;
  esac
done

echo "╔══════════════════════════════════════╗"
echo "║  DesiMapper — Data Pipeline          ║"
echo "╚══════════════════════════════════════╝"

# Activate mise environment
if command -v mise &> /dev/null; then
  eval "$(mise env)"
fi

if [ "$SKIP_FETCH" = false ]; then
  echo ""
  echo "▶ Step 1: Downloading DESI DR1 clustering catalogs…"
  python pipeline/fetch.py
fi

if [ "$SKIP_PROCESS" = false ]; then
  echo ""
  echo "▶ Step 2: Processing FITS → Parquet…"
  python pipeline/process.py
fi

echo ""
echo "▶ Step 3: Exporting web binary…"
python pipeline/reduce.py

echo ""
echo "✓ Pipeline complete. Web data ready in web/public/data/"
