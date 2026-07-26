"""Construtores de comando pra ferramentas externas que rodam em ambientes Conda
proprios: FaceFusion (troca de rosto, remocao de fundo, dublagem), TTS (XTTS-v2) e
Demucs (isolamento de voz). Cada uma tem environment/script isolado por conflito real
de dependencia - ver PROMPT_MASTER.md Fases 1/8/9.
"""

import os
from typing import Optional

from vfx_config import (
	DEFAULT_EXECUTION_PROVIDER,
	DEMUCS_CONDA_ENV,
	DEMUCS_SCRIPT_PATH,
	FACEFUSION_CONDA_ENV,
	MINICONDA_DIR,
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
	conda_python = os.path.join(MINICONDA_DIR, "envs", FACEFUSION_CONDA_ENV, "bin", "python")
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
		"--execution-providers", DEFAULT_EXECUTION_PROVIDER,
	]
	return cmd


def build_background_remover_command(target_path: str, output_path: str) -> list[str]:
	conda_python = os.path.join(MINICONDA_DIR, "envs", FACEFUSION_CONDA_ENV, "bin", "python")
	return [
		conda_python, "facefusion.py", "headless-run",
		"--processors", "background_remover",
		"-t", target_path,
		"-o", output_path,
		"--execution-providers", DEFAULT_EXECUTION_PROVIDER,
	]


def build_lip_syncer_command(
	source_audio_path: str, target_video_path: str, output_path: str, execution_providers: str = "cpu",
) -> list[str]:
	"""CPU e o modo definitivo do lip_syncer neste servidor (decisao mantida na migracao
	pra AMD em 2026-07-26), ate o onnxruntime publicar wheel com kernels pra esta GPU.

	Situacao atual (RX 9070 XT, RDNA4/gfx1201): nao ha wheel oficial de onnxruntime-rocm com
	kernels gfx1201 prontos. Construir da fonte exige CMAKE_HIP_ARCHITECTURES e ha relatos de
	gfx1201 ausente da tabela de arquiteturas, causando fallback silencioso. Avaliado e
	descartado por ora: esforco alto, resultado incerto, e o ganho so' apareceria aqui.

	Historico (RTX 5060 Ti, Blackwell/sm_120): o mesmo processador ja rodava em CPU pelo mesmo
	tipo de motivo - o onnxruntime-gpu nao trazia kernels cuBLAS pra sm_120 e o wav2lip falhava
	com 'CUBLAS failure 3'. Registrado porque mostra o padrao: arquitetura nova demais pro
	ecossistema onnxruntime e' um problema recorrente, independente de fabricante.

	CPU validada ponta a ponta na epoca (~136s pra um clipe de 270 frames). O parametro
	`execution_providers` segue exposto pra reavaliar sem mudanca de codigo."""
	conda_python = os.path.join(MINICONDA_DIR, "envs", FACEFUSION_CONDA_ENV, "bin", "python")
	return [
		conda_python, "facefusion.py", "headless-run",
		"--processors", "lip_syncer",
		"-s", source_audio_path,
		"-t", target_video_path,
		"-o", output_path,
		"--execution-providers", execution_providers,
	]


def build_facefusion_env() -> dict:
	"""Monta o ambiente do subprocesso do FaceFusion.

	Historico (era NVIDIA): o onnxruntime-gpu nao achava as libs CUDA instaladas via pip
	porque ficavam dentro do site-packages, fora do caminho do linker dinamico - precisava
	de LD_LIBRARY_PATH explicito, senao caia silenciosamente pra CPU.

	Hoje (AMD/ROCm): o padrao e' CPU (ver DEFAULT_EXECUTION_PROVIDER), que nao precisa de
	biblioteca de GPU nenhuma. A funcao e' mantida porque o mesmo problema de linker se
	repete no ROCm - as libs vem em site-packages/_rocm_sdk_core ou equivalente - entao a
	varredura fica generica: registra qualquer diretorio 'lib' dos SDKs de GPU presentes.
	Se nenhum existir (caso do modo CPU), o ambiente volta inalterado."""
	env = build_subprocess_env()
	site_packages = os.path.join(MINICONDA_DIR, "envs", FACEFUSION_CONDA_ENV, "lib", "python3.11", "site-packages")

	lib_dirs: list[str] = []
	for sdk_dir_name in ("_rocm_sdk_core", "rocm", "nvidia"):
		sdk_dir = os.path.join(site_packages, sdk_dir_name)
		if not os.path.isdir(sdk_dir):
			continue
		direct_lib = os.path.join(sdk_dir, "lib")
		if os.path.isdir(direct_lib):
			lib_dirs.append(direct_lib)
		lib_dirs += [
			os.path.join(sdk_dir, pkg, "lib")
			for pkg in sorted(os.listdir(sdk_dir))
			if os.path.isdir(os.path.join(sdk_dir, pkg, "lib"))
		]

	if lib_dirs:
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
	conda_python = os.path.join(MINICONDA_DIR, "envs", TTS_CONDA_ENV, "bin", "python")
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
	"""Demucs (Meta AI) roda num ambiente Conda proprio (noise-pipeline).

	Na migracao pra AMD, o torch deste ambiente passa a vir das wheels ROCm da AMD
	(repo.amd.com/rocm/whl/gfx120X-all/), nao mais das wheels CUDA. Continua precisando do
	'torchcodec' extra, que o torchaudio usa por padrao pra salvar audio e nao vem junto.

	Licao herdada da era NVIDIA que segue valendo: fixar versao de torch por conta propria
	neste ambiente ja quebrou uma vez (kernels pre-compilados nao cobriam a GPU). Manter
	alinhado com o vfx-pipeline/ComfyUI em vez de divergir."""
	conda_python = os.path.join(MINICONDA_DIR, "envs", DEMUCS_CONDA_ENV, "bin", "python")
	cmd = [conda_python, DEMUCS_SCRIPT_PATH, "--input", input_path, "--output-vocals", output_vocals, "--model", model]
	if output_instrumental:
		cmd += ["--output-instrumental", output_instrumental]
	return cmd
