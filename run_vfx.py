"""AP AI Studio - orquestrador principal do pipeline VFX.

Achado de auditoria (Engenheiro de Software, 2026-07-03): este arquivo era um
monolito de ~1500 linhas fazendo gates de seguranca, comunicacao com o ComfyUI,
construcao de workflow, comandos de ferramentas externas (FaceFusion/TTS/Demucs) e
FFmpeg tudo junto. Dividido em modulos por responsabilidade:

- vfx_config.py    - constantes e a excecao GateDenied (sem dependencia interna)
- vfx_core.py      - validacao de caminho/binario/porta, logging, confirm() [Y/n]
- vfx_gates.py     - os 3 Authorization Gates (memoria, VRAM/RAM/swap, disco)
- vfx_comfyui.py   - comunicacao HTTP com o ComfyUI e gestao do processo dele
- vfx_workflows.py - construtores de workflow (Wan2.2, inpaint, MusicGen) - dict puro
- vfx_facefusion.py- comandos externos (FaceFusion, TTS, Demucs)
- vfx_ffmpeg.py    - FFmpeg (masterizacao, corte/juncao de video), EXIF

Este arquivo agora e' so' o orquestrador: reexporta tudo dos modulos acima (mesmos
nomes de sempre, pra `from run_vfx import X` continuar funcionando sem mudanca em
quem ja consome este modulo - CLI, testes, atalhos vfx-*, webui) e define
orchestrate()/build_parser()/main() - a logica de "qual --mode faz o que", que e'
especifica deste arquivo e nao se encaixa em nenhum modulo de baixo nivel.
"""

import argparse
import asyncio
import logging
import os
import shutil
import sys
from typing import Optional

# --- Reexport de vfx_config.py (constantes + GateDenied) ---
from vfx_config import (  # noqa: F401
	CONDA_FALLBACK_PATHS,
	CONTROLNET_DEPTH_SDXL,
	COMFYUI_DIR,
	COMFYUI_HOST,
	COMFYUI_INPUT_DIR,
	COMFYUI_PORT,
	COMFYUI_SCOPE_UNIT,
	DEMUCS_CONDA_ENV,
	DEMUCS_SCRIPT_PATH,
	DISK_SAFETY_MARGIN_GB,
	FACEFUSION_CONDA_ENV,
	GateDenied,
	INPAINT_CHECKPOINT,
	LOG_PATH,
	LOG_TRUNCATE_THRESHOLD_BYTES,
	MAX_VIDEO_FRAMES,
	MAX_VIDEO_HEIGHT,
	MAX_VIDEO_WIDTH,
	MEMORY_MAX_DEFAULT,
	MEMORY_MAX_VIDEO,
	MEMORY_SWAP_MAX_VIDEO,
	NVIDIA_SMI_PATH,
	PIPELINE_PATH,
	PYTORCH_CUDA_ALLOC_CONF_VALUE,
	TTS_CONDA_ENV,
	TTS_SCRIPT_PATH,
	VRAM_PEAK_ALERT_GB,
	WAN22_HIGH_NOISE_GGUF,
	WAN22_I2V_HIGH_NOISE_GGUF,
	WAN22_I2V_LOW_NOISE_GGUF,
	WAN22_INTERPOLATION_MODEL,
	WAN22_LOW_NOISE_GGUF,
	WAN22_OUTPUT_FPS,
	WAN22_TEXT_ENCODER,
	WAN22_UPSCALE_MODEL,
	WAN22_VAE,
)

# --- Reexport de vfx_core.py ---
from vfx_core import (  # noqa: F401
	build_subprocess_env,
	check_binary,
	check_port_free,
	confirm,
	log_gate_decision,
	setup_logger,
	truncate_log_if_large,
	validate_pipeline_path,
)

# --- Reexport de vfx_gates.py ---
from vfx_gates import (  # noqa: F401
	gate_1_memory_jail,
	gate_2_vram_check,
	gate_3_disk_check,
	get_disk_free_gb,
	get_ram_free_mb,
	get_swap_used_mb,
	get_vram_free_mb,
	run_in_memory_jail,
	unload_ollama_model,
)

