"""Construtores de workflow (formato de API do ComfyUI) - Wan2.2 (T2V/I2V), inpainting
SDXL, MusicGen e upscale standalone. Funcoes puras (dict in/out), sem I/O nem chamada
de rede.
"""

from typing import Optional

from vfx_config import (
	CONTROLNET_DEPTH_SDXL,
	INPAINT_CHECKPOINT,
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
	use_depth_controlnet: bool = False,
	controlnet_strength: float = 0.6,
	feather_amount: int = 24,
) -> dict:
	"""Monta o prompt de API pra remover/editar uma area de uma imagem via inpainting SDXL.
	`mask_filename` e uma imagem separada (branco = area a apagar/redesenhar, preto = manter) -
	abordagem padrao de mascara manual, mais simples e previsivel que segmentacao automatica
	por texto (que exigiria baixar mais um modelo tipo GroundingDINO+SAM - deixado de fora por
	enquanto, ver PROMPT_MASTER.md). positive_prompt vazio funciona bem pra "remover objeto"
	simples (o modelo preenche com o que faz sentido pro fundo); usar um prompt descritivo
	quando quiser colocar algo especifico no lugar.

	`use_depth_controlnet=True` (achado de auditoria "uso profissional") extrai um mapa de
	profundidade da propria imagem original (MiDaS, via comfyui_controlnet_aux) e usa um
	ControlNet SDXL treinado em profundidade pra guiar a composicao/perspectiva da area
	editada - util quando a mascara sozinha deixa o resultado sem nocao de profundidade da
	cena (ex.: trocar o fundo mantendo objetos em primeiro plano coerentes em escala/posicao).
	Desligado por padrao: e' um recurso avancado, com custo de VRAM/tempo extra.

	`feather_amount` (achado real: teste com ControlNet mostrou uma linha de costura visivel
	na borda da mascara, mesmo com o ControlNet ativo) suaviza a borda da mascara
	(FeatherMask) e cola o resultado gerado de volta na FOTO ORIGINAL via essa mascara
	suavizada (ImageCompositeMasked), em vez de usar a imagem inteira decodificada pelo VAE
	direto. Duas causas reais do artefato de costura corrigidas ao mesmo tempo: (1) borda de
	mascara dura vira uma transicao suave; (2) a area "mantida" (fora da mascara) passa a ser
	byte-a-byte igual a original, sem a leve deriva de cor/textura que o round-trip do VAE
	(encode+decode) introduz na imagem inteira. Sempre ativo (nao e' um recurso opcional -
	e' uma correcao de qualidade que nao tem motivo pra desligar)."""
	workflow = {
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
		"feather_mask": {
			"class_type": "FeatherMask",
			"inputs": {
				"mask": ["mask_to_grayscale", 0],
				"left": feather_amount,
				"top": feather_amount,
				"right": feather_amount,
				"bottom": feather_amount,
			},
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
				"mask": ["feather_mask", 0],
				"grow_mask_by": 6,
			},
		},
		"decode": {
			"class_type": "VAEDecode",
			"inputs": {"samples": ["sampler", 0], "vae": ["checkpoint", 2]},
		},
		"composite": {
			"class_type": "ImageCompositeMasked",
			"inputs": {
				"destination": ["load_image", 0],
				"source": ["decode", 0],
				"x": 0,
				"y": 0,
				"resize_source": False,
				"mask": ["feather_mask", 0],
			},
		},
		"save": {
			"class_type": "SaveImage",
			"inputs": {"images": ["composite", 0], "filename_prefix": filename_prefix},
		},
	}

	sampler_positive = ["positive", 0]
	sampler_negative = ["negative", 0]

	if use_depth_controlnet:
		workflow["depth_preprocessor"] = {
			"class_type": "MiDaS-DepthMapPreprocessor",
			"inputs": {"image": ["load_image", 0], "a": 6.283185307179586, "bg_threshold": 0.1, "resolution": 512},
		}
		workflow["controlnet_loader"] = {
			"class_type": "ControlNetLoader",
			"inputs": {"control_net_name": CONTROLNET_DEPTH_SDXL},
		}
		workflow["controlnet_apply"] = {
			"class_type": "ControlNetApplyAdvanced",
			"inputs": {
				"positive": ["positive", 0],
				"negative": ["negative", 0],
				"control_net": ["controlnet_loader", 0],
				"image": ["depth_preprocessor", 0],
				"strength": controlnet_strength,
				"start_percent": 0.0,
				"end_percent": 1.0,
			},
		}
		sampler_positive = ["controlnet_apply", 0]
		sampler_negative = ["controlnet_apply", 1]

	workflow["sampler"] = {
		"class_type": "KSampler",
		"inputs": {
			"model": ["checkpoint", 0],
			"seed": seed,
			"steps": steps,
			"cfg": cfg,
			"sampler_name": "dpmpp_2m",
			"scheduler": "karras",
			"positive": sampler_positive,
			"negative": sampler_negative,
			"latent_image": ["encode_inpaint", 0],
			"denoise": denoise,
		},
	}

	return workflow


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


