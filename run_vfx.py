import argparse
import asyncio
import logging
import os
import resource
import shutil
import socket
import subprocess
import sys
import uuid
from typing import Optional

PIPELINE_PATH = "/home/ap/ai_pipeline"
LOG_PATH = os.path.join(PIPELINE_PATH, "logs", "run_vfx.log")
COMFYUI_HOST = "127.0.0.1"
COMFYUI_PORT = 8288
DISK_SAFETY_MARGIN_GB = 30
VRAM_PEAK_ALERT_GB = 15
MEMORY_MAX_DEFAULT = "24G"
MEMORY_MAX_VIDEO = "28G"
MEMORY_SWAP_MAX_VIDEO = "4G"

CONDA_FALLBACK_PATHS = [
	os.path.expanduser("~/miniconda3/bin/conda"),
	os.path.expanduser("~/miniconda3/condabin/conda"),
]

# Fase 3B: modelo de vídeo generativo (Wan2.2 T2V-A14B, GGUF Q4_K_M, MoE high/low noise)
WAN22_HIGH_NOISE_GGUF = "Wan2.2-T2V-A14B-HighNoise-Q4_K_M.gguf"
WAN22_LOW_NOISE_GGUF = "Wan2.2-T2V-A14B-LowNoise-Q4_K_M.gguf"
WAN22_VAE = "Wan2.1_VAE.safetensors"
WAN22_TEXT_ENCODER = "umt5-xxl-enc-fp8_e4m3fn.safetensors"
WAN22_UPSCALE_MODEL = "RealESRGAN_x4plus.pth"
PYTORCH_CUDA_ALLOC_CONF_VALUE = "expandable_segments:True"
COMFYUI_SCOPE_UNIT = "vfx-comfyui-video.scope"
COMFYUI_DIR = os.path.join(PIPELINE_PATH, "ComfyUI")
MAX_VIDEO_WIDTH = 720
MAX_VIDEO_HEIGHT = 720
MAX_VIDEO_FRAMES = 81


class GateDenied(Exception):
	pass


# --- Validação básica (Fase 2) ---

def validate_pipeline_path(path: str = PIPELINE_PATH) -> bool:
	return os.path.isdir(path) and os.access(path, os.W_OK)


def check_binary(name: str, fallback_paths: Optional[list[str]] = None) -> bool:
	if shutil.which(name) is not None:
		return True
	for candidate in fallback_paths or []:
		if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
			return True
	return False


def check_port_free(port: int, host: str = "127.0.0.1") -> bool:
	with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
		sock.settimeout(1)
		return sock.connect_ex((host, port)) != 0


# --- Logging persistente ---

def setup_logger(log_path: str = LOG_PATH, dry_run: bool = False) -> logging.Logger:
	logger = logging.getLogger("run_vfx")
	logger.setLevel(logging.INFO)
	logger.handlers.clear()
	fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
	if not dry_run:
		os.makedirs(os.path.dirname(log_path), exist_ok=True)
		fh = logging.FileHandler(log_path)
		fh.setFormatter(fmt)
		logger.addHandler(fh)
	sh = logging.StreamHandler(sys.stdout)
	sh.setFormatter(fmt)
	logger.addHandler(sh)
	return logger


def log_gate_decision(logger: logging.Logger, gate_name: str, decision: str, details: str = "") -> None:
	logger.info(f"GATE {gate_name} | decisao={decision} | {details}")


# --- Confirmação interativa [Y/n] (não bloqueia o event loop) ---

async def confirm(prompt: str) -> bool:
	try:
		answer = await asyncio.to_thread(input, f"{prompt} [Y/n] ")
	except EOFError as exc:
		# Achado real: 'conda run' nao repassa stdin ao processo filho, entao input()
		# aqui derruba com EOFError cru e confuso. Isso NAO acontece com 'conda activate
		# <env> && python run_vfx.py ...' (uso normal). Gate 3 nunca e pulavel, entao esse
		# erro sempre aparece se rodar via 'conda run' sem --auto-approve cobrir o gate.
		raise RuntimeError(
			"Este gate precisa de confirmacao interativa, mas stdin nao esta disponivel "
			"(EOF). Se estiver usando 'conda run -n <env> python run_vfx.py ...', troque "
			"por 'conda activate <env> && python run_vfx.py ...' - 'conda run' nao repassa "
			"stdin corretamente."
		) from exc
	return answer.strip().lower() in ("", "y", "yes", "s", "sim")


