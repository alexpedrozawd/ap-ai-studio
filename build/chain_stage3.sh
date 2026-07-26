#!/usr/bin/env bash
# Aguarda o estagio 2 terminar e dispara o estagio 3 automaticamente.
set -u
log() { echo "[$(date +'%F %T')] [chain] $*"; }
log "aguardando o estagio 2 terminar..."
while systemctl --user is-active --quiet ai-studio-stage2; do sleep 30; done
log "estagio 2 terminou. Iniciando estagio 3 (modelos)."
exec distrobox enter ai-studio -- bash /var/home/apsrv/ap-ai-studio/build/stage3_models.sh
