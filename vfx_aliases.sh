#!/usr/bin/env bash
# AP AI Studio - atalhos de terminal (source deste arquivo no ~/.bashrc)
#
# Cada função chama o interpretador Python certo pelo caminho absoluto (nao usa
# 'conda activate' nem 'conda run') - funciona em qualquer terminal, independente
# do ambiente Conda que estiver ativo no momento, e nao tem o bug de stdin do
# 'conda run' (as perguntas [Y/n] dos Gates funcionam normalmente).
#
# Padrão: <atalho> <argumentos obrigatorios> [flags extras do run_vfx.py]
# Tudo que vier depois dos argumentos obrigatorios é repassado direto pro
# run_vfx.py - ex: vfx-rosto origem.jpg alvo.mp4 saida.mp4 --chunk-seconds 30

VFX_DIR="/home/ap/ap-ai-studio"
VFX_PY="/home/ap/miniconda3/envs/vfx-pipeline/bin/python"
VFX_SCRIPT="$VFX_DIR/run_vfx.py"
FF_PY="/home/ap/miniconda3/envs/facefusion-pipeline/bin/python"
FF_DIR="/home/ap/ai_pipeline/facefusion"
COMFYUI_DIR="/home/ap/ai_pipeline/ComfyUI"
COMFYUI_HOST="127.0.0.1"
COMFYUI_PORT="8288"
WEBUI_PY="/home/ap/miniconda3/envs/webui-pipeline/bin/python"
WEBUI_BACKEND_DIR="$VFX_DIR/webui/backend"
WEBUI_FRONTEND_DIR="$VFX_DIR/webui/frontend"
WEBUI_HOST="100.122.206.41"
WEBUI_PORT="8299"
COMFYUI_LOG="/home/ap/ai_pipeline/logs/comfyui_boot.log"

# --- internos, não chamar diretamente ---

_vfx_comfyui_up() {
	curl -s -o /dev/null -m 2 "http://${COMFYUI_HOST}:${COMFYUI_PORT}/system_stats"
}

_vfx_ensure_comfyui() {
	if _vfx_comfyui_up; then
		return 0
	fi
	echo "ComfyUI nao esta respondendo em ${COMFYUI_HOST}:${COMFYUI_PORT}."
	read -r -p "Ligar agora? [Y/n] " resp
	case "$resp" in
		[nN]*) echo "Cancelado - ligue manualmente com 'vfx-ligar' quando quiser."; return 1 ;;
		*) vfx-ligar ;;
	esac
}

# --- controle do ComfyUI ---

vfx-ligar() {
	if _vfx_comfyui_up; then
		echo "ComfyUI ja esta rodando em ${COMFYUI_HOST}:${COMFYUI_PORT}."
		return 0
	fi
	mkdir -p "$(dirname "$COMFYUI_LOG")"
	echo "Ligando ComfyUI (log em $COMFYUI_LOG)..."
	(cd "$COMFYUI_DIR" && nohup "$VFX_PY" main.py --port "$COMFYUI_PORT" --listen "$COMFYUI_HOST" >> "$COMFYUI_LOG" 2>&1 &)
	for _ in $(seq 1 45); do
		if _vfx_comfyui_up; then
			echo "ComfyUI no ar."
			return 0
		fi
		sleep 2
	done
	echo "ComfyUI nao respondeu em 90s - confira $COMFYUI_LOG"
	return 1
}

vfx-parar() {
	if ! _vfx_comfyui_up; then
		echo "ComfyUI ja nao esta rodando."
		return 0
	fi
	fuser -k "${COMFYUI_PORT}/tcp" 2>/dev/null
	echo "Comando de encerramento enviado ao ComfyUI (porta ${COMFYUI_PORT})."
}

vfx-status() {
	echo "--- ComfyUI ---"
	if _vfx_comfyui_up; then echo "no ar em ${COMFYUI_HOST}:${COMFYUI_PORT}"; else echo "desligado"; fi
	echo "--- VRAM ---"
	nvidia-smi --query-gpu=memory.used,memory.free,memory.total --format=csv 2>/dev/null || echo "nvidia-smi indisponivel"
	echo "--- Disco (/) ---"
	df -h / | tail -1
}