# --- Wayland guard ---

def build_subprocess_env() -> dict:
	env = os.environ.copy()
	env["QT_QPA_PLATFORM"] = "offscreen"
	return env


# --- Gate 1: Jaula de Memória ---

def _parse_memory_to_bytes(value: str) -> int:
	units = {"K": 1024, "M": 1024**2, "G": 1024**3}
	value = value.strip().upper()
	if value and value[-1] in units:
		return int(float(value[:-1]) * units[value[-1]])
	return int(value)


def _apply_rlimit(memory_bytes: int):
	def _setter():
		resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
	return _setter


async def gate_1_memory_jail(
	logger: logging.Logger, mode: str = "faceswap", auto_approve: bool = False, dry_run: bool = False
) -> dict:
	memory_max = MEMORY_MAX_VIDEO if mode == "video" else MEMORY_MAX_DEFAULT
	# MemorySwapMax é sempre definido explicitamente (nunca deixado default/ilimitado): testado ao vivo que
	# MemoryMax sozinho NAO mata o processo quando ha swap disponivel no sistema - o kernel prefere reclamar
	# (empurrar paginas anonimas pro /swapfile compartilhado) em vez de OOM-kill. Sem MemorySwapMax=0 no modo
	# padrao, um subprocesso descontrolado entraria em thrashing no swap do servidor inteiro (o mesmo risco que
	# o modo video generativo reconhece explicitamente, so que sem a mitigacao). No modo video, 4G de colchao
	# de emergencia é aceito de proposito (ver Fase 3B).
	memory_swap_max = MEMORY_SWAP_MAX_VIDEO if mode == "video" else "0"
	detail = f"MemoryMax={memory_max} MemorySwapMax={memory_swap_max}"

	if dry_run:
		log_gate_decision(logger, "1-memoria", "dry-run (nao aplicado)", detail)
		return {"memory_max": memory_max, "memory_swap_max": memory_swap_max}

	if auto_approve:
		log_gate_decision(logger, "1-memoria", "auto-aprovado", detail)
	else:
		approved = await confirm(f"Gate 1 - Jaula de memoria: subprocesso sera limitado a {detail}. Prosseguir?")
		if not approved:
			log_gate_decision(logger, "1-memoria", "negado", detail)
			raise GateDenied("Gate 1 negado pelo usuario")
		log_gate_decision(logger, "1-memoria", "aprovado", detail)

	return {"memory_max": memory_max, "memory_swap_max": memory_swap_max}


async def run_in_memory_jail(
	cmd: list[str],
	memory_max: str,
	memory_swap_max: Optional[str] = None,
	cwd: Optional[str] = None,
	env: Optional[dict] = None,
	logger: Optional[logging.Logger] = None,
	force_fallback: bool = False,
):
	memory_bytes = _parse_memory_to_bytes(memory_max)

	if not force_fallback and check_binary("systemd-run"):
		scope_unit = f"vfx-{uuid.uuid4().hex[:8]}.scope"
		systemd_cmd = ["systemd-run", "--user", "--scope", "--unit", scope_unit, "-p", f"MemoryMax={memory_max}"]
		if memory_swap_max:
			systemd_cmd += ["-p", f"MemorySwapMax={memory_swap_max}"]
		systemd_cmd += ["--", *cmd]

		proc = await asyncio.create_subprocess_exec(
			*systemd_cmd, cwd=cwd, env=env,
			stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
		)
		stdout, stderr = await proc.communicate()

		dbus_failure = proc.returncode != 0 and (
			b"Failed to connect to bus" in stderr or b"Failed to create bus connection" in stderr
		)
		if not dbus_failure:
			return proc.returncode, stdout, stderr

		if logger:
			logger.warning("systemd-run sem sessao DBus disponivel, caindo para o Plano B (resource.setrlimit)")

	if logger:
		logger.info(f"Plano B: aplicando limite via resource.setrlimit ({memory_max})")

	proc = await asyncio.create_subprocess_exec(
		*cmd, cwd=cwd, env=env,
		stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
		preexec_fn=_apply_rlimit(memory_bytes),
	)
	stdout, stderr = await proc.communicate()
	return proc.returncode, stdout, stderr


# --- Gate 2: Pico de VRAM, RAM e Swap ---