# --- Reexport de vfx_comfyui.py ---
from vfx_comfyui import (  # noqa: F401
	ensure_comfyui_audio_output_dir,
	ensure_comfyui_running_under_jail,
	free_comfyui_vram,
	get_comfyui_output_file,
	poll_comfyui_system_stats,
	stage_image_for_comfyui,
	submit_comfyui_prompt,
	wait_for_comfyui_prompt,
)

# --- Reexport de vfx_workflows.py ---
from vfx_workflows import (  # noqa: F401
	build_inpaint_workflow,
	build_musicgen_workflow,
	build_upscale_workflow,
	build_wan22_video_workflow,
	is_video_file,
)

# --- Reexport de vfx_facefusion.py ---
from vfx_facefusion import (  # noqa: F401
	build_background_remover_command,
	build_demucs_command,
	build_facefusion_command,
	build_facefusion_env,
	build_lip_syncer_command,
	build_tts_command,
)

# --- Reexport de vfx_ffmpeg.py ---
from vfx_ffmpeg import (  # noqa: F401
	build_ffmpeg_mastering_command,
	concat_video_chunks,
	get_video_duration_seconds,
	process_long_faceswap,
	process_long_upscale,
	sanitize_exif,
	split_video_into_chunks,
)


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
		workflow_kwargs = {}
		if args.blocks_to_swap is not None:
			workflow_kwargs["blocks_to_swap"] = args.blocks_to_swap
		workflow = build_wan22_video_workflow(
			positive_prompt=args.prompt,
			width=args.width,
			height=args.height,
			num_frames=args.num_frames,
			source_image_path=staged_image_name,
			**workflow_kwargs,
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
		await ensure_comfyui_running_under_jail(
			memory_max=memory_cfg["memory_max"], memory_swap_max=memory_cfg["memory_swap_max"], logger=logger,
		)
		workflow = build_inpaint_workflow(
			image_filename=staged_image,
			mask_filename=staged_mask,
			positive_prompt=args.prompt or "",
			use_depth_controlnet=args.use_depth_controlnet,
			controlnet_strength=args.controlnet_strength,
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
		await ensure_comfyui_running_under_jail(
			memory_max=memory_cfg["memory_max"], memory_swap_max=memory_cfg["memory_swap_max"], logger=logger,
		)
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

	if args.mode == "upscale":
		# Pedido do usuario (auditoria de uso profissional): upscale de uma foto/video
		# JA' EXISTENTE (ex.: foto antiga de familia), reaproveitando o mesmo modelo
		# Real-ESRGAN ja instalado e usado internamente no modo `video` - nao gera
		# nada novo, so' aumenta a resolucao 4x.
		if not args.target or not args.output:
			logger.error("Modo upscale requer --target e --output")
			return 1
		if not os.path.isfile(args.target):
			logger.error(f"--target nao encontrado: {args.target}")
			return 1
		await ensure_comfyui_running_under_jail(
			memory_max=memory_cfg["memory_max"], memory_swap_max=memory_cfg["memory_swap_max"], logger=logger,
		)
		is_video = is_video_file(args.target)
		if not is_video:
			# Imagem unica: um so' frame, sem risco de OOM por lote nem audio a preservar.
			staged = stage_image_for_comfyui(args.target)
			workflow = build_upscale_workflow(staged_filename=staged, is_video=False, output_fps=args.fps)
			prompt_id = await submit_comfyui_prompt(workflow, logger=logger)
			history_entry = await wait_for_comfyui_prompt(prompt_id, logger=logger, timeout=1800.0)
			comfyui_output_path = get_comfyui_output_file(history_entry)
			shutil.copy(comfyui_output_path, args.output)
			logger.info(f"Upscale concluido: {args.output}")
			return 0

		# Video: processado em pedacos (achado real - ver process_long_upscale) e remontado
		# com o audio original. --chunk-seconds default de 8s se o usuario nao passar nada,
		# pra nao repetir o OOM confirmado ao vivo com o video inteiro num lote so.
		returncode = await process_long_upscale(
			args.target, args.output, chunk_seconds=args.chunk_seconds or 8, output_fps=args.fps, logger=logger,
		)
		return returncode

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
				face_selector_gender=args.face_selector_gender,
			)
		except (RuntimeError, GateDenied) as exc:
			logger.error(f"Processamento em pedacos falhou: {exc}")
			return 1
		if returncode != 0:
			return 1
		logger.info("FaceFusion (Fase 7, processado em pedacos) concluido com sucesso.")
		return 0

	env = build_facefusion_env()
	cmd = build_facefusion_command(args.source, args.target, args.output, face_selector_gender=args.face_selector_gender)
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
	parser.add_argument("--mode", choices=["faceswap", "video", "master", "inpaint", "removebg", "tts", "denoise", "music", "upscale"], default="faceswap")
	parser.add_argument("--source", type=str, default=None)
	parser.add_argument(
		"--face-selector-gender", choices=["male", "female"], default=None,
		help="Modo faceswap: desambigua qual rosto trocar em cenas com mais de uma pessoa "
		"(ex.: duas pessoas adultas no mesmo quadro) sem depender de reference-face-position/"
		"distancia entre frames - nao tem relacao com o filtro de protecao/idade do FaceFusion.",
	)
	parser.add_argument("--target", type=str, default=None, help="Foto/video de destino (faceswap/removebg/denoise) ou a aumentar de resolucao (modo upscale)")
	parser.add_argument("--output", type=str, default=None)
	parser.add_argument("--dry-run", action="store_true")
	parser.add_argument("--auto-approve", action="store_true")
	parser.add_argument("--prompt", type=str, default=None, help="Prompt de texto (modo video)")
	parser.add_argument("--source-image", type=str, default=None, help="Foto de origem para animar (modo I2V) ou editar (modo inpaint)")
	parser.add_argument("--mask-image", type=str, default=None, help="Mascara branco=apagar/preto=manter (modo inpaint)")
	parser.add_argument(
		"--use-depth-controlnet", action="store_true",
		help=(
			"Modo inpaint: guia a edicao por um mapa de profundidade (MiDaS) da propria "
			"imagem original, via ControlNet SDXL - ajuda a manter a composicao/perspectiva "
			"da cena coerente, alem da mascara manual. Desligado por padrao (custo extra de "
			"VRAM/tempo)."
		),
	)
	parser.add_argument(
		"--controlnet-strength", type=float, default=0.6,
		help="Forca do ControlNet de profundidade no modo inpaint (0=ignora, 1=segue rigidamente a profundidade original)",
	)
	parser.add_argument("--chunk-seconds", type=int, default=None, help="Processa video longo (modo faceswap ou upscale) em pedacos de N segundos (upscale usa 8s por padrao se omitido, pra evitar OOM)")
	parser.add_argument("--text", type=str, default=None, help="Texto a sintetizar (modo tts)")
	parser.add_argument("--language", type=str, default="pt", help="Idioma da fala (modo tts)")
	parser.add_argument("--speaker", type=str, default=None, help="Nome de uma voz embutida do XTTS-v2 (modo tts)")
	parser.add_argument("--speaker-wav", type=str, default=None, help="Amostra de audio pra clonar a voz (modo tts)")
	parser.add_argument("--output-instrumental", type=str, default=None, help="Caminho pro resto do audio sem a voz (modo denoise)")
	parser.add_argument("--music-duration", type=float, default=5.0, help="Duracao em segundos da musica gerada (modo music)")
	parser.add_argument("--width", type=int, default=320)
	parser.add_argument("--height", type=int, default=320)
	parser.add_argument("--num-frames", type=int, default=161)  # ~10s a 16fps
	parser.add_argument(
		"--blocks-to-swap", type=int, default=None,
		help=(
			"Avancado, modo video: reduz o padrao (20) pra acelerar o render descarregando "
			"menos blocos do modelo pra CPU - troca velocidade por mais VRAM de pico. Testado "
			"ao vivo: valores baixos (ex. 5) sao ~33%% mais rapidos e seguros ATE por volta de "
			"80 frames em 480x480 (~12GB de pico), mas travaram o ComfyUI com OOM real nos 161 "
			"frames padrao (--num-frames) na mesma resolucao. Use por sua conta e risco em "
			"renders curtos; nao mude o padrao pra renders longos sem testar antes."
		),
	)
	parser.add_argument("--original", type=str, default=None, help="Video original (audio/legendas), modo master")
	parser.add_argument("--processed-video", type=str, default=None, help="Video processado (FaceFusion/Wan2.2), modo master")
	parser.add_argument("--fps", type=float, default=24.0, help="Frame rate constante de saida (modo master; tambem usado no modo upscale se o alvo for video)")
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
