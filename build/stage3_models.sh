#!/usr/bin/env bash
# Estagio 3: download dos modelos.
# Roda DENTRO do contêiner distrobox 'ai-studio'. Idempotente (pula o que ja existe,
# e o wget usa -c pra retomar download interrompido em vez de recomecar do zero).
#
# TODAS as URLs abaixo foram verificadas com HTTP 200 antes de entrarem aqui - nenhuma
# foi escrita de memoria. O RIFE ficou de fora de proposito: o node
# ComfyUI-Frame-Interpolation baixa os pesos sozinho no primeiro uso.
set -Euo pipefail

STUDIO_HOME="${AP_AI_STUDIO_HOME:-/var/home/apsrv/ap-ai-studio}"
MODELS="$STUDIO_HOME/ai_pipeline/ComfyUI/models"
FALHAS=()

log() { echo "[$(date +'%F %T')] $*"; }

baixar() {  # url, destino_relativo
	local url="$1" destino="$MODELS/$2"
	mkdir -p "$(dirname "$destino")"
	if [ -s "$destino" ]; then
		log "ja existe: $2 ($(du -h "$destino" | cut -f1))"
		return 0
	fi
	log "baixando: $2"
	# -c retoma download parcial; --tries pra sobreviver a oscilacao de rede
	if wget -c -q --tries=5 --timeout=60 -O "$destino" "$url"; then
		log "  ok: $2 ($(du -h "$destino" | cut -f1))"
	else
		log "  FALHOU: $2"
		FALHAS+=("$2")
		rm -f "$destino"   # nao deixar arquivo truncado passando por completo
	fi
}

log "=== Estagio 3: modelos ==="
log "espaco livre antes: $(df -h "$STUDIO_HOME" | tail -1 | awk '{print $4}')"

HF="https://huggingface.co"

# --- Wan2.2 texto->video (MoE high/low noise, GGUF Q4_K_M) ---
baixar "$HF/QuantStack/Wan2.2-T2V-A14B-GGUF/resolve/main/HighNoise/Wan2.2-T2V-A14B-HighNoise-Q4_K_M.gguf" \
	"unet/Wan2.2-T2V-A14B-HighNoise-Q4_K_M.gguf"
baixar "$HF/QuantStack/Wan2.2-T2V-A14B-GGUF/resolve/main/LowNoise/Wan2.2-T2V-A14B-LowNoise-Q4_K_M.gguf" \
	"unet/Wan2.2-T2V-A14B-LowNoise-Q4_K_M.gguf"

# --- Wan2.2 imagem->video ---
baixar "$HF/QuantStack/Wan2.2-I2V-A14B-GGUF/resolve/main/HighNoise/Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf" \
	"unet/Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf"
baixar "$HF/QuantStack/Wan2.2-I2V-A14B-GGUF/resolve/main/LowNoise/Wan2.2-I2V-A14B-LowNoise-Q4_K_M.gguf" \
	"unet/Wan2.2-I2V-A14B-LowNoise-Q4_K_M.gguf"

# --- VAE e text encoder do Wan ---
baixar "$HF/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/vae/wan_2.1_vae.safetensors" \
	"vae/Wan2.1_VAE.safetensors"
baixar "$HF/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors" \
	"text_encoders/umt5-xxl-enc-fp8_e4m3fn.safetensors"

# --- Upscale ---
baixar "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth" \
	"upscale_models/RealESRGAN_x4plus.pth"

# --- Inpainting SDXL + ControlNet Depth ---
baixar "$HF/diffusers/stable-diffusion-xl-1.0-inpainting-0.1/resolve/main/unet/diffusion_pytorch_model.fp16.safetensors" \
	"unet/sd_xl_base_1.0_inpainting_0.1.safetensors"
baixar "$HF/diffusers/controlnet-depth-sdxl-1.0/resolve/main/diffusion_pytorch_model.fp16.safetensors" \
	"controlnet/controlnet-depth-sdxl-1.0.safetensors"

log "=== Estagio 3 finalizado ==="
log "espaco livre depois: $(df -h "$STUDIO_HOME" | tail -1 | awk '{print $4}')"
log "total baixado: $(du -sh "$MODELS" 2>/dev/null | cut -f1)"

if [ ${#FALHAS[@]} -eq 0 ]; then
	log "Todos os modelos baixados."
	touch "$STUDIO_HOME/build/.stage3_done"
else
	log "Modelos que falharam (${#FALHAS[@]}):"
	for f in "${FALHAS[@]}"; do log "  - $f"; done
	log "Reexecutar este script retoma so' os que faltam."
fi