async def get_vram_free_mb() -> Optional[int]:
	def _query():
		try:
			out = subprocess.check_output(
				["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
				text=True, timeout=5,
			)
			return int(out.strip().splitlines()[0])
		except Exception:
			return None
	return await asyncio.to_thread(_query)


def get_ram_free_mb() -> int:
	with open("/proc/meminfo") as f:
		for line in f:
			if line.startswith("MemAvailable:"):
				return int(line.split()[1]) // 1024
	return 0


def get_swap_used_mb() -> int:
	total = free = 0
	with open("/proc/meminfo") as f:
		for line in f:
			if line.startswith("SwapTotal:"):
				total = int(line.split()[1])
			elif line.startswith("SwapFree:"):
				free = int(line.split()[1])
	return (total - free) // 1024


async def unload_ollama_model(logger: logging.Logger, model: str = "qwen") -> None:
	if not check_binary("ollama"):
		logger.warning("Binario 'ollama' nao encontrado, nao foi possivel descarregar o modelo")
		return
	proc = await asyncio.create_subprocess_exec(
		"ollama", "stop", model,
		stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
	)
	await proc.communicate()
	logger.info(f"Ollama: 'ollama stop {model}' executado (servico ollama.service nao foi parado)")


async def gate_2_vram_check(
	logger: logging.Logger, mode: str = "faceswap", auto_approve: bool = False, dry_run: bool = False
) -> dict:
	vram_free_mb = await get_vram_free_mb()
	if vram_free_mb is None:
		# nvidia-smi falhou/indisponivel: assume o pior (alerta), nao o melhor - uma leitura
		# desconhecida nao pode ser tratada como "VRAM livre o suficiente".
		peak_alert = True
		detail = "VRAM livre=DESCONHECIDA (nvidia-smi falhou)"
	else:
		vram_free_gb = vram_free_mb / 1024
		peak_alert = vram_free_gb < VRAM_PEAK_ALERT_GB
		detail = f"VRAM livre={vram_free_gb:.1f}GB"

	ram_free_mb = swap_used_mb = None
	tight = peak_alert

	if mode == "video":
		ram_free_mb = get_ram_free_mb()
		swap_used_mb = get_swap_used_mb()
		detail += f" RAM livre={ram_free_mb / 1024:.1f}GB swap usado={swap_used_mb / 1024:.1f}GB"
		tight = tight or ram_free_mb < 4096 or swap_used_mb > 2048

	if peak_alert:
		detail += f" [ALERTA: abaixo do pico esperado de {VRAM_PEAK_ALERT_GB}GB]"

	if mode == "video" and tight and not dry_run:
		if auto_approve:
			logger.info("Recursos apertados e --auto-approve ativo: descarregando Ollama automaticamente (sem prompt).")
			unload = True
		else:
			unload = await confirm("Recursos apertados por causa do Qwen. Descarregar o modelo do Ollama antes de prosseguir?")
		if unload:
			await unload_ollama_model(logger)
			vram_free_mb = await get_vram_free_mb()
			vram_free_gb = (vram_free_mb or 0) / 1024
			detail = f"VRAM livre={vram_free_gb:.1f}GB (apos descarregar Ollama)"
			if mode == "video":
				ram_free_mb = get_ram_free_mb()
				swap_used_mb = get_swap_used_mb()
				detail += f" RAM livre={ram_free_mb / 1024:.1f}GB swap usado={swap_used_mb / 1024:.1f}GB"

	if dry_run:
		log_gate_decision(logger, "2-vram", "dry-run (nao aplicado)", detail)
		return {"vram_free_mb": vram_free_mb, "ram_free_mb": ram_free_mb, "swap_used_mb": swap_used_mb}

	if auto_approve:
		log_gate_decision(logger, "2-vram", "auto-aprovado", detail)
	else:
		approved = await confirm(f"Gate 2 - Pico de VRAM/RAM/Swap: {detail}. Prosseguir com o POST ao ComfyUI?")
		if not approved:
			log_gate_decision(logger, "2-vram", "negado", detail)
			raise GateDenied("Gate 2 negado pelo usuario")
		log_gate_decision(logger, "2-vram", "aprovado", detail)

	return {"vram_free_mb": vram_free_mb, "ram_free_mb": ram_free_mb, "swap_used_mb": swap_used_mb}


# --- Gate 3: I/O de Disco (nunca pulável, mesmo com --auto-approve) ---

def get_disk_free_gb(path: str = "/") -> float:
	usage = shutil.disk_usage(path)
	return usage.free / (1024**3)


async def gate_3_disk_check(logger: logging.Logger, auto_approve: bool = False, dry_run: bool = False) -> dict:
	free_gb = get_disk_free_gb("/")
	detail = f"espaco livre em /={free_gb:.1f}GB (margem minima={DISK_SAFETY_MARGIN_GB}GB)"

	if free_gb < DISK_SAFETY_MARGIN_GB:
		log_gate_decision(logger, "3-disco", "abortado (abaixo da margem)", detail)
		raise GateDenied(f"Gate 3: espaco insuficiente ({detail})")

	if dry_run:
		log_gate_decision(logger, "3-disco", "dry-run (nao aplicado)", detail)
		return {"free_gb": free_gb}

	# auto_approve é ignorado de propósito: Gate 3 sempre pede confirmação manual.
	approved = await confirm(f"Gate 3 - I/O de disco (NVENC): {detail}. Prosseguir com escrita em {PIPELINE_PATH}?")
	if not approved:
		log_gate_decision(logger, "3-disco", "negado", detail)
		raise GateDenied("Gate 3 negado pelo usuario")
	log_gate_decision(logger, "3-disco", "aprovado", detail)
	return {"free_gb": free_gb}


# --- Higiene de metadados EXIF ---

async def sanitize_exif(image_path: str, logger: Optional[logging.Logger] = None) -> bool:
	if not check_binary("exiftool"):
		if logger:
			logger.error("exiftool nao encontrado - instale com 'sudo apt install libimage-exiftool-perl'")
		raise RuntimeError("exiftool ausente no sistema")
	proc = await asyncio.create_subprocess_exec(
		"exiftool", "-all=", "-overwrite_original", image_path,
		stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
	)
	_, stderr = await proc.communicate()
	ok = proc.returncode == 0
	if logger:
		log_gate_decision(logger, "exif-hygiene", "ok" if ok else f"falhou: {stderr.decode(errors='ignore')}", image_path)
	return ok


# --- Polling dinâmico do ComfyUI ---

async def poll_comfyui_system_stats(
	host: str = COMFYUI_HOST, port: int = COMFYUI_PORT, interval: float = 2.0, timeout: float = 60.0,
	logger: Optional[logging.Logger] = None,
):
	import time
	import aiohttp

	deadline = time.monotonic() + timeout
	url = f"http://{host}:{port}/system_stats"
	async with aiohttp.ClientSession() as session:
		while time.monotonic() < deadline:
			try:
				async with session.get(url, timeout=aiohttp.ClientTimeout(total=3)) as resp:
					if resp.status == 200:
						data = await resp.json(content_type=None)
						if logger:
							pytorch_version = data.get("system", {}).get("pytorch_version", "desconhecida")
							logger.info(f"ComfyUI pronto: {pytorch_version}")
						return data
			except (aiohttp.ClientError, asyncio.TimeoutError, TimeoutError):
				pass  # servidor ainda subindo/nao aceitando conexoes - esperado, continua tentando
			await asyncio.sleep(interval)
	raise TimeoutError("ComfyUI nao respondeu /system_stats dentro do timeout")


async def ensure_comfyui_running_under_jail(
	memory_max: str, memory_swap_max: str, logger: logging.Logger,
	comfyui_dir: str = COMFYUI_DIR, conda_env: str = "vfx-pipeline",
) -> None:
	"""Garante que o ComfyUI esteja rodando dentro de um systemd scope com o limite de
	memoria do Gate 1 e com PYTORCH_CUDA_ALLOC_CONF setado. Achado da revisao: sem isso,
	o modo video calculava o limite mas nunca o aplicava - o ComfyUI ficava rodando solto
	na propria sessao de login (sem MemoryMax/MemorySwapMax nenhum), exatamente o cenario
	de thrashing que o Gate 1 existe para evitar. Se ja estiver rodando dentro do scope
	esperado, reaproveita em vez de reiniciar."""
	if not check_binary("systemd-run"):
		logger.warning(
			"systemd-run indisponivel - ComfyUI ficara SEM jaula de memoria no modo video "
			"(risco real de thrashing de swap no servidor inteiro)."
		)
		return

	check = await asyncio.create_subprocess_exec(
		"systemctl", "--user", "is-active", COMFYUI_SCOPE_UNIT,
		stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
	)
	await check.communicate()
	if check.returncode == 0:
		logger.info(f"ComfyUI ja esta rodando dentro do scope {COMFYUI_SCOPE_UNIT}, reaproveitando.")
		return

	if not check_port_free(COMFYUI_PORT):
		logger.info(f"Encerrando instancia do ComfyUI fora da jaula (porta {COMFYUI_PORT} ocupada) antes de reiniciar presa.")
		if check_binary("fuser"):
			kill_proc = await asyncio.create_subprocess_exec(
				"fuser", "-k", f"{COMFYUI_PORT}/tcp",
				stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
			)
			await kill_proc.communicate()
			await asyncio.sleep(2)
		else:
			raise RuntimeError(
				f"Porta {COMFYUI_PORT} ocupada e 'fuser' indisponivel para liberar - "
				"encerre a instancia atual do ComfyUI manualmente antes de rodar o modo video."
			)

	env = build_subprocess_env()
	env["PYTORCH_CUDA_ALLOC_CONF"] = PYTORCH_CUDA_ALLOC_CONF_VALUE
	conda_python = os.path.expanduser(f"~/miniconda3/envs/{conda_env}/bin/python")
	log_path = os.path.join(PIPELINE_PATH, "logs", "comfyui_video_mode.log")
	os.makedirs(os.path.dirname(log_path), exist_ok=True)

	systemd_cmd = [
		"systemd-run", "--user", "--scope", "--unit", COMFYUI_SCOPE_UNIT,
		"-p", f"MemoryMax={memory_max}", "-p", f"MemorySwapMax={memory_swap_max}",
		"--", conda_python, "main.py", "--port", str(COMFYUI_PORT), "--listen", COMFYUI_HOST,
	]
	with open(log_path, "ab") as log_file:
		proc = await asyncio.create_subprocess_exec(
			*systemd_cmd, cwd=comfyui_dir, env=env,
			stdout=log_file, stderr=log_file, start_new_session=True,
		)
	logger.info(
		f"ComfyUI reiniciado sob jaula de memoria (scope={COMFYUI_SCOPE_UNIT}, "
		f"MemoryMax={memory_max}, MemorySwapMax={memory_swap_max}, PID={proc.pid})"
	)
	await poll_comfyui_system_stats(logger=logger, timeout=90.0)


# --- Fase 3B: workflow Wan2.2 T2V-A14B (GGUF, block swap, VAE tiled) ---

def build_wan22_video_workflow(
	positive_prompt: str,
	negative_prompt: str = "baixa qualidade, distorcido, tremido",
	width: int = 320,
	height: int = 320,
	num_frames: int = 17,
	steps: int = 10,
	blocks_to_swap: int = 20,
	cfg: float = 6.0,
	shift: float = 8.0,
	seed: int = 43,
	filename_prefix: str = "wan22_teste_fase3b",
) -> dict:
	"""Monta o prompt no formato de API do ComfyUI (nao o formato do editor visual) para um
	clipe curto de teste com o Wan2.2 T2V-A14B em GGUF, usando os dois experts MoE
	(high/low noise) encadeados, block swap compartilhado e decode em modo tiled.
	Steps sao divididos ao meio entre os dois experts (metade dos steps em cada um),
	seguindo o mesmo padrao observado no workflow de exemplo oficial do WanVideoWrapper."""
	switch_step = steps // 2
	return {
		"blockswap_args": {
			"class_type": "WanVideoBlockSwap",
			"inputs": {
				"blocks_to_swap": blocks_to_swap,
				"offload_img_emb": False,
				"offload_txt_emb": False,
			},
		},
		"loader_high": {
			"class_type": "WanVideoModelLoader",
			"inputs": {
				"model": WAN22_HIGH_NOISE_GGUF,
				"base_precision": "fp16",
				"quantization": "disabled",
				"load_device": "offload_device",
			},
		},
		"loader_high_bs": {
			"class_type": "WanVideoSetBlockSwap",
			"inputs": {
				"model": ["loader_high", 0],
				"block_swap_args": ["blockswap_args", 0],
			},
		},
		"loader_low": {
			"class_type": "WanVideoModelLoader",
			"inputs": {
				"model": WAN22_LOW_NOISE_GGUF,
				"base_precision": "fp16",
				"quantization": "disabled",
				"load_device": "offload_device",
			},
		},
		"loader_low_bs": {
			"class_type": "WanVideoSetBlockSwap",
			"inputs": {
				"model": ["loader_low", 0],
				"block_swap_args": ["blockswap_args", 0],
			},
		},
		"t5": {
			"class_type": "LoadWanVideoT5TextEncoder",
			"inputs": {
				"model_name": WAN22_TEXT_ENCODER,
				"precision": "bf16",
				"quantization": "disabled",
			},
		},
		"text_encode": {
			"class_type": "WanVideoTextEncode",
			"inputs": {
				"positive_prompt": positive_prompt,
				"negative_prompt": negative_prompt,
				"t5": ["t5", 0],
			},
		},
		"empty_embeds": {
			"class_type": "WanVideoEmptyEmbeds",
			"inputs": {
				"width": width,
				"height": height,
				"num_frames": num_frames,
			},
		},
		"sampler_high": {
			"class_type": "WanVideoSampler",
			"inputs": {
				"model": ["loader_high_bs", 0],
				"image_embeds": ["empty_embeds", 0],
				"text_embeds": ["text_encode", 0],
				"steps": steps,
				"cfg": cfg,
				"shift": shift,
				"seed": seed,
				"force_offload": True,
				"scheduler": "dpm++_sde",
				"riflex_freq_index": 0,
				"end_step": switch_step,
			},
		},
		"sampler_low": {
			"class_type": "WanVideoSampler",
			"inputs": {
				"model": ["loader_low_bs", 0],
				"image_embeds": ["empty_embeds", 0],
				"text_embeds": ["text_encode", 0],
				"samples": ["sampler_high", 0],
				"steps": steps,
				"cfg": cfg,
				"shift": shift,
				"seed": seed,
				"force_offload": True,
				"scheduler": "dpm++_sde",
				"riflex_freq_index": 0,
				"start_step": switch_step,
			},
		},
		"vae_loader": {
			"class_type": "WanVideoVAELoader",
			"inputs": {
				"model_name": WAN22_VAE,
				"precision": "bf16",
			},
		},
		"decode": {
			"class_type": "WanVideoDecode",
			"inputs": {
				"vae": ["vae_loader", 0],
				"samples": ["sampler_low", 0],
				"enable_vae_tiling": True,
				"tile_x": 128,
				"tile_y": 128,
				"tile_stride_x": 64,
				"tile_stride_y": 64,
			},
		},
		"upscale_model": {
			"class_type": "UpscaleModelLoader",
			"inputs": {
				"model_name": WAN22_UPSCALE_MODEL,
			},
		},
		"upscale": {
			"class_type": "ImageUpscaleWithModel",
			"inputs": {
				"upscale_model": ["upscale_model", 0],
				"image": ["decode", 0],
			},
		},
		"save": {
			# Achado real: o demuxer webp do ffmpeg (usado na Fase 4) nao le direito webp
			# animado (chunks ANIM/ANMF) mesmo sendo um formato valido - "Decode error rate
			# 1 exceeds maximum" e o job de masterizacao falha. VHS_VideoCombine gera MP4
			# de verdade, que o ffmpeg le sem drama nenhum.
			"class_type": "VHS_VideoCombine",
			"inputs": {
				"images": ["upscale", 0],
				"frame_rate": 8,
				"loop_count": 0,
				"filename_prefix": filename_prefix,
				"format": "video/h264-mp4",
				"pingpong": False,
				"save_output": True,
			},
		},
	}


async def submit_comfyui_prompt(
	workflow: dict, host: str = COMFYUI_HOST, port: int = COMFYUI_PORT, logger: Optional[logging.Logger] = None,
) -> str:
	import aiohttp

	url = f"http://{host}:{port}/prompt"
	async with aiohttp.ClientSession() as session:
		async with session.post(url, json={"prompt": workflow}, timeout=aiohttp.ClientTimeout(total=30)) as resp:
			body_text = await resp.text()
			if resp.status != 200:
				if logger:
					logger.error(f"ComfyUI rejeitou o prompt (HTTP {resp.status}): {body_text}")
				raise RuntimeError(f"Falha ao submeter prompt ao ComfyUI (HTTP {resp.status}): {body_text}")
			try:
				data = await resp.json(content_type=None)
			except Exception as exc:
				if logger:
					logger.error(f"Resposta do ComfyUI nao e JSON valido: {body_text}")
				raise RuntimeError(f"Resposta do ComfyUI nao e JSON valido: {exc}") from exc
			if "prompt_id" not in data:
				if logger:
					logger.error(f"ComfyUI nao retornou prompt_id: {data}")
				raise RuntimeError(f"Falha ao submeter prompt ao ComfyUI: {data}")
			if logger:
				logger.info(f"Prompt submetido ao ComfyUI: prompt_id={data['prompt_id']}")
			return data["prompt_id"]


async def wait_for_comfyui_prompt(
	prompt_id: str, host: str = COMFYUI_HOST, port: int = COMFYUI_PORT,
	interval: float = 3.0, timeout: float = 3600.0, logger: Optional[logging.Logger] = None,
) -> dict:
	import time
	import aiohttp

	deadline = time.monotonic() + timeout
	url = f"http://{host}:{port}/history/{prompt_id}"
	async with aiohttp.ClientSession() as session:
		while time.monotonic() < deadline:
			try:
				async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
					data = await resp.json(content_type=None)
			except (asyncio.TimeoutError, TimeoutError) as exc:
				if logger:
					logger.warning(f"Timeout consultando /history/{prompt_id}, tentando de novo: {exc}")
				await asyncio.sleep(interval)
				continue
			if prompt_id in data:
				entry = data[prompt_id]
				status = entry.get("status", {})
				if status.get("completed") is True or status.get("status_str") == "success":
					if logger:
						logger.info(f"Render Wan2.2 concluido: prompt_id={prompt_id}")
					return entry
				if status.get("status_str") == "error":
					if logger:
						logger.error(f"Render Wan2.2 falhou: {status}")
					raise RuntimeError(f"ComfyUI reportou erro no prompt {prompt_id}: {status}")
			await asyncio.sleep(interval)
	raise TimeoutError(f"Prompt {prompt_id} nao terminou dentro do timeout de {timeout}s")


# --- Fase 4: Render Final e Masterização ---

def build_ffmpeg_mastering_command(
	original_path: str,
	processed_video_path: str,
	output_path: str,
	fps: float = 24.0,
	video_codec: str = "h264_nvenc",
) -> list[str]:
	"""Costura o video processado (saida do FaceFusion ou do Wan2.2) de volta com o
	audio/legendas/metadados do arquivo original intactos. Video vem do arquivo processado
	(-map 1:v:0); audio e legendas vem do original sem recodificar (-c:a copy -c:s copy,
	preserva 5.1/7.1 e faixas de legenda bit-a-bit). CFR via `-fps_mode cfr` (nao `-vsync`,
	que esta deprecated no ffmpeg 6.x instalado neste servidor). Matriz de cor bt709 fixada
	explicitamente para evitar shift de cor entre o clipe processado e o original."""
	return [
		"ffmpeg", "-y",
		"-i", original_path,
		"-i", processed_video_path,
		"-map", "1:v:0",
		"-map", "0:a?",
		"-map", "0:s?",
		"-map_metadata", "0",
		"-fps_mode", "cfr",
		"-r", str(fps),
		"-color_primaries", "bt709",
		"-color_trc", "bt709",
		"-colorspace", "bt709",
		"-c:v", video_codec,
		"-c:a", "copy",
		"-c:s", "copy",
		output_path,
	]


# --- FaceFusion (modo de rosto de referência) ---

def build_facefusion_command(source_path: str, target_path: str, output_path: str, reference_face_position: int = 0) -> list[str]:
	return [
		"python", "facefusion.py", "headless-run",
		"-s", source_path,
		"-t", target_path,
		"-o", output_path,
		"--face-selector-mode", "reference",
		"--reference-face-position", str(reference_face_position),
		"--execution-providers", "cuda",
	]


# --- Orquestração principal ---

async def orchestrate(args: argparse.Namespace, logger: logging.Logger) -> int:
	if not validate_pipeline_path():
		logger.error(f"Caminho do pipeline invalido/nao gravavel: {PIPELINE_PATH}")
		return 1
	if not check_binary("ffmpeg"):
		logger.error("ffmpeg nao encontrado")
		return 1

	memory_cfg = await gate_1_memory_jail(logger, mode=args.mode, auto_approve=args.auto_approve, dry_run=args.dry_run)
	await gate_2_vram_check(logger, mode=args.mode, auto_approve=args.auto_approve, dry_run=args.dry_run)
	await gate_3_disk_check(logger, auto_approve=args.auto_approve, dry_run=args.dry_run)

	if args.dry_run:
		logger.info("DRY-RUN: nenhum subprocesso/chamada de API real foi executado. Pipeline validado do inicio ao fim.")
		return 0

	if args.mode == "video":
		if not args.prompt:
			logger.error("Modo video requer --prompt")
			return 1
		if args.width > MAX_VIDEO_WIDTH or args.height > MAX_VIDEO_HEIGHT or args.num_frames > MAX_VIDEO_FRAMES:
			logger.error(
				f"Resolucao/duracao acima do orcamento assumido pelos Gates 1/2 "
				f"(max {MAX_VIDEO_WIDTH}x{MAX_VIDEO_HEIGHT}, {MAX_VIDEO_FRAMES} frames)."
			)
			return 1
		await ensure_comfyui_running_under_jail(
			memory_max=memory_cfg["memory_max"], memory_swap_max=memory_cfg["memory_swap_max"], logger=logger,
		)
		workflow = build_wan22_video_workflow(
			positive_prompt=args.prompt,
			width=args.width,
			height=args.height,
			num_frames=args.num_frames,
		)
		prompt_id = await submit_comfyui_prompt(workflow, logger=logger)
		await wait_for_comfyui_prompt(prompt_id, logger=logger, timeout=3600.0)
		logger.info("Render Wan2.2 (Fase 3B) concluido com sucesso, sem OOM.")
		return 0

	if args.mode == "master":
		if not args.original or not args.processed_video or not args.output:
			logger.error("Modo master requer --original, --processed-video e --output")
			return 1
		if not os.path.isfile(args.original) or not os.path.isfile(args.processed_video):
			logger.error("Arquivo --original ou --processed-video nao encontrado no disco")
			return 1
		env = build_subprocess_env()
		cmd = build_ffmpeg_mastering_command(args.original, args.processed_video, args.output, fps=args.fps)
		returncode, stdout, stderr = await run_in_memory_jail(
			cmd, memory_max=memory_cfg["memory_max"], memory_swap_max=memory_cfg["memory_swap_max"], env=env, logger=logger,
		)
		if returncode != 0:
			logger.error(f"FFmpeg (masterizacao) falhou (codigo {returncode}): {stderr.decode(errors='ignore')}")
			return 1
		logger.info(f"Masterizacao concluida com sucesso: {args.output}")
		return 0

	if not args.source or not args.target or not args.output:
		logger.error("Modo faceswap requer --source, --target e --output")
		return 1

	if not await sanitize_exif(args.source, logger):
		logger.error("Higiene de metadados EXIF falhou - abortando antes de rodar o FaceFusion com metadados nao higienizados.")
		return 1

	env = build_subprocess_env()
	cmd = build_facefusion_command(args.source, args.target, args.output)
	returncode, stdout, stderr = await run_in_memory_jail(
		cmd,
		memory_max=memory_cfg["memory_max"],
		memory_swap_max=memory_cfg["memory_swap_max"],
		cwd=os.path.join(PIPELINE_PATH, "facefusion"),
		env=env,
		logger=logger,
	)
	if returncode != 0:
		logger.error(f"FaceFusion falhou (codigo {returncode}): {stderr.decode(errors='ignore')}")
		return 1

	logger.info("FaceFusion concluido com sucesso.")
	return 0


def build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(description="AP AI Studio - orquestrador do pipeline VFX")
	parser.add_argument("--mode", choices=["faceswap", "video", "master"], default="faceswap")
	parser.add_argument("--source", type=str, default=None)
	parser.add_argument("--target", type=str, default=None)
	parser.add_argument("--output", type=str, default=None)
	parser.add_argument("--dry-run", action="store_true")
	parser.add_argument("--auto-approve", action="store_true")
	parser.add_argument("--prompt", type=str, default=None, help="Prompt de texto (modo video)")
	parser.add_argument("--width", type=int, default=320)
	parser.add_argument("--height", type=int, default=320)
	parser.add_argument("--num-frames", type=int, default=17)
	parser.add_argument("--original", type=str, default=None, help="Video original (audio/legendas), modo master")
	parser.add_argument("--processed-video", type=str, default=None, help="Video processado (FaceFusion/Wan2.2), modo master")
	parser.add_argument("--fps", type=float, default=24.0, help="Frame rate constante de saida (modo master)")
	return parser


async def main_async(argv: Optional[list[str]] = None) -> int:
	args = build_parser().parse_args(argv)
	logger = setup_logger(dry_run=args.dry_run)
	logger.info(f"Iniciando run_vfx.py | modo={args.mode} dry_run={args.dry_run} auto_approve={args.auto_approve}")
	try:
		return await orchestrate(args, logger)
	except GateDenied as exc:
		logger.error(f"Pipeline abortado: {exc}")
		return 1


def main(argv: Optional[list[str]] = None) -> int:
	return asyncio.run(main_async(argv))


if __name__ == "__main__":
	sys.exit(main())
