import argparse
import asyncio
import glob
import logging
import logging.handlers
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
WAN22_I2V_HIGH_NOISE_GGUF = "Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf"
WAN22_I2V_LOW_NOISE_GGUF = "Wan2.2-I2V-A14B-LowNoise-Q4_K_M.gguf"
WAN22_VAE = "Wan2.1_VAE.safetensors"
WAN22_TEXT_ENCODER = "umt5-xxl-enc-fp8_e4m3fn.safetensors"
WAN22_UPSCALE_MODEL = "RealESRGAN_x4plus.pth"
WAN22_INTERPOLATION_MODEL = "rife_v4.25.safetensors"
WAN22_OUTPUT_FPS = 30  # pedido do usuario: fluidez proxima de cinema/TV (16fps nativo x2 = 32, salvo a 30)

# Fase 6: remocao de objeto / edicao geral de imagem (inpainting)
INPAINT_CHECKPOINT = "sd_xl_base_1.0_inpainting_0.1.safetensors"
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

LOG_TRUNCATE_THRESHOLD_BYTES = 5 * 1024 * 1024


def truncate_log_if_large(log_path: str, threshold_bytes: int = LOG_TRUNCATE_THRESHOLD_BYTES) -> None:
	"""Pros logs de boot do ComfyUI (redirecionamento cru de stdout/stderr de subprocesso,
	nao um logging.Logger) - RotatingFileHandler nao se aplica aqui. Truncamento simples
	em vez de rotacao com backups, suficiente pra um log de diagnostico de boot."""
	try:
		if os.path.isfile(log_path) and os.path.getsize(log_path) > threshold_bytes:
			open(log_path, "w").close()
	except OSError:
		pass  # nao vale travar a subida do ComfyUI por causa de um log de diagnostico


def setup_logger(log_path: str = LOG_PATH, dry_run: bool = False) -> logging.Logger:
	logger = logging.getLogger("run_vfx")
	logger.setLevel(logging.INFO)
	logger.handlers.clear()
	fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
	if not dry_run:
		os.makedirs(os.path.dirname(log_path), exist_ok=True)
		# Achado de auditoria: sem rotacao, run_vfx.log cresce pra sempre (disco
		# compartilhado com o SO, ver Fase 1). 5MB x 5 arquivos de backup e' generoso
		# pro volume de log deste pipeline (cada job gera algumas dezenas de linhas).
		fh = logging.handlers.RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=5)
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


async def free_comfyui_vram(host: str = COMFYUI_HOST, port: int = COMFYUI_PORT, logger: Optional[logging.Logger] = None) -> None:
	"""Achado real (chunked faceswap falhou com 'Failed to allocate memory for requested
	buffer of size 294912' - so 288KB, mesmo com 8GB 'livres' segundo nvidia-smi): o ComfyUI
	mantem modelos em cache na VRAM entre execucoes (ex.: o checkpoint SDXL de 7GB do
	inpainting ficou carregado ate um teste de FaceFusion completamente sem relacao precisar
	de memoria). Chamar /free antes de qualquer operacao pesada do FaceFusion evita essa
	disputa de memoria entre processos GPU diferentes (ComfyUI + FaceFusion sao processos
	separados, cada um com sua propria nocao de 'memoria livre' que nao conta o que o outro
	esta segurando)."""
	try:
		import aiohttp
		async with aiohttp.ClientSession() as session:
			async with session.post(
				f"http://{host}:{port}/free", json={"unload_models": True, "free_memory": True},
				timeout=aiohttp.ClientTimeout(total=10),
			) as resp:
				if logger:
					logger.info(f"VRAM do ComfyUI liberada antes da operacao (HTTP {resp.status})")
	except Exception as exc:
		if logger:
			logger.warning(f"Nao foi possivel liberar VRAM do ComfyUI (provavelmente nao esta rodando, tudo bem): {exc}")


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
	truncate_log_if_large(log_path)

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


def stage_image_for_comfyui(source_path: str) -> str:
	"""O node LoadImage do ComfyUI so aceita nomes de arquivo dentro de 'ComfyUI/input/',
	nao um caminho absoluto qualquer do sistema (ve 'folder_paths.get_annotated_filepath').
	Copia a imagem de origem pra la com um nome unico e devolve so o nome do arquivo, que e
	o que o workflow da API espera no campo 'image'."""
	os.makedirs(COMFYUI_INPUT_DIR, exist_ok=True)
	extension = os.path.splitext(source_path)[1] or ".png"
	staged_name = f"i2v_source_{uuid.uuid4().hex[:8]}{extension}"
	shutil.copy(source_path, os.path.join(COMFYUI_INPUT_DIR, staged_name))
	return staged_name


# --- Fase 3B: workflow Wan2.2 T2V-A14B (GGUF, block swap, VAE tiled) ---

