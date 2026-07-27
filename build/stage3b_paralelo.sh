#!/usr/bin/env bash
# Estagio 3b: baixa em PARALELO os modelos que o estagio 3 ainda nao alcancou.
#
# Por que existe: o wget de conexao unica ficou em ~3 MB/s contra o CDN da HuggingFace,
# enquanto o pip alcancou ~40 MB/s no mesmo link - ou seja, o limite e' por conexao, nao
# da banda. Baixando N arquivos ao mesmo tempo, a vazao agregada multiplica.
#
# Convive com o estagio 3 sem conflito: cada arquivo tem destino proprio, o teste de
# "ja existe" evita duplicar, e o wget -c retoma parcial em vez de recomecar. Quando o
# estagio 3 chegar num arquivo que este script ja terminou, ele pula.
set -Euo pipefail

STUDIO_HOME="${AP_AI_STUDIO_HOME:-/var/home/apsrv/ap-ai-studio}"
MODELS="$STUDIO_HOME/ai_pipeline/ComfyUI/models"
HF="https://huggingface.co"
PARALELO=4   # conexoes simultaneas

log() { echo "[$(date +'%F %T')] $*"; }

# O primeiro arquivo (T2V HighNoise) fica de fora: o estagio 3 esta baixando ele agora,
# e duas escritas no mesmo destino se corromperiam mutuamente.
declare -a TAREFAS=(
"$HF/QuantStack/Wan2.2-T2V-A14B-GGUF/resolve/main/LowNoise/Wan2.2-T2V-A14B-LowNoise-Q4_K_M.gguf|unet/Wan2.2-T2V-A14B-LowNoise-Q4_K_M.gguf"
"$HF/QuantStack/Wan2.2-I2V-A14B-GGUF/resolve/main/HighNoise/Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf|unet/Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf"
"$HF/QuantStack/Wan2.2-I2V-A14B-GGUF/resolve/main/LowNoise/Wan2.2-I2V-A14B-LowNoise-Q4_K_M.gguf|unet/Wan2.2-I2V-A14B-LowNoise-Q4_K_M.gguf"
"$HF/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/vae/wan_2.1_vae.safetensors|vae/Wan2.1_VAE.safetensors"
"$HF/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors|text_encoders/umt5-xxl-enc-fp8_e4m3fn.safetensors"
"https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth|upscale_models/RealESRGAN_x4plus.pth"
"$HF/diffusers/stable-diffusion-xl-1.0-inpainting-0.1/resolve/main/unet/diffusion_pytorch_model.fp16.safetensors|unet/sd_xl_base_1.0_inpainting_0.1.safetensors"
"$HF/diffusers/controlnet-depth-sdxl-1.0/resolve/main/diffusion_pytorch_model.fp16.safetensors|controlnet/controlnet-depth-sdxl-1.0.safetensors"
)

baixar_um() {
	local url="${1%%|*}" rel="${1##*|}" destino
	destino="$MODELS/$rel"
	mkdir -p "$(dirname "$destino")"

	# Se o arquivo ja esta completo (tamanho local == Content-Length), nao mexe.
	local esperado atual
	esperado=$(curl -sIL "$url" --max-time 30 | grep -i '^content-length' | tail -1 | tr -dc '0-9')
	atual=$(stat -c%s "$destino" 2>/dev/null || echo 0)
	if [ -n "$esperado" ] && [ "$atual" = "$esperado" ]; then
		log "completo, pulando: $rel"
		return 0
	fi

	log "baixando: $rel"
	if wget -c -q --tries=5 --timeout=60 -O "$destino" "$url"; then
		log "  ok: $rel ($(du -h "$destino" | cut -f1))"
	else
		log "  FALHOU: $rel"
	fi
}
export -f baixar_um log
export MODELS

log "=== Estagio 3b: ${#TAREFAS[@]} arquivos, $PARALELO por vez ==="
printf '%s\n' "${TAREFAS[@]}" | xargs -P "$PARALELO" -I{} bash -c 'baixar_um "$@"' _ {}

log "=== Estagio 3b finalizado ==="
log "total em models/: $(du -sh "$MODELS" 2>/dev/null | cut -f1)"
log "espaco livre: $(df -h "$STUDIO_HOME" | tail -1 | awk '{print $4}')"
