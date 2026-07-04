"""FFmpeg (masterizacao final, corte/juncao de video em pedacos), higiene de EXIF, e
o processamento de faceswap/upscale em video longo que combina tudo isso com o Gate 1.
"""

import asyncio
import glob
import logging
import os
import shutil
import uuid
from typing import Optional

from vfx_comfyui import (
	get_comfyui_output_file,
	stage_image_for_comfyui,
	submit_comfyui_prompt,
	wait_for_comfyui_prompt,
)
from vfx_config import DISK_SAFETY_MARGIN_GB, GateDenied, PIPELINE_PATH
from vfx_core import check_binary
from vfx_facefusion import build_facefusion_command, build_facefusion_env
from vfx_gates import get_disk_free_gb, run_in_memory_jail
from vfx_workflows import build_upscale_workflow


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
		from vfx_core import log_gate_decision
		log_gate_decision(logger, "exif-hygiene", "ok" if ok else f"falhou: {stderr.decode(errors='ignore')}", image_path)
	return ok


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
	face_selector_gender: Optional[str] = None,
) -> int:
	"""Processa uma cena/filme inteiro rodando o face-swap pedaco por pedaco (evita carregar
	o video inteiro de uma vez na jaula de memoria do Gate 1), remonta os pedacos processados
	e costura com o audio/legendas do original via Fase 4. Cada pedaco roda dentro da MESMA
	jaula de memoria calculada pelo Gate 1 - nao e um teto por pedaco, e o mesmo teto do
	processo inteiro, entao pedacos menores = menos chance de estourar por pedaco.

	`face_selector_gender` repassa pro `build_facefusion_command` (ver achado real #2 la') -
	util em cenas com mais de uma pessoa, onde o modo `reference` sozinho pode perder o rosto
	certo ou pegar o errado por engano."""
	duration = await get_video_duration_seconds(target_video_path)
	if duration <= chunk_seconds:
		logger.info(f"Video ({duration:.1f}s) cabe num unico pedaco (limite {chunk_seconds}s) - processando sem dividir.")
		cmd = build_facefusion_command(source_path, target_video_path, final_output_path, face_selector_gender=face_selector_gender)
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
		cmd = build_facefusion_command(source_path, raw_chunk, processed_path, face_selector_gender=face_selector_gender)
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
	assert proc.returncode is not None  # communicate() so garante retorno depois do processo terminar
	if proc.returncode != 0:
		logger.error(f"Masterizacao final dos pedacos falhou: {stderr.decode(errors='ignore')}")
		return proc.returncode

	shutil.rmtree(chunk_dir, ignore_errors=True)
	logger.info(f"Processamento em {len(raw_chunks)} pedacos concluido: {final_output_path}")
	return 0


# --- Upscale de video longo em pedacos (achado real: OOM confirmado ao vivo) ---
# O modo upscale (ImageUpscaleWithModel) carrega o video INTEIRO como um unico lote de
# frames na VRAM/RAM antes de processar - ao contrario do FaceFusion, que streama frame a
# frame. Um teste ao vivo com um clipe de 26s/625 frames em 640x360 (saida 4x = 2560x1440)
# estourou a jaula de memoria padrao (24G, mesma do Gate 1 pra modo != "video") e foi morto
# pelo OOM killer aos ~10min, sem gerar nenhuma saida (journalctl: "Failed with result
# 'oom-kill'", memory peak 24.0G). Corrigido dividindo em pedacos (mesmo padrao ja usado em
# process_long_faceswap) - cada pedaco carrega só os frames daquele trecho de uma vez.
# Tambem corrige um bug separado: o modo upscale de video nunca remuxava o audio original
# (build_upscale_workflow so' passa "images" pro VHS_VideoCombine) - o video upscalado saia
# mudo mesmo no caminho de pedaco unico. Agora sempre remonta com o audio/legendas originais
# via build_ffmpeg_mastering_command, igual ao faceswap.

