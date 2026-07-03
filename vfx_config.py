"""Constantes e configuracao compartilhadas por todos os modulos do run_vfx.py.

Achado de auditoria (Engenheiro de Software): run_vfx.py era um monolito de ~1500
linhas fazendo orquestracao, gates, workflows do ComfyUI, comandos externos e parsing
de CLI tudo junto. Dividido em modulos por responsabilidade - este e' o unico modulo
sem nenhuma dependencia interna (so' stdlib), pra evitar import circular: todos os
outros dependem dele, ele nao depende de nenhum outro.
"""

import os

PIPELINE_PATH = "/home/ap/ai_pipeline"
LOG_PATH = os.path.join(PIPELINE_PATH, "logs", "run_vfx.log")
COMFYUI_HOST = "127.0.0.1"
COMFYUI_PORT = 8288
DISK_SAFETY_MARGIN_GB = 30
VRAM_PEAK_ALERT_GB = 15
MEMORY_MAX_DEFAULT = "24G"
MEMORY_MAX_VIDEO = "28G"
MEMORY_SWAP_MAX_VIDEO = "4G"
NVIDIA_SMI_PATH = "/usr/bin/nvidia-smi"  # achado do SAST (bandit B607): caminho absoluto
# em vez de depender do PATH, evita que um PATH manipulado troque o binario real por um falso.

LOG_TRUNCATE_THRESHOLD_BYTES = 5 * 1024 * 1024

CONDA_FALLBACK_PATHS = [
	os.path.expanduser("~/miniconda3/bin/conda"),
	os.path.expanduser("~/miniconda3/condabin/conda"),
]

# Fase 3B: modelo de vídeo generativo (Wan2.2 T2V-A14B, GGUF Q4_K_M, MoE high/low noise)
WAN22_HIGH_NOISE_GGUF = "Wan2.2-T2V-A14B-HighNoise-Q4_K_M.gguf"
WAN22_LOW_NOISE_GGUF = "Wan2.2-T2V-A14B-LowNoise-Q4_K_M.gguf"
WAN22_I2V_HIGH_NOISE_GGUF = "Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf"
WAN22_I2V_LOW_NOISE_GGUF = "Wan2.2-I2V-A14B-LowNoise-Q4_K_M.gguf"
WAN22_VAE = "Wan2.1_VAE.safetensors"
WAN22_TEXT_ENCODER = "umt5-xxl-enc-fp8_e4m3fn.safetensors"
WAN22_UPSCALE_MODEL = "RealESRGAN_x4plus.pth"
WAN22_INTERPOLATION_MODEL = "rife_v4.25.safetensors"
WAN22_OUTPUT_FPS = 30  # pedido do usuario: fluidez proxima de cinema/TV (16fps nativo x2 = 32, salvo a 30)

# Fase 6: remocao de objeto / edicao geral de imagem (inpainting)
INPAINT_CHECKPOINT = "sd_xl_base_1.0_inpainting_0.1.safetensors"

# ControlNet Depth (achado de auditoria "uso profissional" - guia a composicao/profundidade
# da cena no inpainting, alem da mascara manual). Pre-processador de profundidade vem do
# pacote de nos comfyui_controlnet_aux (Fannovel16), instalado a parte do ComfyUI core.
CONTROLNET_DEPTH_SDXL = "controlnet-depth-sdxl-1.0.safetensors"
PYTORCH_CUDA_ALLOC_CONF_VALUE = "expandable_segments:True"
COMFYUI_SCOPE_UNIT = "vfx-comfyui-video.scope"
COMFYUI_DIR = os.path.join(PIPELINE_PATH, "ComfyUI")
COMFYUI_INPUT_DIR = os.path.join(COMFYUI_DIR, "input")
MAX_VIDEO_WIDTH = 720
MAX_VIDEO_HEIGHT = 720
MAX_VIDEO_FRAMES = 241  # ~15s a 16fps (fps nativo do Wan2.2) - pedido do usuario, ainda NAO
# testado nessa escala (so validamos 17 frames/~1s de verdade); risco real de OOM/timeout
# maior que o teste original, gates ainda se aplicam mas o "orcamento" que eles assumem
# nao foi recalibrado pra clipes desse tamanho.

# --- FaceFusion / TTS / Demucs: ambientes Conda e scripts standalone ---
FACEFUSION_CONDA_ENV = "facefusion-pipeline"
TTS_CONDA_ENV = "tts-pipeline"
TTS_SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tts_synthesize.py")
DEMUCS_CONDA_ENV = "noise-pipeline"
DEMUCS_SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demucs_separate.py")


class GateDenied(Exception):
	pass
