"""Constantes e configuracao compartilhadas por todos os modulos do run_vfx.py.

Achado de auditoria (Engenheiro de Software): run_vfx.py era um monolito de ~1500
linhas fazendo orquestracao, gates, workflows do ComfyUI, comandos externos e parsing
de CLI tudo junto. Dividido em modulos por responsabilidade - este e' o unico modulo
sem nenhuma dependencia interna (so' stdlib), pra evitar import circular: todos os
outros dependem dele, ele nao depende de nenhum outro.
"""

import os

# --- Caminhos ---
# Parametrizados por variavel de ambiente: o projeto ja migrou de servidor uma vez
# (/home/ap no Ubuntu -> /var/home/apsrv no Bazzite) e hardcode custou caro. O default
# cobre a maquina atual; AP_AI_STUDIO_HOME cobre qualquer outra sem tocar no codigo.
# No Bazzite (ostree) /home e' symlink pra /var/home - os dois caminhos funcionam.
STUDIO_HOME = os.environ.get("AP_AI_STUDIO_HOME", "/var/home/apsrv/ap-ai-studio")
PIPELINE_PATH = os.path.join(STUDIO_HOME, "ai_pipeline")
MINICONDA_DIR = os.path.join(STUDIO_HOME, "miniconda3")
LOG_PATH = os.path.join(PIPELINE_PATH, "logs", "run_vfx.log")
COMFYUI_HOST = "127.0.0.1"
COMFYUI_PORT = 8288
DISK_SAFETY_MARGIN_GB = 30

# Gate 3 mede o espaco AQUI, nao em "/". No Bazzite a raiz e' composefs somente-leitura
# (44MB, 100% ocupada por definicao) - medir "/" fazia o Gate 3 abortar todo o pipeline
# com "disco cheio" tendo centenas de GB livres em /var/home. Ver MIGRACAO_BAZZITE.md.
DISK_CHECK_PATH = os.environ.get("AP_AI_STUDIO_DISK_CHECK_PATH", STUDIO_HOME)

VRAM_PEAK_ALERT_GB = 15
MEMORY_MAX_DEFAULT = "24G"
MEMORY_MAX_VIDEO = "28G"
MEMORY_SWAP_MAX_VIDEO = "4G"

# --- GPU (AMD Radeon RX 9070 XT / RDNA4 gfx1201, driver amdgpu) ---
# A leitura de VRAM vem do sysfs do amdgpu, nao de um binario externo: funciona sem
# instalar nada (rocm-smi nao esta presente e exigiria layering na imagem imutavel).
AMDGPU_VRAM_TOTAL_GLOB = "/sys/class/drm/card*/device/mem_info_vram_total"
AMDGPU_VRAM_USED_GLOB = "/sys/class/drm/card*/device/mem_info_vram_used"
# Fallback opcional, usado so' se o sysfs falhar. Caminho absoluto de proposito
# (achado do SAST, bandit B607): evita que um PATH manipulado troque o binario real.
ROCM_SMI_PATH = "/usr/bin/rocm-smi"

# Encoder de video por hardware. A AMD descontinuou o AMF nos drivers Linux recentes e
# orienta migrar pra VA-API; VAAPI foi validado nesta GPU (H.264/HEVC/AV1 com
# VAEntrypointEncSlice). Ver MIGRACAO_BAZZITE.md secao 2.3.
VAAPI_DEVICE = os.environ.get("AP_AI_STUDIO_VAAPI_DEVICE", "/dev/dri/renderD128")

LOG_TRUNCATE_THRESHOLD_BYTES = 5 * 1024 * 1024

CONDA_FALLBACK_PATHS = [
	os.path.join(MINICONDA_DIR, "bin", "conda"),
	os.path.join(MINICONDA_DIR, "condabin", "conda"),
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
# PyTorch no ROCm usa a variavel HIP (o runtime e' HIP, nao CUDA). O nome CUDA ainda e'
# aceito por compatibilidade em algumas versoes, mas depender disso e' fragil.
PYTORCH_HIP_ALLOC_CONF_VALUE = "expandable_segments:True"
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

# Execution provider do onnxruntime (FaceFusion). CPU e' o padrao nesta maquina: nao ha
# wheel oficial de onnxruntime-rocm com kernels gfx1201 (RDNA4) prontos, e construir da
# fonte exige CMAKE_HIP_ARCHITECTURES com relatos de lacunas do gfx1201 na tabela de
# arquiteturas (fallback silencioso). Decisao do usuario em 2026-07-26: aceitar CPU agora
# e reavaliar quando houver wheel oficial - trocando esta constante ou a env var, sem
# mexer no codigo. Historico: na RTX 5060 Ti (Blackwell/sm_120) o lip_syncer ja rodava em
# CPU pelo mesmo tipo de motivo, entao isto NAO e' regressao pra esse processador.
DEFAULT_EXECUTION_PROVIDER = os.environ.get("AP_AI_STUDIO_EXECUTION_PROVIDER", "cpu")
TTS_CONDA_ENV = "tts-pipeline"
TTS_SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tts_synthesize.py")
DEMUCS_CONDA_ENV = "noise-pipeline"
DEMUCS_SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demucs_separate.py")


class GateDenied(Exception):
	pass
