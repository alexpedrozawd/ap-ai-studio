#!/usr/bin/env bash
# Aguarda o estagio 2 terminar e dispara o estagio 3 automaticamente.
set -u
log() { echo "[$(date +'%F %T')] [chain] $*"; }
log "aguardando o estagio 2 terminar..."
while systemctl --user is-active --quiet ai-studio-stage2; do sleep 30; done
log "estagio 2 terminou. Iniciando estagio 3 (modelos)."
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
exec distrobox enter ai-studio -- bash "$RAIZ/build/stage3_models.sh"