# --- Upscale standalone (pedido do usuario, auditoria de uso profissional) ---
# Achado da auditoria: o Real-ESRGAN ja' vinha instalado e usado internamente no
# pipeline de geracao de video (Fase 3B), mas nao havia jeito de so' aumentar a
# qualidade de uma foto ou video JA' EXISTENTE (ex.: foto antiga de familia) sem
# passar pelo resto do pipeline de geracao. Reaproveita o mesmo modelo
# (WAN22_UPSCALE_MODEL) e o mesmo node (ImageUpscaleWithModel) ja' validados.

def build_upscale_workflow(
	staged_filename: str,
	is_video: bool = False,
	output_fps: float = 30.0,
	filename_prefix: str = "upscale_resultado",
) -> dict:
	"""Upscale 4x de uma imagem ou video ja' existente, sem gerar nada novo - so'
	aumenta a resolucao. Pra video, usa VHS_LoadVideo (confirmado disponivel no
	ComfyUI deste servidor via /object_info antes de usar - mesmo node pack do
	VHS_VideoCombine ja usado no modo `video`) pra carregar os frames como um lote,
	aplica o upscale em todos de uma vez (o node ja' suporta lote, e' o mesmo usado
	no pipeline de geracao) e remonta com VHS_VideoCombine. `output_fps` nao e'
	detectado automaticamente do video original (VHS_LoadVideo devolve isso num tipo
	separado que exigiria um node a mais pra' extrair o escalar) - por padrao usa 30,
	pode ser sobrescrito via --fps."""
	workflow = {
		"upscale_model": {
			"class_type": "UpscaleModelLoader",
			"inputs": {"model_name": WAN22_UPSCALE_MODEL},
		},
	}

	if is_video:
		workflow["load_video"] = {
			"class_type": "VHS_LoadVideo",
			"inputs": {
				"video": staged_filename,
				"force_rate": 0,
				"custom_width": 0,
				"custom_height": 0,
				"frame_load_cap": 0,
				"skip_first_frames": 0,
				"select_every_nth": 1,
			},
		}
		image_source = ["load_video", 0]
	else:
		workflow["load_image"] = {
			"class_type": "LoadImage",
			"inputs": {"image": staged_filename},
		}
		image_source = ["load_image", 0]

	workflow["upscale"] = {
		"class_type": "ImageUpscaleWithModel",
		"inputs": {"upscale_model": ["upscale_model", 0], "image": image_source},
	}

	if is_video:
		workflow["save"] = {
			"class_type": "VHS_VideoCombine",
			"inputs": {
				"images": ["upscale", 0],
				"frame_rate": output_fps,
				"loop_count": 0,
				"filename_prefix": filename_prefix,
				"format": "video/h264-mp4",
				"pingpong": False,
				"save_output": True,
			},
		}
	else:
		workflow["save"] = {
			"class_type": "SaveImage",
			"inputs": {"images": ["upscale", 0], "filename_prefix": filename_prefix},
		}

	return workflow


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}


def is_video_file(path: str) -> bool:
	import os
	return os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS
