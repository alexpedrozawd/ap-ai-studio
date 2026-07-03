"""Comunicacao HTTP com o ComfyUI (submeter/consultar prompt, liberar VRAM) e gestao
do processo dele sob a jaula de memoria do Gate 1 no modo video.
"""

import asyncio
import logging
import os
import shutil
import uuid
from typing import Optional

from vfx_config import (
	COMFYUI_DIR,
	COMFYUI_HOST,
	COMFYUI_INPUT_DIR,
	COMFYUI_PORT,
	COMFYUI_SCOPE_UNIT,
	PIPELINE_PATH,
	PYTORCH_CUDA_ALLOC_CONF_VALUE,
)
from vfx_core import build_subprocess_env, check_binary, check_port_free, truncate_log_if_large


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


def ensure_comfyui_audio_output_dir() -> None:
	"""Achado real: MusicGenAudioToFile derruba com FileNotFoundError na primeira execucao
	porque 'ComfyUI/output/audio/' nao existe por padrao - so foi criada manualmente durante
	o teste. Chamado antes de qualquer job de musica pra nao depender de setup manual."""
	os.makedirs(os.path.join(COMFYUI_DIR, "output", "audio"), exist_ok=True)
