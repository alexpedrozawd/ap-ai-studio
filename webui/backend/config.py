"""Constantes compartilhadas do backend da interface web.

Nao importa run_vfx.py como biblioteca de proposito - o backend so' conversa com ele
via subprocesso (mesma decisao de arquitetura do vfx_aliases.sh), entao os valores
abaixo sao copias deliberadas dos mesmos usados la', nao uma fonte unica compartilhada.
Se um dia divergirem, e' sinal de que algo mudou dos dois lados e precisa de atencao.
"""

COMFYUI_HOST = "127.0.0.1"
COMFYUI_PORT = 8288
COMFYUI_DIR = "/home/ap/ai_pipeline/ComfyUI"

VFX_DIR = "/home/ap/ap-ai-studio"
VFX_PY = "/home/ap/miniconda3/envs/vfx-pipeline/bin/python"
VFX_SCRIPT = f"{VFX_DIR}/run_vfx.py"

# Dublagem (lip_syncer) nao tem --mode dedicado no run_vfx.py ainda (ver MANUAL_USO.md
# secao 4.9) - chamamos o facefusion.py direto, no ambiente Conda proprio dele.
FACEFUSION_PY = "/home/ap/miniconda3/envs/facefusion-pipeline/bin/python"
FACEFUSION_DIR = "/home/ap/ai_pipeline/facefusion"

UPLOAD_DIR = "/home/ap/ai_pipeline/webui_uploads"
JOB_OUTPUT_DIR = "/home/ap/ai_pipeline/webui_jobs"

# Achados de auditoria: (1) upload multipart era salvo em disco ANTES do Gate 3 do
# run_vfx.py ter qualquer chance de checar espaco livre - um upload grande ja' teria
# comido a margem antes do gate rodar; (2) nao havia limite de tamanho configurado.
# DISK_SAFETY_MARGIN_GB espelha de proposito a mesma margem do Gate 3 (run_vfx.py) -
# duplicacao deliberada, mesma logica do resto deste arquivo.
DISK_SAFETY_MARGIN_GB = 30
MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024  # 4GB - generoso p/ video, sem ameacar o disco

# Diretorios de job com mais de N dias sao apagados automaticamente (ver jobs.py:
# cleanup_old_jobs). Jobs em memoria (JOBS) mais antigos que isso tambem sao descartados.
JOB_RETENTION_DAYS = 7

WEBUI_HOST = "100.122.206.41"  # IP Tailscale do servidor - nunca 0.0.0.0
WEBUI_PORT = 8299
