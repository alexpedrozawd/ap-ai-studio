#!/usr/bin/env bash
# Estagio 2: ComfyUI, custom nodes, FaceFusion e os demais ambientes Conda.
# Roda DENTRO do contêiner distrobox 'ai-studio'. Idempotente.
#
# Politica de erro: cada componente e' isolado. Um custom node que falhe NAO derruba o
# estagio inteiro - o erro e' registrado e o build segue. Motivo: um node opcional
# quebrado nao pode impedir o ComfyUI de existir. O resumo final lista o que falhou.
set -Euo pipefail

STUDIO_HOME="${AP_AI_STUDIO_HOME:-/var/home/apsrv/ap-ai-studio}"
MINICONDA_DIR="$STUDIO_HOME/miniconda3"
PIPELINE="$STUDIO_HOME/ai_pipeline"
CONDA="$MINICONDA_DIR/bin/conda"
ROCM_INDEX="https://repo.amd.com/rocm/whl/gfx120X-all/"
FALHAS=()

mkdir -p "$PIPELINE" "$STUDIO_HOME/build/logs"
log() { echo "[$(date +'%F %T')] $*"; }
falhou() { log "FALHOU: $1"; FALHAS+=("$1"); }

log "=== Estagio 2: aplicacoes e ambientes ==="

criar_env() {  # nome, versao_python
	local nome="$1" pyver="${2:-3.11}"
	if "$CONDA" env list | grep -q "^$nome "; then
		log "Ambiente $nome ja existe."
		return 0
	fi
	log "Criando ambiente $nome (python $pyver)..."
	"$CONDA" create -y -q -n "$nome" "python=$pyver" --override-channels --channel conda-forge \
		|| { falhou "criar env $nome"; return 1; }
}

clonar() {  # url, destino
	local url="$1" destino="$2" nome
	nome=$(basename "$destino")
	if [ -d "$destino/.git" ]; then
		log "$nome ja clonado."
		return 0
	fi
	log "Clonando $nome..."
	# ACHADO REAL (2026-07-26): 'git clone' recusa destino nao-vazio, e o diretorio
	# ai_pipeline/ComfyUI ja existia (criado como efeito colateral da suite de testes,
	# que faz os.makedirs em PIPELINE_PATH). O clone falhou, o build seguiu, e os custom
	# nodes foram instalados dentro de um ComfyUI que nao existia - so' detectado depois.
	# Por isso: se o destino existe mas nao e' repo, clona num temporario e preenche o que
	# falta, sem sobrescrever (-n) o que ja estiver la'.
	if [ -d "$destino" ] && [ -n "$(ls -A "$destino" 2>/dev/null)" ]; then
		log "  destino nao-vazio e sem .git - clonando via temporario e preenchendo lacunas"
		local tmp
		tmp=$(mktemp -d)
		if git clone --depth 1 "$url" "$tmp/repo"; then
			cp -rn "$tmp/repo/.git" "$destino/" 2>/dev/null
			cp -rn "$tmp/repo/." "$destino/" 2>/dev/null
			rm -rf "$tmp"
			log "  $nome preenchido."
			return 0
		fi
		rm -rf "$tmp"
		falhou "clonar $nome (via temporario)"
		return 1
	fi
	git clone --depth 1 "$url" "$destino" || { falhou "clonar $nome"; return 1; }
}

# --- 2.1 ComfyUI ---
clonar https://github.com/comfyanonymous/ComfyUI.git "$PIPELINE/ComfyUI"

VFX_PY="$MINICONDA_DIR/envs/vfx-pipeline/bin/python"
if [ -f "$PIPELINE/ComfyUI/requirements.txt" ]; then
	log "Instalando requirements do ComfyUI (sem tocar no torch ROCm ja instalado)..."
	# --no-deps NAO serve aqui (quebraria dependencias legitimas). A protecao real e'
	# reinstalar o torch ROCm depois, caso o requirements do ComfyUI puxe uma wheel CUDA
	# por cima - foi exatamente o que aconteceu na era NVIDIA (ver PROMPT_MASTER, Fase 1).
	"$VFX_PY" -m pip install -q -r "$PIPELINE/ComfyUI/requirements.txt" || falhou "requirements do ComfyUI"
	log "Reafirmando o torch ROCm (protecao contra downgrade pra wheel CUDA)..."
	"$VFX_PY" -m pip install -q --index-url "$ROCM_INDEX" --force-reinstall --no-deps \
		torch torchvision torchaudio || falhou "reafirmar torch ROCm"
