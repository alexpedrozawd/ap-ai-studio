"""Os 3 "Authorization Gates" (memoria, VRAM/RAM/swap, disco) que pausam o pipeline
antes de qualquer operacao pesada - ver PROMPT_MASTER.md Fase 3 pro design original.
"""

import asyncio
import logging
import resource
import shutil
import subprocess
import uuid
from typing import Optional

from vfx_config import (
	DISK_SAFETY_MARGIN_GB,
	GateDenied,
	MEMORY_MAX_DEFAULT,
	MEMORY_MAX_VIDEO,
	MEMORY_SWAP_MAX_VIDEO,
	NVIDIA_SMI_PATH,
	PIPELINE_PATH,
	VRAM_PEAK_ALERT_GB,
)
from vfx_core import check_binary, confirm, log_gate_decision


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
				[NVIDIA_SMI_PATH, "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
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
