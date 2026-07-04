"""Construtores de comando pra ferramentas externas que rodam em ambientes Conda
proprios: FaceFusion (troca de rosto, remocao de fundo, dublagem), TTS (XTTS-v2) e
Demucs (isolamento de voz). Cada uma tem environment/script isolado por conflito real
de dependencia - ver PROMPT_MASTER.md Fases 1/8/9.
"""

import os
from typing import Optional

from vfx_config import (
	DEMUCS_CONDA_ENV,
	DEMUCS_SCRIPT_PATH,
	FACEFUSION_CONDA_ENV,
	TTS_CONDA_ENV,
	TTS_SCRIPT_PATH,
)
from vfx_core import build_subprocess_env


# --- FaceFusion (modo de rosto de referência) ---

def build_facefusion_command(
	source_path: str, target_path: str, output_path: str,
	reference_face_position: int = 0,
	face_selector_gender: Optional[str] = None,
) -> list[str]:
	"""Achado real (primeiro face-swap end-to-end): usar so 'python' aqui resolve pro
	interprete do ambiente Conda que estiver ativo no processo do run_vfx.py (vfx-pipeline,
	do ComfyUI) - onde nao existe onnxruntime instalado. FaceFusion vive num ambiente Conda
	SEPARADO (facefusion-pipeline, ver Fase 1). Preciso do caminho explicito do interprete
	desse outro ambiente, nao do 'python' generico do PATH herdado.

	Achado real #2 (cena com duas pessoas, Jurassic Park, 2026-07-04): o modo `reference`
	sozinho (posicao + distancia padrao) e' fragil em cenas com mais de um rosto - a
	referencia extraida de UM frame especifico as vezes nao bate (por angulo/pose) com o
	MESMO rosto em outros frames da cena (distancia > 0.3), fazendo o swap sumir em trechos
	inteiros, e quando a distancia e' afrouxada pra compensar, o rosto ERRADO (a outra
	pessoa da cena) pode ser capturado por engano se a deteccao ficar ruidosa. Pra cenas com
	mais de uma pessoa, passar `face_selector_gender` ("male"/"female") troca pro modo `one`
	filtrado por genero - mais robusto pra esse caso (nao depende de casar identidade entre
	frames), sem tocar em nenhum filtro de idade/protecao do FaceFusion (a fronteira de
	seguranca do projeto continua intacta: isso e' so' desambiguar homem-vs-mulher adultos
	numa cena, nao um jeito de contornar o age-analyzer). Sem genero passado, comportamento
	inalterado (modo `reference` + posicao, como sempre foi).

	Achado real #3 (mesma sessao): a lente dos oculos de sol "piscava" (aparecia/sumia a
	cada poucos frames) especificamente em angulo lateral - rastreado ate' o modelo de
	landmarks padrao (`2dfan4`) perdendo precisao nesse angulo, fazendo o recorte do rosto
	tremer 1-2px entre frames e a borda da mascara entrar/sair da area da lente. O ensemble
	`many` e' mais estavel. Combinado com mascara de oclusao (`box occlusion region`, em vez
	do `box` sozinho) pra preservar oculos/mao/cabelo na frente do rosto de forma
	consistente quadro a quadro. Testado ao vivo (contact sheet quadro a quadro) - lente
	estavel em 100% dos frames testados, sem nenhuma alternancia."""
	conda_python = os.path.expanduser(f"~/miniconda3/envs/{FACEFUSION_CONDA_ENV}/bin/python")
	cmd = [
		conda_python, "facefusion.py", "headless-run",
		"-s", source_path,
		"-t", target_path,
		"-o", output_path,
	]
	if face_selector_gender:
		cmd += ["--face-selector-mode", "one", "--face-selector-gender", face_selector_gender]
	else:
		cmd += ["--face-selector-mode", "reference", "--reference-face-position", str(reference_face_position)]
	cmd += [
		"--face-landmarker-model", "many",
		"--face-occluder-model", "many",
		"--face-mask-types", "box", "occlusion", "region",
		"--execution-providers", "cuda",
	]
	return cmd


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


# --- Fase 9: remoção de ruído / isolamento de voz ---

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