async def _run_single_upscale_chunk(
	target_path: str, output_path: str, is_video: bool, output_fps: float, logger: logging.Logger,
) -> None:
	staged = stage_image_for_comfyui(target_path)
	workflow = build_upscale_workflow(staged_filename=staged, is_video=is_video, output_fps=output_fps)
	prompt_id = await submit_comfyui_prompt(workflow, logger=logger)
	history_entry = await wait_for_comfyui_prompt(prompt_id, logger=logger, timeout=1800.0)
	comfyui_output_path = get_comfyui_output_file(history_entry)
	shutil.copy(comfyui_output_path, output_path)


async def process_long_upscale(
	target_video_path: str, final_output_path: str, chunk_seconds: int, output_fps: float, logger: logging.Logger,
) -> int:
	"""Processa o upscale 4x de um video pedaco por pedaco (evita carregar o video inteiro
	de uma vez na jaula de memoria - ver achado acima), remonta os pedacos e costura de volta
	com o audio/legendas do original."""
	duration = await get_video_duration_seconds(target_video_path)
	if not chunk_seconds or duration <= chunk_seconds:
		if chunk_seconds:
			logger.info(f"Video ({duration:.1f}s) cabe num unico pedaco (limite {chunk_seconds}s) - processando sem dividir.")
		upscaled_path = f"{final_output_path}.sem_audio.mp4"
		await _run_single_upscale_chunk(target_video_path, upscaled_path, is_video=True, output_fps=output_fps, logger=logger)
		master_cmd = build_ffmpeg_mastering_command(target_video_path, upscaled_path, final_output_path, fps=output_fps)
		proc = await asyncio.create_subprocess_exec(*master_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
		_, stderr = await proc.communicate()
		os.remove(upscaled_path)
		if proc.returncode != 0:
			logger.error(f"Masterizacao final do upscale falhou: {stderr.decode(errors='ignore')}")
			return proc.returncode
		logger.info(f"Upscale concluido (audio remontado): {final_output_path}")
		return 0

	chunk_dir = os.path.join(PIPELINE_PATH, "tmp", f"upscale_chunks_{uuid.uuid4().hex[:8]}")
	logger.info(f"Video de {duration:.1f}s excede o limite de {chunk_seconds}s por pedaco - dividindo antes do upscale.")
	raw_chunks = await split_video_into_chunks(target_video_path, chunk_seconds, os.path.join(chunk_dir, "raw"), logger)

	processed_chunks = []
	for i, raw_chunk in enumerate(raw_chunks):
		free_gb = get_disk_free_gb("/")
		if free_gb < DISK_SAFETY_MARGIN_GB:
			raise GateDenied(f"Gate 3: espaco insuficiente no meio do upscale em pedacos ({free_gb:.1f}GB livres)")
		processed_path = os.path.join(chunk_dir, "processed", f"chunk_{i:04d}.mp4")
		os.makedirs(os.path.dirname(processed_path), exist_ok=True)
		logger.info(f"Upscale do pedaco {i + 1}/{len(raw_chunks)}: {raw_chunk}")
		await _run_single_upscale_chunk(raw_chunk, processed_path, is_video=True, output_fps=output_fps, logger=logger)
		processed_chunks.append(processed_path)

	concatenated_path = os.path.join(chunk_dir, "concatenado.mp4")
	await concat_video_chunks(processed_chunks, concatenated_path, logger)

	master_cmd = build_ffmpeg_mastering_command(target_video_path, concatenated_path, final_output_path, fps=output_fps)
	proc = await asyncio.create_subprocess_exec(*master_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
	_, stderr = await proc.communicate()
	if proc.returncode != 0:
		logger.error(f"Masterizacao final dos pedacos de upscale falhou: {stderr.decode(errors='ignore')}")
		return proc.returncode

	shutil.rmtree(chunk_dir, ignore_errors=True)
	logger.info(f"Upscale em {len(raw_chunks)} pedacos concluido (audio remontado): {final_output_path}")
	return 0
