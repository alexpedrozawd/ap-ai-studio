"""FFmpeg (masterizacao final, corte/juncao de video em pedacos), higiene de EXIF, e
o processamento de faceswap em video longo que combina tudo isso com o Gate 1.
"""

import asyncio
import glob
import logging
import os
import shutil
import uuid
from typing import Optional

from vfx_config import DISK_SAFETY_MARGIN_GB, GateDenied, PIPELINE_PATH
from vfx_core import check_binary
from vfx_facefusion import build_facefusion_command, build_facefusion_env
from vfx_gates import get_disk_free_gb, run_in_memory_jail


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
	assert proc.returncode is not None  # communicate() so garante retorno depois do processo terminar
	if proc.returncode != 0:
		logger.error(f"Masterizacao final dos pedacos falhou: {stderr.decode(errors='ignore')}")
		return proc.returncode

	shutil.rmtree(chunk_dir, ignore_errors=True)
	logger.info(f"Processamento em {len(raw_chunks)} pedacos concluido: {final_output_path}")
	return 0
