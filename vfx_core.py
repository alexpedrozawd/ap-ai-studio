"""Utilitarios de base sem dependencia de gates/comfyui/facefusion especificos -
validacao de caminho/binario/porta, logging persistente e confirmacao interativa.
Todo outro modulo (vfx_gates, vfx_comfyui, vfx_facefusion, vfx_ffmpeg) depende deste,
mas ele nao depende de nenhum deles - evita import circular.
"""

import asyncio
import logging
import logging.handlers
import os
import shutil
import socket
import sys
from typing import Optional

from vfx_config import LOG_PATH, LOG_TRUNCATE_THRESHOLD_BYTES, PIPELINE_PATH


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