def build_wan22_video_workflow(
	positive_prompt: str,
	negative_prompt: str = "baixa qualidade, distorcido, tremido",
	width: int = 320,
	height: int = 320,
	num_frames: int = 161,  # ~10s a 16fps (media pedida pelo usuario: 10-15s)
	steps: int = 10,
	blocks_to_swap: int = 20,
	cfg: float = 6.0,
	shift: float = 8.0,
	seed: int = 43,
	filename_prefix: str = "wan22_teste_fase3b",
	source_image_path: Optional[str] = None,
) -> dict:
	"""Monta o prompt no formato de API do ComfyUI (nao o formato do editor visual) para um
	clipe de teste com o Wan2.2 A14B em GGUF, usando os dois experts MoE (high/low noise)
	encadeados, block swap compartilhado e decode em modo tiled. Steps sao divididos ao meio
	entre os dois experts (metade dos steps em cada um), seguindo o mesmo padrao observado no
	workflow de exemplo oficial do WanVideoWrapper. Se `source_image_path` for informado, monta
	o modo I2V (imagem -> video, anima uma foto existente) em vez de T2V (texto -> video) - os
	dois usam pesos GGUF diferentes (Wan2.2-I2V-A14B vs Wan2.2-T2V-A14B) mas o resto do grafo
	(block swap, samplers, decode, interpolacao, upscale, save) e identico."""
	is_i2v = source_image_path is not None
	high_noise_model = WAN22_I2V_HIGH_NOISE_GGUF if is_i2v else WAN22_HIGH_NOISE_GGUF
	low_noise_model = WAN22_I2V_LOW_NOISE_GGUF if is_i2v else WAN22_LOW_NOISE_GGUF
	switch_step = steps // 2

	workflow = {
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
				"model": high_noise_model,
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
				"model": low_noise_model,
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
		"vae_loader": {
			"class_type": "WanVideoVAELoader",
			"inputs": {
				"model_name": WAN22_VAE,
				"precision": "bf16",
			},
		},
	}

	if is_i2v:
		workflow["load_image"] = {
			"class_type": "LoadImage",
			"inputs": {"image": source_image_path},
		}
		workflow["resize_image"] = {
			"class_type": "ImageScale",
			"inputs": {
				"image": ["load_image", 0],
				"upscale_method": "lanczos",
				"width": width,
				"height": height,
				"crop": "center",
			},
		}
		workflow["image_embeds"] = {
			"class_type": "WanVideoImageToVideoEncode",
			"inputs": {
				"width": width,
				"height": height,
				"num_frames": num_frames,
				"noise_aug_strength": 0.0,
				"start_latent_strength": 1.0,
				"end_latent_strength": 1.0,
				"force_offload": True,
				"vae": ["vae_loader", 0],
				"start_image": ["resize_image", 0],
			},
		}
		embeds_node = "image_embeds"
	else:
		workflow["empty_embeds"] = {
			"class_type": "WanVideoEmptyEmbeds",
			"inputs": {
				"width": width,
				"height": height,
				"num_frames": num_frames,
			},
		}
		embeds_node = "empty_embeds"

	workflow["sampler_high"] = {
		"class_type": "WanVideoSampler",
		"inputs": {
			"model": ["loader_high_bs", 0],
			"image_embeds": [embeds_node, 0],
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
	}
	workflow["sampler_low"] = {
		"class_type": "WanVideoSampler",
		"inputs": {
			"model": ["loader_low_bs", 0],
			"image_embeds": [embeds_node, 0],
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
	}

	workflow.update({
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
		"interp_model": {
			"class_type": "FrameInterpolationModelLoader",
			"inputs": {
				"model_name": WAN22_INTERPOLATION_MODEL,
			},
		},
		"interpolate": {
			# Pedido do usuario: fluidez proxima de cinema (~30fps), nao so mudar o numero de
			# frame_rate na hora de salvar (isso so mudaria a VELOCIDADE, nao a suavidade real -
			# foi exatamente o bug do frame_rate=8 encontrado antes). RIFE gera quadros
			# intermediarios de verdade entre os frames existentes. multiplier=2 dobra os
			# quadros (16fps nativo -> 32 quadros/s reais), salvos a WAN22_OUTPUT_FPS (30).
			"class_type": "FrameInterpolate",
			"inputs": {
				"interp_model": ["interp_model", 0],
				"images": ["decode", 0],
				"multiplier": 2,
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
				"image": ["interpolate", 0],
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
				# Achado real (confirmado nos workflows de exemplo do proprio Kijai): o modelo
				# A14B (o que usamos) gera nativamente a 16fps - usar 8 aqui deixava o clipe em
				# camera lenta sem ninguem perceber (frames corretos, velocidade de playback errada).
				# 24fps nos exemplos dele e especifico do modelo 5B, que nao usamos. Com a
				# interpolacao (multiplier=2) os quadros reais dobram pra ~32/s, entao salvar a
				# WAN22_OUTPUT_FPS (30) da a fluidez pedida sem alterar a duracao real do clipe.
				"frame_rate": WAN22_OUTPUT_FPS,
				"loop_count": 0,
				"filename_prefix": filename_prefix,
				"format": "video/h264-mp4",
				"pingpong": False,
				"save_output": True,
			},
		},
	})

	return workflow


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
						logger.info(f"Job do ComfyUI concluido: prompt_id={prompt_id}")
					return entry
				if status.get("status_str") == "error":
					if logger:
						logger.error(f"Job do ComfyUI falhou: {status}")
					raise RuntimeError(f"ComfyUI reportou erro no prompt {prompt_id}: {status}")
			await asyncio.sleep(interval)
	raise TimeoutError(f"Prompt {prompt_id} nao terminou dentro do timeout de {timeout}s")


def get_comfyui_output_file(history_entry: dict, node_id: str = "save") -> str:
	"""Acha o caminho real do arquivo que um node de saida (SaveImage/VHS_VideoCombine)
	gravou, a partir do retorno de /history. Achado real: o modo inpaint estava ignorando
	--output completamente - o resultado sempre ficava com o nome fixo do
	filename_prefix dentro de ComfyUI/output/, sem nenhum jeito de saber onde parou."""
	outputs = history_entry.get("outputs", {}).get(node_id, {})
	files = outputs.get("images") or outputs.get("gifs") or []
	if not files:
		raise RuntimeError(f"Nenhum arquivo de saida encontrado no node '{node_id}' do resultado do ComfyUI")
	first = files[0]
	return os.path.join(COMFYUI_DIR, "output", first.get("subfolder", ""), first["filename"])


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


# --- Fase 6: inpainting (remover objeto / editar imagem) ---

def build_inpaint_workflow(
	image_filename: str,
	mask_filename: str,
	positive_prompt: str = "",
	negative_prompt: str = "baixa qualidade, artefatos, borrado",
	steps: int = 25,
	cfg: float = 7.0,
	denoise: float = 1.0,
	seed: int = 42,
	filename_prefix: str = "inpaint_resultado",
) -> dict:
	"""Monta o prompt de API pra remover/editar uma area de uma imagem via inpainting SDXL.
	`mask_filename` e uma imagem separada (branco = area a apagar/redesenhar, preto = manter) -
	abordagem padrao de mascara manual, mais simples e previsivel que segmentacao automatica
	por texto (que exigiria baixar mais um modelo tipo GroundingDINO+SAM - deixado de fora por
	enquanto, ver PROMPT_MASTER.md). positive_prompt vazio funciona bem pra "remover objeto"
	simples (o modelo preenche com o que faz sentido pro fundo); usar um prompt descritivo
	quando quiser colocar algo especifico no lugar."""
	return {
		"checkpoint": {
			"class_type": "CheckpointLoaderSimple",
			"inputs": {"ckpt_name": INPAINT_CHECKPOINT},
		},
		"load_image": {
			"class_type": "LoadImage",
			"inputs": {"image": image_filename},
		},
		"load_mask": {
			"class_type": "LoadImage",
			"inputs": {"image": mask_filename},
		},
		"mask_to_grayscale": {
			"class_type": "ImageToMask",
			"inputs": {"image": ["load_mask", 0], "channel": "red"},
		},
		"positive": {
			"class_type": "CLIPTextEncode",
			"inputs": {"text": positive_prompt, "clip": ["checkpoint", 1]},
		},
		"negative": {
			"class_type": "CLIPTextEncode",
			"inputs": {"text": negative_prompt, "clip": ["checkpoint", 1]},
		},
		"encode_inpaint": {
			"class_type": "VAEEncodeForInpaint",
			"inputs": {
				"pixels": ["load_image", 0],
				"vae": ["checkpoint", 2],
				"mask": ["mask_to_grayscale", 0],
				"grow_mask_by": 6,
			},
		},
		"sampler": {
			"class_type": "KSampler",
			"inputs": {
				"model": ["checkpoint", 0],
				"seed": seed,
				"steps": steps,
				"cfg": cfg,
				"sampler_name": "dpmpp_2m",
				"scheduler": "karras",
				"positive": ["positive", 0],
				"negative": ["negative", 0],
				"latent_image": ["encode_inpaint", 0],
				"denoise": denoise,
			},
		},
		"decode": {
			"class_type": "VAEDecode",
			"inputs": {"samples": ["sampler", 0], "vae": ["checkpoint", 2]},
		},
		"save": {
			"class_type": "SaveImage",
			"inputs": {"images": ["decode", 0], "filename_prefix": filename_prefix},
		},
	}


# --- FaceFusion (modo de rosto de referência) ---

FACEFUSION_CONDA_ENV = "facefusion-pipeline"


def build_facefusion_command(source_path: str, target_path: str, output_path: str, reference_face_position: int = 0) -> list[str]:
	"""Achado real (primeiro face-swap end-to-end): usar so 'python' aqui resolve pro
	interprete do ambiente Conda que estiver ativo no processo do run_vfx.py (vfx-pipeline,
	do ComfyUI) - onde nao existe onnxruntime instalado. FaceFusion vive num ambiente Conda
	SEPARADO (facefusion-pipeline, ver Fase 1). Preciso do caminho explicito do interprete
	desse outro ambiente, nao do 'python' generico do PATH herdado."""
	conda_python = os.path.expanduser(f"~/miniconda3/envs/{FACEFUSION_CONDA_ENV}/bin/python")
	return [
		conda_python, "facefusion.py", "headless-run",
		"-s", source_path,
		"-t", target_path,
		"-o", output_path,
		"--face-selector-mode", "reference",
		"--reference-face-position", str(reference_face_position),
		"--execution-providers", "cuda",
	]


def build_background_remover_command(target_path: str, output_path: str) -> list[str]:
	conda_python = os.path.expanduser(f"~/miniconda3/envs/{FACEFUSION_CONDA_ENV}/bin/python")
	return [
		conda_python, "facefusion.py", "headless-run",
		"--processors", "background_remover",
		"-t", target_path,
		"-o", output_path,
		"--execution-providers", "cuda",
	]


def build_lip_syncer_command(
	source_audio_path: str, target_video_path: str, output_path: str, execution_providers: str = "cpu",
) -> list[str]:
	"""DECISAO OFICIAL (nao e mais um TODO): CPU e o modo definitivo do lip_syncer neste
	servidor, ate o ecossistema onnxruntime/TensorRT amadurecer suporte pra essa GPU.

	Causa raiz confirmada: a RTX 5060 Ti e arquitetura Blackwell, compute capability sm_120.
	O onnxruntime-gpu oficial (testado 1.26.0 e 1.27.0) nao traz kernels cuBLAS compilados pra
	essa arquitetura ainda (confirmado em issues abertas no repo oficial microsoft/onnxruntime,
	ex. #26245/#26177) - o wav2lip usa uma operacao de cuBLAS sem caminho de fallback JIT e
	falha com 'CUBLAS failure 3: the resource allocation failed'.

	Alternativas avaliadas e descartadas (nao sao 'sim, mas' - trocam um problema contornavel
	por um risco maior ou esforco desproporcional):
	  - Atualizar onnxruntime-gpu -> exige libcudart.so.13, pacotes pip pra CUDA 13 falham ao
	    compilar wheel neste ambiente.
	  - Forcar --execution-providers tensorrt -> SDK completo nao instalado, cai pra CPU do
	    mesmo jeito (e nao ha garantia de suporte a sm_120 nem instalando).
	  - Build nao-oficial com kernels sm_120 (Natfii/onnxruntime-gpu-blackwell) -> 0 estrelas,
	    sem manutencao, risco de seguranca real pra rodar binario pre-compilado nao verificado.
	  - Reimplementar wav2lip em PyTorch (que ja funciona bem nessa GPU, confirmado no
	    WanVideoWrapper/TTS/Demucs) -> exigiria patchear o codigo-fonte do FaceFusion, fragil
	    contra atualizacoes deles, desproporcional pro ganho.

	CPU valida ponta a ponta (~136s pra um clipe de 270 frames). 'cuda'/'tensorrt' continuam
	disponiveis via parametro pra reavaliar no futuro sem mudanca de codigo, quando o
	ecossistema atualizar."""
	conda_python = os.path.expanduser(f"~/miniconda3/envs/{FACEFUSION_CONDA_ENV}/bin/python")
	return [
		conda_python, "facefusion.py", "headless-run",
		"--processors", "lip_syncer",
		"-s", source_audio_path,
		"-t", target_video_path,
		"-o", output_path,
		"--execution-providers", execution_providers,
	]


def build_facefusion_env() -> dict:
	"""Achado real: o onnxruntime-gpu do ambiente facefusion-pipeline nao acha as bibliotecas
	CUDA 12.x mesmo com nvidia-cublas-cu12/nvidia-cudnn-cu12 instaladas via pip - elas ficam
	dentro do site-packages, fora do caminho de busca do linker dinamico. Diferente do torch
	(que se auto-registra), onnxruntime plain precisa de LD_LIBRARY_PATH explicito. Sem isso,
	falha silenciosamente pra CPU (bem mais lento, sem nenhum erro visivel no retorno)."""
	env = build_subprocess_env()
	site_packages = os.path.expanduser(f"~/miniconda3/envs/{FACEFUSION_CONDA_ENV}/lib/python3.11/site-packages")
	nvidia_dir = os.path.join(site_packages, "nvidia")
	if os.path.isdir(nvidia_dir):
		lib_dirs = [
			os.path.join(nvidia_dir, pkg, "lib")
			for pkg in os.listdir(nvidia_dir)
			if os.path.isdir(os.path.join(nvidia_dir, pkg, "lib"))
		]
		existing = env.get("LD_LIBRARY_PATH", "")
		env["LD_LIBRARY_PATH"] = ":".join(lib_dirs + ([existing] if existing else []))
	return env


# --- Fase 8: TTS/clonagem de voz (dublagem) ---

TTS_CONDA_ENV = "tts-pipeline"
TTS_SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tts_synthesize.py")


def build_tts_command(
	text: str, output_path: str, language: str = "pt", speaker: Optional[str] = None, speaker_wav: Optional[str] = None,
) -> list[str]:
	"""XTTS-v2 roda num ambiente Conda proprio (tts-pipeline), separado do vfx-pipeline e do
	facefusion-pipeline - achado real: o pacote coqui-tts (e o node ComfyUI-XTTS que tentamos
	primeiro) precisam de transformers==4.57.6 especificamente (versoes mais novas removeram
	uma funcao que o codigo interno do XTTS ainda usa; versoes mais antigas nao satisfazem o
	minimo que o proprio coqui-tts declara) - incompativel com o transformers mais novo que o
	WanVideoWrapper usa no mesmo processo do ComfyUI. Roda como script standalone, mesmo
	padrao do FaceFusion."""
	conda_python = os.path.expanduser(f"~/miniconda3/envs/{TTS_CONDA_ENV}/bin/python")
	cmd = [conda_python, TTS_SCRIPT_PATH, "--text", text, "--output", output_path, "--language", language]
	if speaker:
		cmd += ["--speaker", speaker]
	if speaker_wav:
		cmd += ["--speaker-wav", speaker_wav]
	return cmd


# --- Fase 10: geração de música ---

def build_musicgen_workflow(
	prompt: str, duration: float = 5.0, model_size: str = "small",
	guidance_scale: float = 3.0, seed: int = 42, filename_prefix: str = "musicgen_resultado",
) -> dict:
	"""MusicGen (Meta AI) via node pack `ComfyUI-MusicGen-HF`, roda no mesmo processo/ambiente
	do ComfyUI (nao precisa de ambiente Conda separado - ao contrario de TTS/Demucs, nao teve
	conflito de dependencia). Achado real: o node MusicGenAudioToFile falha com
	FileNotFoundError se a pasta 'ComfyUI/output/audio/' nao existir ainda - ele nao cria o
	diretorio sozinho antes de escrever o arquivo (bug do node pack, nao nosso)."""
	max_new_tokens = int(duration * 51.2)  # ~256 tokens para 5s, escala linear (medido ao vivo)
	return {
		"musicgen": {
			"class_type": "HuggingFaceMusicGen",
			"inputs": {
				"model_size": model_size,
				"duration": duration,
				"guidance_scale": guidance_scale,
				"do_sample": True,
				"max_new_tokens": max_new_tokens,
				"seed": seed,
				"prompt": prompt,
			},
		},
		"save": {
			"class_type": "MusicGenAudioToFile",
			"inputs": {
				"audio": ["musicgen", 0],
				"filename": filename_prefix,
				"format": "wav",
			},
		},
	}


def ensure_comfyui_audio_output_dir() -> None:
	"""Achado real: MusicGenAudioToFile derruba com FileNotFoundError na primeira execucao
	porque 'ComfyUI/output/audio/' nao existe por padrao - so foi criada manualmente durante
	o teste. Chamado antes de qualquer job de musica pra nao depender de setup manual."""
	os.makedirs(os.path.join(COMFYUI_DIR, "output", "audio"), exist_ok=True)


# --- Fase 9: remoção de ruído / isolamento de voz ---

DEMUCS_CONDA_ENV = "noise-pipeline"
DEMUCS_SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demucs_separate.py")


def build_demucs_command(
	input_path: str, output_vocals: str, output_instrumental: Optional[str] = None, model: str = "htdemucs",
) -> list[str]:
	"""Demucs (Meta AI) roda num ambiente Conda proprio (noise-pipeline). Achado real: o
	torch instalado por padrao via pip (2.6.0+cu124) da 'CUDA error: no kernel image is
	available for execution on the device' nessa RTX 5060 Ti - GPU nova demais pros kernels
	pre-compilados dessa versao. Corrigido com torch 2.12.1+cu130 (mesma versao que ja
	funciona no vfx-pipeline/ComfyUI). Tambem precisou de 'torchcodec' extra, que o torchaudio
	dessa versao usa por padrao pra salvar audio (nao vem junto por padrao)."""
	conda_python = os.path.expanduser(f"~/miniconda3/envs/{DEMUCS_CONDA_ENV}/bin/python")
	cmd = [conda_python, DEMUCS_SCRIPT_PATH, "--input", input_path, "--output-vocals", output_vocals, "--model", model]
	if output_instrumental:
		cmd += ["--output-instrumental", output_instrumental]
	return cmd


# --- Fase 7: processar vídeos longos em pedaços (cenas/filmes inteiros) ---

async def get_video_duration_seconds(video_path: str) -> float:
	proc = await asyncio.create_subprocess_exec(
		"ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", video_path,
		stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
	)
	stdout, stderr = await proc.communicate()
	if proc.returncode != 0:
		raise RuntimeError(f"Falha ao ler duracao do video: {stderr.decode(errors='ignore')}")
	return float(stdout.decode().strip())


async def split_video_into_chunks(video_path: str, chunk_seconds: int, output_dir: str, logger: Optional[logging.Logger] = None) -> list[str]:
	"""Divide um video em pedacos de ate `chunk_seconds` cada. Achado real (pego por um teste
	funcional, nao mock): `-c copy` (stream-copy) so corta em keyframes - um video de teste com
	keyframes espacados virou 1 pedaco so em vez dos 3+ esperados, quebrando silenciosamente o
	proposito de limitar o tamanho por pedaco. Recodifica de proposito (libx264 ultrafast) pra
	cortar exatamente no tempo pedido - sem perda de qualidade composta, porque cada pedaco
	ainda vai ser decodificado/recodificado de novo pelo FaceFusion na etapa seguinte de
	qualquer jeito, entao o stream-copy aqui nao preservava nada na pratica."""
	os.makedirs(output_dir, exist_ok=True)
	pattern = os.path.join(output_dir, "chunk_%04d.mp4")
	cmd = [
		"ffmpeg", "-y", "-i", video_path,
		"-map", "0:v:0", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
		"-f", "segment", "-segment_time", str(chunk_seconds),
		"-reset_timestamps", "1", "-force_key_frames", f"expr:gte(t,n_forced*{chunk_seconds})",
		pattern,
	]
	proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
	_, stderr = await proc.communicate()
	if proc.returncode != 0:
		raise RuntimeError(f"Falha ao dividir video em pedacos: {stderr.decode(errors='ignore')}")
	chunks = sorted(glob.glob(os.path.join(output_dir, "chunk_*.mp4")))
	if logger:
		logger.info(f"Video dividido em {len(chunks)} pedacos de ate {chunk_seconds}s cada")
	return chunks


async def concat_video_chunks(chunk_paths: list[str], output_path: str, logger: Optional[logging.Logger] = None) -> None:
	list_file = f"{output_path}.concat_list.txt"
	with open(list_file, "w") as f:
		for chunk in chunk_paths:
			f.write(f"file '{os.path.abspath(chunk)}'\n")
	cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", output_path]
	proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
	_, stderr = await proc.communicate()
	os.remove(list_file)
	if proc.returncode != 0:
		raise RuntimeError(f"Falha ao juntar pedacos de video: {stderr.decode(errors='ignore')}")
	if logger:
		logger.info(f"{len(chunk_paths)} pedacos remontados em: {output_path}")


async def process_long_faceswap(
	source_path: str, target_video_path: str, final_output_path: str, original_for_audio: str,
	memory_cfg: dict, chunk_seconds: int, logger: logging.Logger,
) -> int:
	"""Processa uma cena/filme inteiro rodando o face-swap pedaco por pedaco (evita carregar
	o video inteiro de uma vez na jaula de memoria do Gate 1), remonta os pedacos processados
	e costura com o audio/legendas do original via Fase 4. Cada pedaco roda dentro da MESMA
	jaula de memoria calculada pelo Gate 1 - nao e um teto por pedaco, e o mesmo teto do
	processo inteiro, entao pedacos menores = menos chance de estourar por pedaco."""
	duration = await get_video_duration_seconds(target_video_path)
	if duration <= chunk_seconds:
		logger.info(f"Video ({duration:.1f}s) cabe num unico pedaco (limite {chunk_seconds}s) - processando sem dividir.")
		cmd = build_facefusion_command(source_path, target_video_path, final_output_path)
		returncode, stdout, stderr = await run_in_memory_jail(
			cmd, memory_max=memory_cfg["memory_max"], memory_swap_max=memory_cfg["memory_swap_max"],
			cwd=os.path.join(PIPELINE_PATH, "facefusion"), env=build_facefusion_env(), logger=logger,
		)
		return returncode

	chunk_dir = os.path.join(PIPELINE_PATH, "tmp", f"chunks_{uuid.uuid4().hex[:8]}")
	logger.info(f"Video de {duration:.1f}s excede o limite de {chunk_seconds}s por pedaco - dividindo antes de processar.")
	raw_chunks = await split_video_into_chunks(target_video_path, chunk_seconds, os.path.join(chunk_dir, "raw"), logger)

	processed_chunks = []
	for i, raw_chunk in enumerate(raw_chunks):
		free_gb = get_disk_free_gb("/")
		if free_gb < DISK_SAFETY_MARGIN_GB:
			raise GateDenied(f"Gate 3: espaco insuficiente no meio do processamento em pedacos ({free_gb:.1f}GB livres)")
		processed_path = os.path.join(chunk_dir, "processed", f"chunk_{i:04d}.mp4")
		os.makedirs(os.path.dirname(processed_path), exist_ok=True)
		logger.info(f"Processando pedaco {i + 1}/{len(raw_chunks)}: {raw_chunk}")
		cmd = build_facefusion_command(source_path, raw_chunk, processed_path)
		returncode, stdout, stderr = await run_in_memory_jail(
			cmd, memory_max=memory_cfg["memory_max"], memory_swap_max=memory_cfg["memory_swap_max"],
			cwd=os.path.join(PIPELINE_PATH, "facefusion"), env=build_facefusion_env(), logger=logger,
		)
		if returncode != 0:
			raise RuntimeError(f"Pedaco {i + 1}/{len(raw_chunks)} falhou (codigo {returncode}): {stderr.decode(errors='ignore')}")
		processed_chunks.append(processed_path)

	concatenated_path = os.path.join(chunk_dir, "concatenado.mp4")
	await concat_video_chunks(processed_chunks, concatenated_path, logger)

	master_cmd = build_ffmpeg_mastering_command(original_for_audio, concatenated_path, final_output_path)
	proc = await asyncio.create_subprocess_exec(*master_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
	_, stderr = await proc.communicate()
	if proc.returncode != 0:
		logger.error(f"Masterizacao final dos pedacos falhou: {stderr.decode(errors='ignore')}")
		return proc.returncode

	shutil.rmtree(chunk_dir, ignore_errors=True)
	logger.info(f"Processamento em {len(raw_chunks)} pedacos concluido: {final_output_path}")
	return 0


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
		staged_image_name = None
		if args.source_image:
			if not os.path.isfile(args.source_image):
				logger.error(f"--source-image nao encontrado: {args.source_image}")
				return 1
			staged_image_name = stage_image_for_comfyui(args.source_image)
			logger.info(f"Modo I2V (imagem->video): {args.source_image} copiada para ComfyUI/input/{staged_image_name}")

		await ensure_comfyui_running_under_jail(
			memory_max=memory_cfg["memory_max"], memory_swap_max=memory_cfg["memory_swap_max"], logger=logger,
		)
		workflow = build_wan22_video_workflow(
			positive_prompt=args.prompt,
			width=args.width,
			height=args.height,
			num_frames=args.num_frames,
			source_image_path=staged_image_name,
		)
		prompt_id = await submit_comfyui_prompt(workflow, logger=logger)
		history_entry = await wait_for_comfyui_prompt(prompt_id, logger=logger, timeout=3600.0)
		logger.info("Render Wan2.2 (Fase 3B/5) concluido com sucesso, sem OOM.")
		if args.output:
			# Achado real (interface web): igual aos outros modos que geram arquivo
			# (inpaint/removebg/master/tts/denoise/music), --output aqui so' funciona
			# porque get_comfyui_output_file() ja e' generico o suficiente pro node
			# VHS_VideoCombine (id "save") do workflow de video - nao precisou mudar
			# a funcao, so passou a ser chamada tambem por este modo.
			comfyui_output_path = get_comfyui_output_file(history_entry)
			shutil.copy(comfyui_output_path, args.output)
			logger.info(f"Video copiado para: {args.output}")
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

	if args.mode == "inpaint":
		if not args.source_image or not args.mask_image or not args.output:
			logger.error("Modo inpaint requer --source-image, --mask-image e --output")
			return 1
		if not os.path.isfile(args.source_image) or not os.path.isfile(args.mask_image):
			logger.error("--source-image ou --mask-image nao encontrado no disco")
			return 1
		if not args.prompt:
			logger.warning(
				"Modo inpaint sem --prompt: com prompt vazio, o SDXL as vezes preenche a area "
				"com conteudo estranho em vez de continuar o fundo naturalmente. Recomendado "
				"descrever o que deveria aparecer no lugar (ex.: 'fundo gradiente rosa e azul liso')."
			)
		staged_image = stage_image_for_comfyui(args.source_image)
		staged_mask = stage_image_for_comfyui(args.mask_image)
		await poll_comfyui_system_stats(logger=logger, timeout=60.0)
		workflow = build_inpaint_workflow(
			image_filename=staged_image,
			mask_filename=staged_mask,
			positive_prompt=args.prompt or "",
		)
		prompt_id = await submit_comfyui_prompt(workflow, logger=logger)
		history_entry = await wait_for_comfyui_prompt(prompt_id, logger=logger, timeout=600.0)
		comfyui_output_path = get_comfyui_output_file(history_entry)
		shutil.copy(comfyui_output_path, args.output)
		logger.info(f"Inpainting (Fase 6) concluido com sucesso: {args.output}")
		return 0

	if args.mode == "removebg":
		if not args.target or not args.output:
			logger.error("Modo removebg requer --target e --output")
			return 1
		if not os.path.isfile(args.target):
			logger.error(f"--target nao encontrado: {args.target}")
			return 1
		await free_comfyui_vram(logger=logger)
		cmd = build_background_remover_command(args.target, args.output)
		returncode, stdout, stderr = await run_in_memory_jail(
			cmd, memory_max=memory_cfg["memory_max"], memory_swap_max=memory_cfg["memory_swap_max"],
			cwd=os.path.join(PIPELINE_PATH, "facefusion"), env=build_facefusion_env(), logger=logger,
		)
		if returncode != 0:
			logger.error(f"Remocao de fundo falhou (codigo {returncode}): {stderr.decode(errors='ignore')}")
			return 1
		logger.info(f"Remocao de fundo (Fase 6) concluida: {args.output}")
		return 0

	if args.mode == "tts":
		if not args.text or not args.output:
			logger.error("Modo tts requer --text e --output")
			return 1
		if not args.speaker and not args.speaker_wav:
			logger.error("Modo tts requer --speaker (voz embutida) ou --speaker-wav (clonar voz de uma amostra)")
			return 1
		if args.speaker_wav and not os.path.isfile(args.speaker_wav):
			logger.error(f"--speaker-wav nao encontrado: {args.speaker_wav}")
			return 1
		cmd = build_tts_command(args.text, args.output, language=args.language, speaker=args.speaker, speaker_wav=args.speaker_wav)
		returncode, stdout, stderr = await run_in_memory_jail(
			cmd, memory_max=memory_cfg["memory_max"], memory_swap_max=memory_cfg["memory_swap_max"], logger=logger,
		)
		if returncode != 0:
			logger.error(f"TTS falhou (codigo {returncode}): {stderr.decode(errors='ignore')}")
			return 1
		logger.info(f"TTS (Fase 8) concluido: {args.output}")
		return 0

	if args.mode == "denoise":
		if not args.target or not args.output:
			logger.error("Modo denoise requer --target (audio de entrada) e --output (voz isolada)")
			return 1
		if not os.path.isfile(args.target):
			logger.error(f"--target nao encontrado: {args.target}")
			return 1
		cmd = build_demucs_command(args.target, args.output, output_instrumental=args.output_instrumental)
		returncode, stdout, stderr = await run_in_memory_jail(
			cmd, memory_max=memory_cfg["memory_max"], memory_swap_max=memory_cfg["memory_swap_max"], logger=logger,
		)
		if returncode != 0:
			logger.error(f"Remocao de ruido falhou (codigo {returncode}): {stderr.decode(errors='ignore')}")
			return 1
		logger.info(f"Remocao de ruido/isolamento de voz (Fase 9) concluido: {args.output}")
		return 0

	if args.mode == "music":
		if not args.prompt or not args.output:
			logger.error("Modo music requer --prompt e --output")
			return 1
		ensure_comfyui_audio_output_dir()
		await poll_comfyui_system_stats(logger=logger, timeout=60.0)
		workflow = build_musicgen_workflow(prompt=args.prompt, duration=args.music_duration)
		prompt_id = await submit_comfyui_prompt(workflow, logger=logger)
		# Achado real: MusicGenAudioToFile nao registra o arquivo em entry["outputs"] do jeito
		# que SaveImage/VHS_VideoCombine fazem (RETURN_TYPES e so STRING, sem marcar como saida
		# de UI) - get_comfyui_output_file() nao serve aqui. Acha o arquivo mais recente com o
		# prefixo esperado, por data de modificacao (mais confiavel que ordem de listdir).
		await wait_for_comfyui_prompt(prompt_id, logger=logger, timeout=300.0)
		audio_dir = os.path.join(COMFYUI_DIR, "output", "audio")
		candidates = [os.path.join(audio_dir, f) for f in os.listdir(audio_dir) if f.startswith("musicgen_resultado")]
		if not candidates:
			logger.error("Nenhum arquivo de musica encontrado apos o job concluir")
			return 1
		comfyui_output_path = max(candidates, key=os.path.getmtime)
		shutil.copy(comfyui_output_path, args.output)
		logger.info(f"Musica (Fase 10) concluida: {args.output}")
		return 0

	if not args.source or not args.target or not args.output:
		logger.error("Modo faceswap requer --source, --target e --output")
		return 1

	if not await sanitize_exif(args.source, logger):
		logger.error("Higiene de metadados EXIF falhou - abortando antes de rodar o FaceFusion com metadados nao higienizados.")
		return 1

	await free_comfyui_vram(logger=logger)

	if args.chunk_seconds:
		try:
			returncode = await process_long_faceswap(
				args.source, args.target, args.output, original_for_audio=args.target,
				memory_cfg=memory_cfg, chunk_seconds=args.chunk_seconds, logger=logger,
			)
		except (RuntimeError, GateDenied) as exc:
			logger.error(f"Processamento em pedacos falhou: {exc}")
			return 1
		if returncode != 0:
			return 1
		logger.info("FaceFusion (Fase 7, processado em pedacos) concluido com sucesso.")
		return 0

	env = build_facefusion_env()
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
	parser.add_argument("--mode", choices=["faceswap", "video", "master", "inpaint", "removebg", "tts", "denoise", "music"], default="faceswap")
	parser.add_argument("--source", type=str, default=None)
	parser.add_argument("--target", type=str, default=None)
	parser.add_argument("--output", type=str, default=None)
	parser.add_argument("--dry-run", action="store_true")
	parser.add_argument("--auto-approve", action="store_true")
	parser.add_argument("--prompt", type=str, default=None, help="Prompt de texto (modo video)")
	parser.add_argument("--source-image", type=str, default=None, help="Foto de origem para animar (modo I2V) ou editar (modo inpaint)")
	parser.add_argument("--mask-image", type=str, default=None, help="Mascara branco=apagar/preto=manter (modo inpaint)")
	parser.add_argument("--chunk-seconds", type=int, default=None, help="Processa video longo (modo faceswap) em pedacos de N segundos")
	parser.add_argument("--text", type=str, default=None, help="Texto a sintetizar (modo tts)")
	parser.add_argument("--language", type=str, default="pt", help="Idioma da fala (modo tts)")
	parser.add_argument("--speaker", type=str, default=None, help="Nome de uma voz embutida do XTTS-v2 (modo tts)")
	parser.add_argument("--speaker-wav", type=str, default=None, help="Amostra de audio pra clonar a voz (modo tts)")
	parser.add_argument("--output-instrumental", type=str, default=None, help="Caminho pro resto do audio sem a voz (modo denoise)")
	parser.add_argument("--music-duration", type=float, default=5.0, help="Duracao em segundos da musica gerada (modo music)")
	parser.add_argument("--width", type=int, default=320)
	parser.add_argument("--height", type=int, default=320)
	parser.add_argument("--num-frames", type=int, default=161)  # ~10s a 16fps
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
