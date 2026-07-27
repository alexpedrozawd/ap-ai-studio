#!/usr/bin/env bash
# Estagio 1 da reconstrucao do AP AI Studio no Bazzite/AMD.
# Roda DENTRO do contêiner distrobox 'ai-studio' (Ubuntu 24.04).
#
# Objetivo deste estagio: provar que o PyTorch ROCm enxerga a RX 9070 XT (gfx1201)
# ANTES de baixar dezenas de GB de modelos. Falha rapido se a premissa estiver errada.
#
# Idempotente: pode ser reexecutado sem estragar nada.
set -Eeuo pipefail

# Auto-localizavel: os scripts vivem em <raiz>/build/, entao a raiz e' um nivel acima.
STUDIO_HOME="${AP_AI_STUDIO_HOME:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)}"
MINICONDA_DIR="$STUDIO_HOME/miniconda3"
LOG_DIR="$STUDIO_HOME/build/logs"
mkdir -p "$LOG_DIR"

log() { echo "[$(date +'%F %T')] $*"; }
trap 'log "ERRO na linha $LINENO (comando: $BASH_COMMAND)"' ERR

log "=== Estagio 1: base + PyTorch ROCm ==="
log "STUDIO_HOME=$STUDIO_HOME"

# --- 1.1 Dependencias de sistema (dentro do contêiner, nao no host) ---
if [ ! -f "$STUDIO_HOME/build/.stage1_apt_done" ]; then
	log "Instalando dependencias base via apt (dentro do contêiner)..."
	sudo apt-get update -qq
	sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
		git wget curl ca-certificates bzip2 \
		build-essential pkg-config \
		ffmpeg libgl1 libglib2.0-0 \
		libimage-exiftool-perl psmisc
	touch "$STUDIO_HOME/build/.stage1_apt_done"
	log "apt concluido."
else
	log "apt ja feito, pulando."
fi

# --- 1.2 Miniconda ---
if [ ! -x "$MINICONDA_DIR/bin/conda" ]; then
	log "Instalando Miniconda em $MINICONDA_DIR..."
	INSTALLER="/tmp/miniconda_installer.sh"
	wget -q -O "$INSTALLER" https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
	bash "$INSTALLER" -b -p "$MINICONDA_DIR"
	rm -f "$INSTALLER"
	log "Miniconda instalado."
else
	log "Miniconda ja presente, pulando."
fi

export PATH="$MINICONDA_DIR/bin:$PATH"

# --- 1.2b Canais: conda-forge apenas, sem os canais padrao da Anaconda ---
# Os canais 'pkgs/main' e 'pkgs/r' da Anaconda passaram a exigir aceite explicito de
# Termos de Servico (CondaToSNonInteractiveError). Duas razoes pra evitar em vez de
# aceitar automaticamente: (1) aceitar um acordo legal em nome do usuario nao e' decisao
# de um script; (2) a licenca dos canais da Anaconda restringe uso comercial em
# organizacoes grandes. conda-forge e' comunitario, sem esse encargo, e tem cobertura
# melhor pro que este projeto usa.
log "Configurando conda para usar somente o conda-forge..."
"$MINICONDA_DIR/bin/conda" config --system --remove-key channels 2>/dev/null || true
"$MINICONDA_DIR/bin/conda" config --system --add channels conda-forge
"$MINICONDA_DIR/bin/conda" config --system --set channel_priority strict

# --- 1.3 Ambiente vfx-pipeline + PyTorch ROCm ---
# Python 3.11: mesma versao da era Ubuntu (o codigo assume lib/python3.11 em
# build_facefusion_env) e a mais testada com ComfyUI.
if ! "$MINICONDA_DIR/bin/conda" env list | grep -q '^vfx-pipeline '; then
	log "Criando ambiente conda vfx-pipeline (python 3.11)..."
	"$MINICONDA_DIR/bin/conda" create -y -q -n vfx-pipeline python=3.11 \
		--override-channels --channel conda-forge
else
	log "Ambiente vfx-pipeline ja existe, pulando criacao."
fi

VFX_PY="$MINICONDA_DIR/envs/vfx-pipeline/bin/python"

log "Instalando PyTorch ROCm (wheels oficiais da AMD para gfx120X/RDNA4)..."
"$VFX_PY" -m pip install -q --upgrade pip
"$VFX_PY" -m pip install -q --index-url https://repo.amd.com/rocm/whl/gfx120X-all/ \
	torch torchvision torchaudio

# --- 1.4 VALIDACAO: a GPU e' de fato visivel? ---
log "=== Validando acesso do PyTorch a GPU ==="
"$VFX_PY" - <<'PYEOF'
import sys
import torch

print(f"torch                : {torch.__version__}")
print(f"compilado p/ HIP/ROCm: {getattr(torch.version, 'hip', None)}")
print(f"GPU disponivel       : {torch.cuda.is_available()}")

if not torch.cuda.is_available():
    print("FALHA: PyTorch nao enxerga a GPU.")
    sys.exit(1)

print(f"dispositivos         : {torch.cuda.device_count()}")
name = torch.cuda.get_device_name(0)
props = torch.cuda.get_device_properties(0)
print(f"nome                 : {name}")
print(f"arquitetura          : {getattr(props, 'gcnArchName', 'desconhecida')}")
print(f"VRAM total           : {props.total_memory / 1024**3:.1f} GiB")

# Teste real de computacao - 'is_available' pode mentir se os kernels nao existirem
# pra arquitetura (foi exatamente o que aconteceu na RTX 5060 Ti com o onnxruntime).
print("\nRodando multiplicacao de matrizes 4096x4096 na GPU...")
a = torch.randn(4096, 4096, device="cuda", dtype=torch.float32)
b = torch.randn(4096, 4096, device="cuda", dtype=torch.float32)
c = a @ b
torch.cuda.synchronize()
esperado = (a.float() @ b.float()).sum().item()
obtido = c.sum().item()
print(f"resultado da soma    : {obtido:.4f}")
assert torch.isfinite(c).all(), "resultado contem NaN/Inf - kernels quebrados"
print("OK: computacao real na GPU funcionou.")
PYEOF

log "=== Estagio 1 concluido com sucesso ==="
touch "$STUDIO_HOME/build/.stage1_done"