# --- funções do pipeline ---

vfx-rosto() {
	if [ "$#" -lt 3 ]; then echo "uso: vfx-rosto <foto_do_rosto> <alvo.jpg|mp4> <saida> [--chunk-seconds N] [outras flags]"; return 1; fi
	local origem="$1" alvo="$2" saida="$3"; shift 3
	"$VFX_PY" "$VFX_SCRIPT" --mode faceswap --source "$origem" --target "$alvo" --output "$saida" "$@"
}

vfx-video() {
	if [ "$#" -lt 1 ]; then echo "uso: vfx-video \"<prompt>\" [--width N --height N --num-frames N] [outras flags]"; return 1; fi
	local prompt="$1"; shift
	"$VFX_PY" "$VFX_SCRIPT" --mode video --prompt "$prompt" "$@"
	echo "Resultado salvo em: $COMFYUI_DIR/output/"
}

vfx-anima() {
	if [ "$#" -lt 2 ]; then echo "uso: vfx-anima <foto.jpg> \"<prompt>\" [--width N --height N --num-frames N] [outras flags]"; return 1; fi
	local foto="$1" prompt="$2"; shift 2
	"$VFX_PY" "$VFX_SCRIPT" --mode video --source-image "$foto" --prompt "$prompt" "$@"
	echo "Resultado salvo em: $COMFYUI_DIR/output/"
}

vfx-editar() {
	if [ "$#" -lt 3 ]; then echo "uso: vfx-editar <foto.jpg> <mascara.png> <saida> [--prompt \"...\"] [outras flags]"; return 1; fi
	_vfx_ensure_comfyui || return 1
	local foto="$1" mascara="$2" saida="$3"; shift 3
	"$VFX_PY" "$VFX_SCRIPT" --mode inpaint --source-image "$foto" --mask-image "$mascara" --output "$saida" "$@"
}

vfx-semfundo() {
	if [ "$#" -lt 2 ]; then echo "uso: vfx-semfundo <foto_ou_video> <saida> [outras flags]"; return 1; fi
	local alvo="$1" saida="$2"; shift 2
	"$VFX_PY" "$VFX_SCRIPT" --mode removebg --target "$alvo" --output "$saida" "$@"
}

vfx-fala() {
	if [ "$#" -lt 3 ]; then echo "uso: vfx-fala \"<texto>\" <nome_da_voz> <saida.wav> [--language pt] [outras flags]"; return 1; fi
	local texto="$1" voz="$2" saida="$3"; shift 3
	"$VFX_PY" "$VFX_SCRIPT" --mode tts --text "$texto" --speaker "$voz" --output "$saida" "$@"
}

vfx-clonar() {
	if [ "$#" -lt 3 ]; then echo "uso: vfx-clonar \"<texto>\" <amostra_de_voz.wav> <saida.wav> [--language pt] [outras flags]"; return 1; fi
	local texto="$1" amostra="$2" saida="$3"; shift 3
	"$VFX_PY" "$VFX_SCRIPT" --mode tts --text "$texto" --speaker-wav "$amostra" --output "$saida" "$@"
}

vfx-dublar() {
	if [ "$#" -lt 3 ]; then echo "uso: vfx-dublar <audio_novo.wav> <video_original.mp4> <saida.mp4> [outras flags]"; return 1; fi
	local audio="$1" video="$2" saida="$3"; shift 3
	echo "Sincronia labial roda em CPU (decisao de arquitetura, ver MANUAL_USO.md secao 4.9) - pode demorar."
	(cd "$FF_DIR" && "$FF_PY" facefusion.py headless-run --processors lip_syncer \
		-s "$audio" -t "$video" -o "$saida" --execution-providers cpu "$@")
}

