#!/usr/bin/env bash
# deploy.sh — Deploy DesiMapper web viewer via Azure VM → Tailscale → Fedora MiniPC
#
# Network topology:
#   MacBook (dev) → Azure VM (public IP, port-forward) → Tailscale → Fedora MiniPC
#
#   The Azure VM acts as a public-facing reverse proxy. It forwards inbound
#   HTTP/HTTPS to the Fedora MiniPC at its Tailscale IP (100.82.166.71).
#   The MacBook can't reach the MiniPC directly (no port-forward on local ISP),
#   so we push files to Azure and let Azure relay traffic + serve the site.
#
# Prerequisites:
#   - Azure VM reachable at $AZURE_HOST with SSH key auth
#   - Tailscale running on both Azure VM and Fedora MiniPC
#   - Nginx on Azure VM configured to reverse-proxy to MiniPC Tailscale IP
#   - Nginx on Fedora MiniPC configured to serve static files
#   - SSH ProxyJump configured: MacBook → Azure → MiniPC
#
# Usage:
#   bash scripts/deploy.sh [--skip-build] [--data-only]

set -euo pipefail

SKIP_BUILD=false
DATA_ONLY=false

for arg in "$@"; do
  case $arg in
    --skip-build) SKIP_BUILD=true ;;
    --data-only)  DATA_ONLY=true; SKIP_BUILD=true ;;
  esac
done

# ─── Configuration ──────────────────────────────────────────────────────────
# Azure VM — public-facing jump host with Tailscale installed
AZURE_HOST="${AZURE_HOST:-root@<AZURE_VM_PUBLIC_IP>}"
AZURE_KEY="${AZURE_SSH_KEY:-~/.ssh/id_rsa}"

# Fedora MiniPC — Tailscale IP (reachable from Azure VM via Tailscale mesh)
MINIPC_TAILSCALE_IP="100.82.166.71"
MINIPC_SSH_OPTS="-o ProxyJump=${AZURE_HOST} -o StrictHostKeyChecking=no"

REMOTE_DIR="/var/www/desimapper"
WEB_DATA_SRC="web/public/data"

echo "╔══════════════════════════════════════════════════╗"
echo "║  DesiMapper — Deploy via Azure → Tailscale       ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""
echo "  Topology: MacBook → ${AZURE_HOST} → [Tailscale] → ${MINIPC_TAILSCALE_IP}"
echo ""

# ─── Step 1: Build ──────────────────────────────────────────────────────────
if [ "$SKIP_BUILD" = false ]; then
  echo "▶ Building web app…"
  cd web && npm run build && cd ..
  echo "  ✓ Built to web/dist/"
fi

# ─── Step 2: Push built files to Fedora MiniPC via Azure jump host ──────────
if [ "$DATA_ONLY" = false ]; then
  echo ""
  echo "▶ Syncing web/dist/ → ${MINIPC_TAILSCALE_IP}:${REMOTE_DIR}/…"
  echo "  (routing through Azure VM as jump host)"

  # Create remote directory
  ssh $MINIPC_SSH_OPTS "root@${MINIPC_TAILSCALE_IP}" "mkdir -p ${REMOTE_DIR}"

  # Sync via rsync through the Azure jump
  rsync -avz --delete \
    -e "ssh -J ${AZURE_HOST} -o StrictHostKeyChecking=no" \
    web/dist/ \
    "root@${MINIPC_TAILSCALE_IP}:${REMOTE_DIR}/"

  echo "  ✓ Synced dist/"
fi

# ─── Step 3: Sync galaxy binary data ────────────────────────────────────────
if [ -f "${WEB_DATA_SRC}/galaxies.bin" ]; then
  echo ""
  BIN_SIZE=$(du -sh "${WEB_DATA_SRC}/galaxies.bin" | cut -f1)
  echo "▶ Syncing galaxy data (${BIN_SIZE})…"

  rsync -avz --progress \
    -e "ssh -J ${AZURE_HOST} -o StrictHostKeyChecking=no" \
    "${WEB_DATA_SRC}/" \
    "root@${MINIPC_TAILSCALE_IP}:${REMOTE_DIR}/data/"

  echo "  ✓ Synced galaxy data"
else
  echo ""
  echo "  ⚠ No galaxy data found at ${WEB_DATA_SRC}/galaxies.bin"
  echo "    Run: mise run export-web  (after running the full pipeline)"
fi

# ─── Step 4: Configure nginx on Fedora MiniPC ───────────────────────────────
echo ""
echo "▶ Installing nginx config on Fedora MiniPC…"
scp $MINIPC_SSH_OPTS \
  scripts/nginx-minipc.conf \
  "root@${MINIPC_TAILSCALE_IP}:/etc/nginx/conf.d/desimapper.conf"
ssh $MINIPC_SSH_OPTS "root@${MINIPC_TAILSCALE_IP}" \
  "nginx -t && systemctl reload nginx && systemctl enable nginx"
echo "  ✓ Nginx reloaded on MiniPC"

# ─── Step 5: Configure nginx on Azure VM as reverse proxy ───────────────────
echo ""
echo "▶ Installing reverse-proxy config on Azure VM…"
scp -i "$AZURE_KEY" \
  scripts/nginx-azure.conf \
  "${AZURE_HOST}:/etc/nginx/conf.d/desimapper.conf"
ssh -i "$AZURE_KEY" "$AZURE_HOST" \
  "nginx -t && systemctl reload nginx && systemctl enable nginx"
echo "  ✓ Nginx reverse proxy reloaded on Azure VM"

echo ""
echo "✓ Deploy complete!"
echo ""
echo "  Public URL  : http://<AZURE_VM_PUBLIC_IP>/"
echo "  Internal    : http://${MINIPC_TAILSCALE_IP}/ (Tailscale only)"
echo ""
echo "  To add a domain, point DNS A record to the Azure VM IP"
echo "  and update nginx-azure.conf with 'server_name yourdomain.com;'"