fi

# --- 2.2 Custom nodes ---
NODES="$PIPELINE/ComfyUI/custom_nodes"
mkdir -p "$NODES"
clonar https://github.com/ltdrdata/ComfyUI-Manager.git          "$NODES/ComfyUI-Manager"
clonar https://github.com/city96/ComfyUI-GGUF.git               "$NODES/ComfyUI-GGUF"
clonar https://github.com/kijai/ComfyUI-WanVideoWrapper.git     "$NODES/ComfyUI-WanVideoWrapper"
clonar https://github.com/Fannovel16/comfyui_controlnet_aux.git "$NODES/comfyui_controlnet_aux"
clonar https://github.com/Fannovel16/ComfyUI-Frame-Interpolation.git "$NODES/ComfyUI-Frame-Interpolation"

for node_dir in "$NODES"/*/; do
	req="$node_dir/requirements.txt"
	[ -f "$req" ] || continue
	nome=$(basename "$node_dir")
	log "Dependencias do node $nome..."
	"$VFX_PY" -m pip install -q -r "$req" || falhou "requirements do node $nome"
done

# Um node pode ter puxado torch CUDA de novo. Reafirma uma ultima vez.
log "Reafirmando torch ROCm apos os custom nodes..."
"$VFX_PY" -m pip install -q --index-url "$ROCM_INDEX" --force-reinstall --no-deps \
	torch torchvision torchaudio || falhou "reafirmar torch ROCm (pos-nodes)"

# --- 2.3 FaceFusion (ambiente proprio: conflito real de numpy com o ComfyUI) ---
criar_env facefusion-pipeline 3.11
clonar https://github.com/facefusion/facefusion.git "$PIPELINE/facefusion"
FF_PY="$MINICONDA_DIR/envs/facefusion-pipeline/bin/python"
if [ -f "$PIPELINE/facefusion/requirements.txt" ]; then
	log "Instalando requirements do FaceFusion..."
	"$FF_PY" -m pip install -q -r "$PIPELINE/facefusion/requirements.txt" || falhou "requirements do FaceFusion"
	# onnxruntime de CPU: nao ha wheel ROCm oficial com kernels gfx1201 (decisao registrada
	# em MIGRACAO_BAZZITE.md secao 2.2). Remove a variante GPU se o requirements puxou uma.
	"$FF_PY" -m pip uninstall -y -q onnxruntime-gpu 2>/dev/null || true
	"$FF_PY" -m pip install -q onnxruntime || falhou "onnxruntime (cpu) do FaceFusion"
fi

# --- 2.4 TTS (XTTS-v2) ---
criar_env tts-pipeline 3.11
TTS_PY="$MINICONDA_DIR/envs/tts-pipeline/bin/python"
log "Instalando coqui-tts + torch ROCm no tts-pipeline..."
"$TTS_PY" -m pip install -q --index-url "$ROCM_INDEX" torch torchaudio || falhou "torch ROCm (tts)"
"$TTS_PY" -m pip install -q coqui-tts || falhou "coqui-tts"

# --- 2.5 Demucs (isolamento de voz) ---
criar_env noise-pipeline 3.11
NOISE_PY="$MINICONDA_DIR/envs/noise-pipeline/bin/python"
log "Instalando demucs + torch ROCm no noise-pipeline..."
"$NOISE_PY" -m pip install -q --index-url "$ROCM_INDEX" torch torchaudio || falhou "torch ROCm (demucs)"
"$NOISE_PY" -m pip install -q demucs torchcodec || falhou "demucs"

# --- 2.6 Interface web ---
criar_env webui-pipeline 3.11
WEB_PY="$MINICONDA_DIR/envs/webui-pipeline/bin/python"
if [ -f "$STUDIO_HOME/webui/backend/requirements.txt" ]; then
	"$WEB_PY" -m pip install -q -r "$STUDIO_HOME/webui/backend/requirements.txt" || falhou "requirements da webui"
else
	"$WEB_PY" -m pip install -q fastapi uvicorn python-multipart aiohttp || falhou "deps basicas da webui"
fi

# --- Resumo ---
log "=== Estagio 2 finalizado ==="
if [ ${#FALHAS[@]} -eq 0 ]; then
	log "Sem falhas."
	touch "$STUDIO_HOME/build/.stage2_done"
else
	log "Componentes com falha (${#FALHAS[@]}):"
	for f in "${FALHAS[@]}"; do log "  - $f"; done
	log "O estagio seguiu mesmo assim; revisar os itens acima."
fi