vfx-limpar() {
	if [ "$#" -lt 2 ]; then echo "uso: vfx-limpar <audio.wav> <saida_voz.wav> [saida_resto.wav] [outras flags]"; return 1; fi
	local audio="$1" voz="$2"; shift 2
	local instrumental=""
	if [ "$#" -gt 0 ] && [[ "$1" != --* ]]; then
		instrumental="$1"; shift
	fi
	if [ -n "$instrumental" ]; then
		"$VFX_PY" "$VFX_SCRIPT" --mode denoise --target "$audio" --output "$voz" --output-instrumental "$instrumental" "$@"
	else
		"$VFX_PY" "$VFX_SCRIPT" --mode denoise --target "$audio" --output "$voz" "$@"
	fi
}

vfx-musica() {
	if [ "$#" -lt 2 ]; then echo "uso: vfx-musica \"<prompt>\" <saida.wav> [--music-duration N] [outras flags]"; return 1; fi
	_vfx_ensure_comfyui || return 1
	local prompt="$1" saida="$2"; shift 2
	"$VFX_PY" "$VFX_SCRIPT" --mode music --prompt "$prompt" --output "$saida" "$@"
}

vfx-juntar() {
	if [ "$#" -lt 3 ]; then echo "uso: vfx-juntar <original.mp4> <processado.mp4> <saida.mp4> [--fps N] [outras flags]"; return 1; fi
	local original="$1" processado="$2" saida="$3"; shift 3
	"$VFX_PY" "$VFX_SCRIPT" --mode master --original "$original" --processed-video "$processado" --output "$saida" "$@"
}

vfx-web-build() {
	echo "Buildando o frontend da interface web..."
	(cd "$WEBUI_FRONTEND_DIR" && npm run build)
}

vfx-web() {
	if [ ! -f "$WEBUI_BACKEND_DIR/static/index.html" ]; then
		echo "Frontend ainda nao foi buildado."
		vfx-web-build || { echo "Build falhou - confira o erro acima."; return 1; }
	fi
	echo "Interface web em: http://${WEBUI_HOST}:${WEBUI_PORT} (Tailscale - Ctrl+C para parar)"
	(cd "$WEBUI_BACKEND_DIR" && "$WEBUI_PY" -m uvicorn main:app --host "$WEBUI_HOST" --port "$WEBUI_PORT")
}

vfx-ajuda() {
	cat <<'EOF'
AP AI Studio - atalhos disponiveis (padrao: nome curto + argumentos obrigatorios)

  vfx-status                                       ve se o ComfyUI esta ligado, VRAM e disco livres
  vfx-ligar                                         liga o ComfyUI (necessario p/ vfx-editar e vfx-musica)
  vfx-parar                                         desliga o ComfyUI

  vfx-web                                           liga a interface web (Tailscale, porta 8299)
  vfx-web-build                                     rebuilda o frontend da interface web (apos mudancas)

  vfx-rosto <origem> <alvo> <saida>                troca de rosto (foto/video; some --chunk-seconds N p/ video longo)
  vfx-video "<prompt>"                              gera video do zero (texto -> video)
  vfx-anima <foto> "<prompt>"                       anima uma foto existente (imagem -> video)
  vfx-editar <foto> <mascara> <saida>               edita/apaga algo de uma foto (inpainting) - some --prompt "..."
  vfx-semfundo <alvo> <saida>                       remove o fundo de uma foto/video
  vfx-fala "<texto>" <voz> <saida.wav>              gera fala com uma voz pronta do XTTS-v2
  vfx-clonar "<texto>" <amostra.wav> <saida.wav>    clona uma voz a partir de uma amostra de audio
  vfx-dublar <audio.wav> <video.mp4> <saida.mp4>    sincroniza a boca do video com um audio novo (dublagem)
  vfx-limpar <audio> <saida_voz> [saida_resto]       isola a voz / remove ruido de fundo (Demucs)
  vfx-musica "<prompt>" <saida.wav>                 gera uma musica
  vfx-juntar <original> <processado> <saida>        junta audio/legendas originais com o video processado

Qualquer flag extra do run_vfx.py (--dry-run, --auto-approve, --width, --fps etc.)
pode ser adicionada no final de qualquer comando acima.
Manual completo: /home/ap/ap-ai-studio/MANUAL_USO.md
EOF
}
