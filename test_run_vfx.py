import asyncio
import logging
import os
import socket
import subprocess
import tempfile

import pytest

from run_vfx import (
	CONDA_FALLBACK_PATHS,
	CONTROLNET_DEPTH_SDXL,
	COMFYUI_DIR,
	COMFYUI_INPUT_DIR,
	MAX_VIDEO_FRAMES,
	PIPELINE_PATH,
	WAN22_HIGH_NOISE_GGUF,
	WAN22_I2V_HIGH_NOISE_GGUF,
	WAN22_I2V_LOW_NOISE_GGUF,
	WAN22_LOW_NOISE_GGUF,
	WAN22_VAE,
	GateDenied,
	INPAINT_CHECKPOINT,
	build_background_remover_command,
	build_demucs_command,
	build_facefusion_command,
	build_facefusion_env,
	build_inpaint_workflow,
	build_lip_syncer_command,
	build_parser,
	build_subprocess_env,
	build_ffmpeg_mastering_command,
	build_wan22_video_workflow,
	check_binary,
	check_port_free,
	concat_video_chunks,
	confirm,
	free_comfyui_vram,
	build_musicgen_workflow,
	build_upscale_workflow,
	gate_1_memory_jail,
	gate_2_vram_check,
	gate_3_disk_check,
	get_video_duration_seconds,
	is_video_file,
	orchestrate,
	run_in_memory_jail,
	split_video_into_chunks,
	stage_image_for_comfyui,
	truncate_log_if_large,
	validate_pipeline_path,
)

TEST_LOGGER = logging.getLogger("test-run-vfx")
TEST_LOGGER.addHandler(logging.NullHandler())


# --- Fase 2: validação essencial ---

def test_pipeline_path_exists_and_writable():
	assert validate_pipeline_path(PIPELINE_PATH) is True


def test_pipeline_path_rejects_missing_dir():
	assert validate_pipeline_path("/home/ap/ai_pipeline_isso_nao_existe") is False


def test_ffmpeg_binary_present():
	assert check_binary("ffmpeg") is True


def test_conda_binary_present():
	assert check_binary("conda", fallback_paths=CONDA_FALLBACK_PATHS) is True


def test_unknown_binary_absent():
	assert check_binary("binario_que_nao_existe_no_sistema") is False


def test_truncate_log_if_large_leaves_small_log_untouched(tmp_path):
	log_path = tmp_path / "pequeno.log"
	log_path.write_text("algumas linhas de log\n")
	truncate_log_if_large(str(log_path), threshold_bytes=1024)
	assert log_path.read_text() == "algumas linhas de log\n"


def test_truncate_log_if_large_zeroes_out_log_above_threshold(tmp_path):
	log_path = tmp_path / "grande.log"
	log_path.write_text("x" * 2000)
	truncate_log_if_large(str(log_path), threshold_bytes=1024)
	assert log_path.stat().st_size == 0


def test_truncate_log_if_large_tolerates_missing_file(tmp_path):
	missing = tmp_path / "nao_existe.log"
	truncate_log_if_large(str(missing), threshold_bytes=1024)  # nao deve levantar excecao


def test_port_free_detects_occupied_port():
	with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
		sock.bind(("127.0.0.1", 0))
		sock.listen(1)
		occupied_port = sock.getsockname()[1]
		assert check_port_free(occupied_port) is False


def test_port_free_detects_free_port():
	with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
		sock.bind(("127.0.0.1", 0))
		free_port = sock.getsockname()[1]
	assert check_port_free(free_port) is True


def test_argument_parsing_defaults():
	args = build_parser().parse_args([])
	assert args.mode == "faceswap"
	assert args.dry_run is False
	assert args.auto_approve is False


def test_argument_parsing_video_mode_dry_run():
	args = build_parser().parse_args(["--mode", "video", "--dry-run", "--auto-approve"])
	assert args.mode == "video"
	assert args.dry_run is True
	assert args.auto_approve is True


# --- Fase 3: Gate 1 (jaula de memória) ---

def test_gate1_acceptance_systemd_kills_only_subprocess():
	"""Estoura memória de propósito via systemd-run --scope e confirma que só o
	subprocesso morre: o processo do pytest (equivalente à sessão/terminal) segue vivo,
	provado pelo fato de este teste (e os seguintes) continuarem executando normalmente.

	MemorySwapMax="0" é obrigatório aqui: testado ao vivo que MemoryMax sozinho NÃO mata
	o processo quando há swap disponível no sistema (o kernel prefere reclamar/paginar pro
	/swapfile em vez de OOM-kill). Sem isso o subprocesso "vaza" pro swap compartilhado do
	servidor e o teste de estouro forçado não teria efeito nenhum (falso positivo de segurança).
	"""
	cmd = ["python3", "-c", "bytearray(300 * 1024 * 1024)"]
	returncode, _stdout, _stderr = asyncio.run(
		run_in_memory_jail(cmd, memory_max="50M", memory_swap_max="0", logger=TEST_LOGGER)
	)
	assert returncode != 0


def test_gate1_acceptance_fallback_resource_kills_only_subprocess():
	"""Mesmo teste de aceitação, mas forçando o Plano B (resource.setrlimit) em vez do
	systemd-run, para cobrir o caso de sessão SSH sem DBus. RLIMIT_AS não tem o problema de
	swap acima (é um limite de espaço de endereçamento do processo, não de cgroup)."""
	cmd = ["python3", "-c", "bytearray(300 * 1024 * 1024)"]
	returncode, _stdout, _stderr = asyncio.run(
		run_in_memory_jail(cmd, memory_max="50M", logger=TEST_LOGGER, force_fallback=True)
	)
	assert returncode != 0


def test_gate1_auto_approve_skips_prompt(monkeypatch):
	called = {"confirm": False}

	async def fake_confirm(prompt):
		called["confirm"] = True
		return True

	monkeypatch.setattr("vfx_gates.confirm", fake_confirm)
	result = asyncio.run(gate_1_memory_jail(TEST_LOGGER, mode="faceswap", auto_approve=True, dry_run=False))
	assert called["confirm"] is False
	assert result["memory_max"] == "24G"
	assert result["memory_swap_max"] == "0"


def test_gate1_video_mode_uses_28g_plus_swap():
	result = asyncio.run(gate_1_memory_jail(TEST_LOGGER, mode="video", auto_approve=True, dry_run=False))
	assert result["memory_max"] == "28G"
	assert result["memory_swap_max"] == "4G"


def test_confirm_gives_clear_error_when_stdin_unavailable(monkeypatch):
	"""Achado real (render ao vivo via 'conda run', que nao repassa stdin): antes disso
	o EOFError cru subia sem contexto. Agora vira um RuntimeError explicando a causa."""
	def fake_input(prompt):
		raise EOFError()

	monkeypatch.setattr("builtins.input", fake_input)
	with pytest.raises(RuntimeError, match="conda activate"):
		asyncio.run(confirm("Prosseguir?"))


def test_gate1_denied_by_user_raises(monkeypatch):
	async def fake_confirm(prompt):
		return False

	monkeypatch.setattr("vfx_gates.confirm", fake_confirm)
	with pytest.raises(GateDenied):
		asyncio.run(gate_1_memory_jail(TEST_LOGGER, mode="faceswap", auto_approve=False, dry_run=False))


# --- Fase 3: Gate 2 (VRAM/RAM/Swap) forçado ---

def test_gate2_forced_low_vram_triggers_alert_and_can_be_denied(monkeypatch):
	async def fake_vram():
		return 2000  # ~2GB, abaixo do alerta de 15GB

	async def fake_confirm(prompt):
		return False

	monkeypatch.setattr("vfx_gates.get_vram_free_mb", fake_vram)
	monkeypatch.setattr("vfx_gates.confirm", fake_confirm)
	with pytest.raises(GateDenied):
		asyncio.run(gate_2_vram_check(TEST_LOGGER, mode="faceswap", auto_approve=False, dry_run=False))


def test_gate2_unknown_vram_does_not_crash_and_reports_none(monkeypatch):
	"""Achado da revisao: quando nvidia-smi falha, get_vram_free_mb() retorna None.
	Antes da correcao, `(vram_free_mb or 0) / 1024` mascarava isso como 0GB (tratado
	como 'nao alerta' por ser < VRAM_PEAK_ALERT_GB mas nao explicitamente marcado como
	desconhecido). Agora o caminho None e tratado explicitamente e nao derruba com TypeError."""
	async def fake_vram():
		return None

	async def fake_confirm(prompt):
		return True

	monkeypatch.setattr("vfx_gates.get_vram_free_mb", fake_vram)
	monkeypatch.setattr("vfx_gates.confirm", fake_confirm)
	result = asyncio.run(gate_2_vram_check(TEST_LOGGER, mode="faceswap", auto_approve=False, dry_run=False))
	assert result["vram_free_mb"] is None


def test_gate2_auto_approve_skips_prompt(monkeypatch):
	called = {"confirm": False}

	async def fake_vram():
		return 16000

	async def fake_confirm(prompt):
		called["confirm"] = True
		return True

	monkeypatch.setattr("vfx_gates.get_vram_free_mb", fake_vram)
	monkeypatch.setattr("vfx_gates.confirm", fake_confirm)
	result = asyncio.run(gate_2_vram_check(TEST_LOGGER, mode="faceswap", auto_approve=True, dry_run=False))
	assert called["confirm"] is False
	assert result["vram_free_mb"] == 16000


def test_gate2_video_mode_offers_to_unload_ollama_when_tight(monkeypatch):
	calls = {"unload": False, "confirm_prompts": []}

	async def fake_vram():
		return 3000

	async def fake_confirm(prompt):
		calls["confirm_prompts"].append(prompt)
		return True

	async def fake_unload(logger, model="qwen"):
		calls["unload"] = True

	monkeypatch.setattr("vfx_gates.get_vram_free_mb", fake_vram)
	monkeypatch.setattr("vfx_gates.get_ram_free_mb", lambda: 2000)
	monkeypatch.setattr("vfx_gates.get_swap_used_mb", lambda: 100)
	monkeypatch.setattr("vfx_gates.confirm", fake_confirm)
	monkeypatch.setattr("vfx_gates.unload_ollama_model", fake_unload)

	asyncio.run(gate_2_vram_check(TEST_LOGGER, mode="video", auto_approve=False, dry_run=False))
	assert calls["unload"] is True
	assert len(calls["confirm_prompts"]) >= 1


def test_gate2_auto_approve_unloads_ollama_without_asking_when_tight(monkeypatch):
	"""Achado ao vivo (render real): --auto-approve nao pulava o sub-prompt de 'descarregar
	Ollama?' dentro do Gate 2, causando EOFError em execucao nao-interativa (o confirm() real
	tentava ler stdin que nao existia). O mock antigo desse teste sempre retornava True e
	escondia o bug. Agora confirm() nao pode ser chamado nesse caminho quando auto_approve=True."""
	calls = {"unload": False}

	async def fake_vram():
		return 3000

	async def fail_if_called(prompt):
		raise AssertionError("confirm() nao deveria ser chamado com --auto-approve, mesmo com recursos apertados")

	async def fake_unload(logger, model="qwen"):
		calls["unload"] = True

	monkeypatch.setattr("vfx_gates.get_vram_free_mb", fake_vram)
	monkeypatch.setattr("vfx_gates.get_ram_free_mb", lambda: 2000)
	monkeypatch.setattr("vfx_gates.get_swap_used_mb", lambda: 100)
	monkeypatch.setattr("vfx_gates.confirm", fail_if_called)
	monkeypatch.setattr("vfx_gates.unload_ollama_model", fake_unload)

	asyncio.run(gate_2_vram_check(TEST_LOGGER, mode="video", auto_approve=True, dry_run=False))
	assert calls["unload"] is True


# --- Fase 3: Gate 3 (disco) forçado, nunca pulável ---

def test_gate3_forced_low_disk_always_aborts_even_with_auto_approve(monkeypatch):
	monkeypatch.setattr("vfx_gates.get_disk_free_gb", lambda path="/": 10.0)
	with pytest.raises(GateDenied):
		asyncio.run(gate_3_disk_check(TEST_LOGGER, auto_approve=True, dry_run=False))


def test_gate3_ignores_auto_approve_and_still_prompts(monkeypatch):
	called = {"confirm": False}

	async def fake_confirm(prompt):
		called["confirm"] = True
		return True

	monkeypatch.setattr("vfx_gates.get_disk_free_gb", lambda path="/": 100.0)
	monkeypatch.setattr("vfx_gates.confirm", fake_confirm)
	asyncio.run(gate_3_disk_check(TEST_LOGGER, auto_approve=True, dry_run=False))
	assert called["confirm"] is True


def test_gate3_denied_by_user_even_with_enough_space(monkeypatch):
	async def fake_confirm(prompt):
		return False

	monkeypatch.setattr("vfx_gates.get_disk_free_gb", lambda path="/": 100.0)
	monkeypatch.setattr("vfx_gates.confirm", fake_confirm)
	with pytest.raises(GateDenied):
		asyncio.run(gate_3_disk_check(TEST_LOGGER, auto_approve=False, dry_run=False))


# --- Wayland guard / FaceFusion command builder ---

def test_wayland_guard_sets_offscreen_platform():
	env = build_subprocess_env()
	assert env["QT_QPA_PLATFORM"] == "offscreen"


def test_facefusion_command_uses_reference_face_selector():
	cmd = build_facefusion_command("/tmp/source.jpg", "/tmp/target.mp4", "/tmp/output.mp4")
	assert "--face-selector-mode" in cmd
	idx = cmd.index("--face-selector-mode")
	assert cmd[idx + 1] == "reference"


def test_facefusion_command_uses_its_own_conda_env_python_not_bare_python():
	"""Achado real (primeiro face-swap end-to-end): 'python' generico resolvia pro ambiente
	Conda do run_vfx.py (vfx-pipeline, sem onnxruntime), nao pro facefusion-pipeline (onde o
	FaceFusion de fato tem suas dependencias). ModuleNotFoundError: onnxruntime."""
	cmd = build_facefusion_command("/tmp/source.jpg", "/tmp/target.mp4", "/tmp/output.mp4")
	assert cmd[0] != "python"
	assert "facefusion-pipeline" in cmd[0]
	assert cmd[0].endswith("/bin/python")


def test_musicgen_workflow_chains_generation_and_save():
	wf = build_musicgen_workflow("calm guitar melody", duration=5.0)
	assert wf["musicgen"]["inputs"]["prompt"] == "calm guitar melody"
	assert wf["musicgen"]["inputs"]["duration"] == 5.0
	assert wf["save"]["inputs"]["audio"] == ["musicgen", 0]


# --- Upscale standalone (pedido do usuario, auditoria de uso profissional) ---

def test_is_video_file_detects_common_video_extensions():
	assert is_video_file("cena.mp4") is True
	assert is_video_file("cena.MOV") is True
	assert is_video_file("foto.jpg") is False
	assert is_video_file("foto.png") is False


def test_upscale_workflow_image_uses_load_image_and_save_image():
	wf = build_upscale_workflow("foto.jpg", is_video=False)
	assert wf["load_image"]["inputs"]["image"] == "foto.jpg"
	assert wf["upscale"]["inputs"]["image"] == ["load_image", 0]
	assert wf["save"]["class_type"] == "SaveImage"
	assert wf["save"]["inputs"]["images"] == ["upscale", 0]
	assert "load_video" not in wf


def test_upscale_workflow_video_uses_vhs_load_video_and_vhs_video_combine():
	wf = build_upscale_workflow("cena.mp4", is_video=True, output_fps=30.0)
	assert wf["load_video"]["class_type"] == "VHS_LoadVideo"
	assert wf["load_video"]["inputs"]["video"] == "cena.mp4"
	assert wf["upscale"]["inputs"]["image"] == ["load_video", 0]
	assert wf["save"]["class_type"] == "VHS_VideoCombine"
	assert wf["save"]["inputs"]["frame_rate"] == 30.0
	assert "load_image" not in wf


def test_upscale_workflow_uses_the_same_realesrgan_model_as_video_mode():
	from run_vfx import WAN22_UPSCALE_MODEL
	wf = build_upscale_workflow("foto.jpg")
	assert wf["upscale_model"]["inputs"]["model_name"] == WAN22_UPSCALE_MODEL


def test_upscale_mode_requires_target_and_output(monkeypatch):
	monkeypatch.setattr("vfx_gates.confirm", _fake_confirm_yes)
	args = build_parser().parse_args(["--mode", "upscale", "--auto-approve"])
	rc = asyncio.run(orchestrate(args, TEST_LOGGER))
	assert rc == 1


def test_upscale_mode_rejects_missing_target_file(monkeypatch, tmp_path):
	monkeypatch.setattr("vfx_gates.confirm", _fake_confirm_yes)
	args = build_parser().parse_args([
		"--mode", "upscale", "--auto-approve",
		"--target", str(tmp_path / "nao_existe.jpg"),
		"--output", str(tmp_path / "saida.jpg"),
	])
	rc = asyncio.run(orchestrate(args, TEST_LOGGER))
	assert rc == 1


def test_demucs_command_uses_its_own_conda_env_and_two_stems_mode():
	cmd = build_demucs_command("/tmp/entrada.wav", "/tmp/voz.wav", output_instrumental="/tmp/resto.wav")
	assert "noise-pipeline" in cmd[0]
	assert "--output-instrumental" in cmd
	assert cmd[cmd.index("--output-instrumental") + 1] == "/tmp/resto.wav"


def test_facefusion_env_sets_ld_library_path_for_cuda(monkeypatch, tmp_path):
	"""Achado real: onnxruntime-gpu no ambiente facefusion-pipeline nao achava as libs CUDA
	instaladas via pip (nvidia-cublas-cu12 etc ficam dentro do site-packages, fora do caminho
	de busca do linker) - caia pra CPU silenciosamente (sem erro visivel no retorno, so lento:
	46s vs 1.5s medido ao vivo). LD_LIBRARY_PATH resolve isso."""
	fake_env_root = tmp_path / "envs" / "facefusion-pipeline" / "lib" / "python3.11" / "site-packages"
	nvidia_dir = fake_env_root / "nvidia"
	(nvidia_dir / "cublas" / "lib").mkdir(parents=True)
	(nvidia_dir / "cudnn" / "lib").mkdir(parents=True)
	monkeypatch.setattr("vfx_facefusion.os.path.expanduser", lambda p: p.replace("~/miniconda3", str(tmp_path)))
	env = build_facefusion_env()
	assert "cublas/lib" in env["LD_LIBRARY_PATH"]
	assert "cudnn/lib" in env["LD_LIBRARY_PATH"]


def test_background_remover_and_lip_syncer_use_correct_processor_flag():
	"""voice_extractor NAO e testado aqui de proposito: achado real (nao um bug de codigo, um
	erro meu de pesquisa anterior) - nao existe como processor standalone nessa versao do
	FaceFusion (`--processors voice_extractor` da erro "invalid choice"). So existe como
	componente interno usado automaticamente pelo lip_syncer antes de sincronizar labios."""
	bg_cmd = build_background_remover_command("/tmp/target.png", "/tmp/output.png")
	assert "--processors" in bg_cmd
	assert bg_cmd[bg_cmd.index("--processors") + 1] == "background_remover"

	lip_cmd = build_lip_syncer_command("/tmp/audio.wav", "/tmp/video.mp4", "/tmp/output.mp4")
	assert lip_cmd[lip_cmd.index("--processors") + 1] == "lip_syncer"
	assert lip_cmd[lip_cmd.index("--execution-providers") + 1] == "cpu"  # achado: cuda quebra com CUBLAS failure 3


# --- Fase 3B: estrutura do workflow Wan2.2 (validação estática, sem GPU real) ---

def test_wan22_workflow_i2v_mode_uses_i2v_gguf_files_not_t2v():
	"""I2V (imagem->video) usa pesos GGUF DIFERENTES do T2V (texto->video), mesmo sendo o
	mesmo tamanho de modelo (A14B) - misturar os dois faria o node rejeitar ou dar resultado
	sem sentido."""
	wf = build_wan22_video_workflow("um teste", source_image_path="foto.png")
	assert wf["loader_high"]["inputs"]["model"] == WAN22_I2V_HIGH_NOISE_GGUF
	assert wf["loader_low"]["inputs"]["model"] == WAN22_I2V_LOW_NOISE_GGUF
	assert wf["loader_high"]["inputs"]["model"] != WAN22_HIGH_NOISE_GGUF


def test_wan22_workflow_i2v_mode_chains_load_resize_encode():
	wf = build_wan22_video_workflow("um teste", source_image_path="foto.png", width=320, height=320)
	assert wf["load_image"]["inputs"]["image"] == "foto.png"
	assert wf["resize_image"]["inputs"]["image"] == ["load_image", 0]
	assert wf["resize_image"]["inputs"]["width"] == 320
	assert wf["image_embeds"]["inputs"]["start_image"] == ["resize_image", 0]
	assert wf["image_embeds"]["inputs"]["vae"] == ["vae_loader", 0]
	assert "empty_embeds" not in wf


def test_wan22_workflow_i2v_mode_wires_samplers_to_image_embeds():
	wf = build_wan22_video_workflow("um teste", source_image_path="foto.png")
	assert wf["sampler_high"]["inputs"]["image_embeds"] == ["image_embeds", 0]
	assert wf["sampler_low"]["inputs"]["image_embeds"] == ["image_embeds", 0]


def test_wan22_workflow_without_source_image_stays_t2v():
	wf = build_wan22_video_workflow("um teste")
	assert "empty_embeds" in wf
	assert "load_image" not in wf
	assert wf["loader_high"]["inputs"]["model"] == WAN22_HIGH_NOISE_GGUF


def test_stage_image_for_comfyui_copies_into_comfyui_input_dir(tmp_path):
	source = tmp_path / "minha_foto.png"
	source.write_bytes(b"fake-png-bytes")
	staged_name = stage_image_for_comfyui(str(source))
	staged_path = os.path.join(COMFYUI_INPUT_DIR, staged_name)
	assert os.path.isfile(staged_path)
	assert staged_name.endswith(".png")
	os.remove(staged_path)


def test_inpaint_workflow_uses_sdxl_inpainting_checkpoint():
	wf = build_inpaint_workflow("foto.png", "mascara.png")
	assert wf["checkpoint"]["inputs"]["ckpt_name"] == INPAINT_CHECKPOINT


def test_inpaint_workflow_chains_image_mask_encode_sample_decode_save():
	wf = build_inpaint_workflow("foto.png", "mascara.png")
	assert wf["load_image"]["inputs"]["image"] == "foto.png"
	assert wf["load_mask"]["inputs"]["image"] == "mascara.png"
	assert wf["mask_to_grayscale"]["inputs"]["image"] == ["load_mask", 0]
	assert wf["encode_inpaint"]["inputs"]["pixels"] == ["load_image", 0]
	assert wf["encode_inpaint"]["inputs"]["mask"] == ["feather_mask", 0]
	assert wf["sampler"]["inputs"]["latent_image"] == ["encode_inpaint", 0]
	assert wf["decode"]["inputs"]["samples"] == ["sampler", 0]
	assert wf["save"]["inputs"]["images"] == ["composite", 0]


def test_inpaint_workflow_feathers_mask_and_composites_onto_original():
	"""Achado real (teste com ControlNet mostrou uma costura visivel na borda da mascara):
	a mascara e' suavizada (FeatherMask) antes de virar latente, e o resultado gerado e'
	colado de volta na FOTO ORIGINAL (nao na imagem inteira decodificada pelo VAE) - a area
	fora da mascara fica byte-a-byte igual a original, sem a deriva de cor/textura que o
	round-trip do VAE introduziria na imagem inteira."""
	wf = build_inpaint_workflow("foto.png", "mascara.png", feather_amount=30)
	assert wf["feather_mask"]["class_type"] == "FeatherMask"
	assert wf["feather_mask"]["inputs"]["mask"] == ["mask_to_grayscale", 0]
	assert wf["feather_mask"]["inputs"]["left"] == 30
	assert wf["feather_mask"]["inputs"]["top"] == 30
	assert wf["feather_mask"]["inputs"]["right"] == 30
	assert wf["feather_mask"]["inputs"]["bottom"] == 30
	assert wf["composite"]["class_type"] == "ImageCompositeMasked"
	assert wf["composite"]["inputs"]["destination"] == ["load_image", 0]
	assert wf["composite"]["inputs"]["source"] == ["decode", 0]
	assert wf["composite"]["inputs"]["mask"] == ["feather_mask", 0]


def test_inpaint_mode_requires_source_and_mask_image(monkeypatch):
	monkeypatch.setattr("vfx_gates.confirm", _fake_confirm_yes)
	args = build_parser().parse_args(["--mode", "inpaint", "--auto-approve"])
	logger = logging.getLogger("test-inpaint-missing-args")
	logger.addHandler(logging.NullHandler())
	rc = asyncio.run(orchestrate(args, logger))
	assert rc == 1


def test_inpaint_workflow_without_controlnet_has_no_depth_nodes():
	"""Comportamento padrao (use_depth_controlnet=False) nao muda em nada - sampler continua
	ligado direto em positive/negative, sem nenhum node de ControlNet."""
	wf = build_inpaint_workflow("foto.png", "mascara.png")
	assert "controlnet_apply" not in wf
	assert "depth_preprocessor" not in wf
	assert "controlnet_loader" not in wf
	assert wf["sampler"]["inputs"]["positive"] == ["positive", 0]
	assert wf["sampler"]["inputs"]["negative"] == ["negative", 0]


def test_inpaint_workflow_with_controlnet_adds_depth_pipeline():
	wf = build_inpaint_workflow("foto.png", "mascara.png", use_depth_controlnet=True, controlnet_strength=0.75)
	assert wf["depth_preprocessor"]["class_type"] == "MiDaS-DepthMapPreprocessor"
	assert wf["depth_preprocessor"]["inputs"]["image"] == ["load_image", 0]
	assert wf["controlnet_loader"]["class_type"] == "ControlNetLoader"
	assert wf["controlnet_loader"]["inputs"]["control_net_name"] == CONTROLNET_DEPTH_SDXL
	assert wf["controlnet_apply"]["inputs"]["positive"] == ["positive", 0]
	assert wf["controlnet_apply"]["inputs"]["negative"] == ["negative", 0]
	assert wf["controlnet_apply"]["inputs"]["control_net"] == ["controlnet_loader", 0]
	assert wf["controlnet_apply"]["inputs"]["image"] == ["depth_preprocessor", 0]
	assert wf["controlnet_apply"]["inputs"]["strength"] == 0.75
	# O sampler passa a usar a saida do ControlNet, nao mais o positive/negative crus
	assert wf["sampler"]["inputs"]["positive"] == ["controlnet_apply", 0]
	assert wf["sampler"]["inputs"]["negative"] == ["controlnet_apply", 1]


def test_inpaint_mode_passes_controlnet_flags_through_to_workflow(monkeypatch):
	"""--use-depth-controlnet e --controlnet-strength no CLI chegam ate build_inpaint_workflow."""
	monkeypatch.setattr("vfx_gates.confirm", _fake_confirm_yes)

	async def fake_poll_comfyui_system_stats(*args, **kwargs):
		return None
	monkeypatch.setattr("run_vfx.poll_comfyui_system_stats", fake_poll_comfyui_system_stats)

	captured_kwargs = {}
	real_build_inpaint_workflow = build_inpaint_workflow

	def fake_build_inpaint_workflow(*args, **kwargs):
		captured_kwargs.update(kwargs)
		return real_build_inpaint_workflow(*args, **kwargs)
	monkeypatch.setattr("run_vfx.build_inpaint_workflow", fake_build_inpaint_workflow)

	async def fake_submit_comfyui_prompt(workflow, logger=None):
		return "fake-prompt-id"
	monkeypatch.setattr("run_vfx.submit_comfyui_prompt", fake_submit_comfyui_prompt)

	async def fake_wait_for_comfyui_prompt(prompt_id, logger=None, timeout=600.0):
		return {"outputs": {"save": {"images": [{"filename": "x.png", "subfolder": ""}]}}}
	monkeypatch.setattr("run_vfx.wait_for_comfyui_prompt", fake_wait_for_comfyui_prompt)

	monkeypatch.setattr("run_vfx.get_comfyui_output_file", lambda history_entry: __file__)
	monkeypatch.setattr("shutil.copy", lambda src, dst: None)

	with tempfile.NamedTemporaryFile(suffix=".png") as source_image, tempfile.NamedTemporaryFile(suffix=".png") as mask_image:
		args = build_parser().parse_args([
			"--mode", "inpaint", "--auto-approve",
			"--source-image", source_image.name,
			"--mask-image", mask_image.name,
			"--output", "/tmp/nao_deveria_ser_usado.png",
			"--use-depth-controlnet",
			"--controlnet-strength", "0.9",
		])
		logger = logging.getLogger("test-inpaint-controlnet-flags")
		logger.addHandler(logging.NullHandler())
		rc = asyncio.run(orchestrate(args, logger))

	assert rc == 0
	assert captured_kwargs["use_depth_controlnet"] is True
	assert captured_kwargs["controlnet_strength"] == 0.9


def test_video_mode_copies_comfyui_output_when_output_flag_given(monkeypatch, tmp_path):
	"""Achado real (pre-requisito da interface web): o modo video ignorava --output
	completamente, so' logava que o resultado ficou dentro de ComfyUI/output/. Os outros
	modos que geram arquivo (inpaint/removebg/master/tts/denoise/music) ja aceitam --output
	usando get_comfyui_output_file() - so' faltava o modo video tambem usar essa mesma
	funcao (ela ja e' generica o bastante pro node VHS_VideoCombine, id "save", sem
	precisar mudar nada nela)."""
	monkeypatch.setattr("vfx_gates.confirm", _fake_confirm_yes)

	async def fake_ensure_comfyui_running_under_jail(*args, **kwargs):
		return None
	monkeypatch.setattr("run_vfx.ensure_comfyui_running_under_jail", fake_ensure_comfyui_running_under_jail)

	async def fake_submit_comfyui_prompt(workflow, logger=None):
		return "fake-prompt-id"
	monkeypatch.setattr("run_vfx.submit_comfyui_prompt", fake_submit_comfyui_prompt)

	subfolder = "video_test_subfolder"
	output_dir = os.path.join(COMFYUI_DIR, "output", subfolder)
	os.makedirs(output_dir, exist_ok=True)
	rendered_filename = "wan22_teste_fase3b_00001.mp4"
	rendered_path = os.path.join(output_dir, rendered_filename)
	with open(rendered_path, "wb") as f:
		f.write(b"fake-mp4-bytes")

	async def fake_wait_for_comfyui_prompt(prompt_id, logger=None, timeout=3600.0):
		return {"outputs": {"save": {"gifs": [{"filename": rendered_filename, "subfolder": subfolder}]}}}
	monkeypatch.setattr("run_vfx.wait_for_comfyui_prompt", fake_wait_for_comfyui_prompt)

	output_path = tmp_path / "meu_video_final.mp4"
	args = build_parser().parse_args([
		"--mode", "video", "--auto-approve",
		"--prompt", "um teste",
		"--output", str(output_path),
	])
	try:
		rc = asyncio.run(orchestrate(args, TEST_LOGGER))
	finally:
		os.remove(rendered_path)
		os.rmdir(output_dir)

	assert rc == 0
	assert output_path.is_file()
	assert output_path.read_bytes() == b"fake-mp4-bytes"


def test_video_mode_without_output_flag_still_succeeds(monkeypatch):
	"""--output continua opcional no modo video - sem ele, comportamento antigo (so' loga
	onde o ComfyUI salvou) se mantem, sem quebrar quem ja usava o modo video sem --output."""
	monkeypatch.setattr("vfx_gates.confirm", _fake_confirm_yes)

	async def fake_ensure_comfyui_running_under_jail(*args, **kwargs):
		return None
	monkeypatch.setattr("run_vfx.ensure_comfyui_running_under_jail", fake_ensure_comfyui_running_under_jail)

	async def fake_submit_comfyui_prompt(workflow, logger=None):
		return "fake-prompt-id"
	monkeypatch.setattr("run_vfx.submit_comfyui_prompt", fake_submit_comfyui_prompt)

	async def fake_wait_for_comfyui_prompt(prompt_id, logger=None, timeout=3600.0):
		return {"outputs": {"save": {"gifs": [{"filename": "nao_deveria_ser_lido.mp4", "subfolder": ""}]}}}
	monkeypatch.setattr("run_vfx.wait_for_comfyui_prompt", fake_wait_for_comfyui_prompt)

	args = build_parser().parse_args(["--mode", "video", "--auto-approve", "--prompt", "um teste"])
	rc = asyncio.run(orchestrate(args, TEST_LOGGER))
	assert rc == 0


def test_blocks_to_swap_flag_overrides_the_default_when_given(monkeypatch):
	"""Achado real (teste ao vivo de velocidade): reduzir blocks_to_swap acelera o render
	(~33% mais rapido em escala pequena) mas travou o ComfyUI com OOM real nos 161 frames
	padrao em 480x480 - por isso o valor mais baixo NAO virou o novo padrao, so' uma opcao
	avancada (--blocks-to-swap) pra quem quiser arriscar em renders curtos."""
	monkeypatch.setattr("vfx_gates.confirm", _fake_confirm_yes)

	async def fake_ensure_comfyui_running_under_jail(*args, **kwargs):
		return None
	monkeypatch.setattr("run_vfx.ensure_comfyui_running_under_jail", fake_ensure_comfyui_running_under_jail)

	captured_workflow = {}

	async def fake_submit_comfyui_prompt(workflow, logger=None):
		captured_workflow.update(workflow)
		return "fake-prompt-id"
	monkeypatch.setattr("run_vfx.submit_comfyui_prompt", fake_submit_comfyui_prompt)

	async def fake_wait_for_comfyui_prompt(prompt_id, logger=None, timeout=3600.0):
		return {"outputs": {"save": {"gifs": [{"filename": "x.mp4", "subfolder": ""}]}}}
	monkeypatch.setattr("run_vfx.wait_for_comfyui_prompt", fake_wait_for_comfyui_prompt)

	args = build_parser().parse_args([
		"--mode", "video", "--auto-approve", "--prompt", "um teste", "--blocks-to-swap", "5",
	])
	rc = asyncio.run(orchestrate(args, TEST_LOGGER))
	assert rc == 0
	assert captured_workflow["blockswap_args"]["inputs"]["blocks_to_swap"] == 5


def test_blocks_to_swap_flag_defaults_to_none_and_keeps_workflow_default(monkeypatch):
	"""Sem --blocks-to-swap, o comportamento antigo se mantem - build_wan22_video_workflow()
	usa o proprio padrao (20), testado e usado em producao ate hoje."""
	monkeypatch.setattr("vfx_gates.confirm", _fake_confirm_yes)

	async def fake_ensure_comfyui_running_under_jail(*args, **kwargs):
		return None
	monkeypatch.setattr("run_vfx.ensure_comfyui_running_under_jail", fake_ensure_comfyui_running_under_jail)

	captured_workflow = {}

	async def fake_submit_comfyui_prompt(workflow, logger=None):
		captured_workflow.update(workflow)
		return "fake-prompt-id"
	monkeypatch.setattr("run_vfx.submit_comfyui_prompt", fake_submit_comfyui_prompt)

	async def fake_wait_for_comfyui_prompt(prompt_id, logger=None, timeout=3600.0):
		return {"outputs": {"save": {"gifs": [{"filename": "x.mp4", "subfolder": ""}]}}}
	monkeypatch.setattr("run_vfx.wait_for_comfyui_prompt", fake_wait_for_comfyui_prompt)

	args = build_parser().parse_args(["--mode", "video", "--auto-approve", "--prompt", "um teste"])
	rc = asyncio.run(orchestrate(args, TEST_LOGGER))
	assert rc == 0
	assert captured_workflow["blockswap_args"]["inputs"]["blocks_to_swap"] == 20


def test_free_comfyui_vram_does_not_raise_when_comfyui_unreachable():
	"""Achado real: face-swap em pedacos falhou com 'Failed to allocate memory for requested
	buffer of size 294912' (so 288KB!) porque o ComfyUI mantinha 7GB de VRAM presos num
	checkpoint SDXL de um teste de inpainting anterior, sem relacao nenhuma com o FaceFusion -
	sao processos GPU separados que nao sabem da memoria um do outro. free_comfyui_vram()
	chama o endpoint /free do ComfyUI antes de operacoes pesadas do FaceFusion; deve ser
	tolerante a falha (ex.: ComfyUI fora do ar) e nao travar o resto do pipeline por causa
	disso."""
	async def run():
		await free_comfyui_vram(host="127.0.0.1", port=1, logger=TEST_LOGGER)  # porta invalida de proposito
	asyncio.run(run())  # nao deve levantar excecao


def test_wan22_workflow_uses_both_moe_experts_with_correct_gguf_files():
	wf = build_wan22_video_workflow("um teste")
	assert wf["loader_high"]["inputs"]["model"] == WAN22_HIGH_NOISE_GGUF
	assert wf["loader_low"]["inputs"]["model"] == WAN22_LOW_NOISE_GGUF
	assert wf["vae_loader"]["inputs"]["model_name"] == WAN22_VAE
	# achado do render real: WanVideoVAELoader aparece como "optional" no object_info do
	# ComfyUI, mas a funcao Python por tras exige 'precision' sem valor default - sem isso
	# o ComfyUI derruba o job com TypeError depois de já ter rodado os dois samplers (caro).
	assert "precision" in wf["vae_loader"]["inputs"]


def test_wan22_workflow_shares_block_swap_config_between_experts():
	wf = build_wan22_video_workflow("um teste", blocks_to_swap=12)
	assert wf["blockswap_args"]["inputs"]["blocks_to_swap"] == 12
	assert wf["loader_high_bs"]["inputs"]["block_swap_args"] == ["blockswap_args", 0]
	assert wf["loader_low_bs"]["inputs"]["block_swap_args"] == ["blockswap_args", 0]


def test_wan22_workflow_chains_samplers_via_latent_and_step_boundary():
	wf = build_wan22_video_workflow("um teste", steps=10)
	assert wf["sampler_high"]["inputs"]["end_step"] == 5
	assert wf["sampler_low"]["inputs"]["start_step"] == 5
	assert wf["sampler_low"]["inputs"]["samples"] == ["sampler_high", 0]


def test_wan22_workflow_enables_tiled_vae_decode():
	wf = build_wan22_video_workflow("um teste")
	assert wf["decode"]["inputs"]["enable_vae_tiling"] is True


def test_wan22_workflow_chains_decode_interpolate_upscale_save_in_order():
	"""Pedido do usuario: fluidez proxima de cinema (~30fps) via interpolacao real de frames
	(RIFE), nao so mudando o numero de frame_rate salvo (isso mudaria velocidade, nao suavidade)."""
	wf = build_wan22_video_workflow("um teste")
	assert wf["interpolate"]["inputs"]["images"] == ["decode", 0]
	assert wf["upscale"]["inputs"]["image"] == ["interpolate", 0]
	assert wf["save"]["inputs"]["images"] == ["upscale", 0]


def test_wan22_workflow_interpolation_doubles_frames_and_saves_at_30fps():
	wf = build_wan22_video_workflow("um teste")
	assert wf["interpolate"]["inputs"]["multiplier"] == 2
	assert wf["save"]["inputs"]["frame_rate"] == 30


def test_wan22_workflow_uses_low_resolution_by_default():
	wf = build_wan22_video_workflow("um teste")
	assert wf["empty_embeds"]["inputs"]["width"] <= 480
	assert wf["empty_embeds"]["inputs"]["height"] <= 480


def test_wan22_workflow_default_duration_is_around_10_seconds_at_16fps():
	"""Pedido do usuario: minimo 5s, media 10-15s. Modelo A14B gera nativamente a 16fps
	(confirmado nos workflows de exemplo do Kijai) - essa e a taxa de GERACAO, independente
	do frame_rate de SALVAMENTO (que agora e 30fps pos-interpolacao, testado separadamente)."""
	wf = build_wan22_video_workflow("um teste")
	num_frames = wf["empty_embeds"]["inputs"]["num_frames"]
	duration_seconds = num_frames / 16
	assert 5 <= duration_seconds <= 15


def test_max_video_frames_allows_up_to_15_seconds_at_16fps():
	assert MAX_VIDEO_FRAMES / 16 >= 15


# --- Fase 4: Render Final e Masterização ---

def test_ffmpeg_mastering_uses_fps_mode_not_deprecated_vsync():
	"""Achado: -vsync esta deprecated no ffmpeg 6.x instalado neste servidor; usar -fps_mode."""
	cmd = build_ffmpeg_mastering_command("/tmp/original.mkv", "/tmp/processado.mp4", "/tmp/saida.mkv")
	assert "-fps_mode" in cmd
	idx = cmd.index("-fps_mode")
	assert cmd[idx + 1] == "cfr"
	assert "-vsync" not in cmd


def test_ffmpeg_mastering_sets_bt709_color_matrix():
	cmd = build_ffmpeg_mastering_command("/tmp/original.mkv", "/tmp/processado.mp4", "/tmp/saida.mkv")
	for flag in ("-color_primaries", "-color_trc", "-colorspace"):
		assert flag in cmd
		assert cmd[cmd.index(flag) + 1] == "bt709"


def test_ffmpeg_mastering_takes_video_from_processed_audio_subs_from_original():
	cmd = build_ffmpeg_mastering_command("/tmp/original.mkv", "/tmp/processado.mp4", "/tmp/saida.mkv")
	assert cmd[cmd.index("-map") + 1] == "1:v:0"  # video vem do processado (segundo -i)
	map_indices = [i for i, v in enumerate(cmd) if v == "-map"]
	map_values = [cmd[i + 1] for i in map_indices]
	assert "0:a?" in map_values  # audio (5.1/7.1) vem do original, opcional
	assert "0:s?" in map_values  # legendas vem do original, opcional
	assert "-map_metadata" in cmd
	assert cmd[cmd.index("-map_metadata") + 1] == "0"


def test_ffmpeg_mastering_copies_audio_and_subtitle_streams_without_reencoding():
	cmd = build_ffmpeg_mastering_command("/tmp/original.mkv", "/tmp/processado.mp4", "/tmp/saida.mkv")
	assert cmd[cmd.index("-c:a") + 1] == "copy"
	assert cmd[cmd.index("-c:s") + 1] == "copy"


# --- Fase 7: processar vídeos longos em pedaços (teste funcional real com ffmpeg) ---

def _make_test_video(path: str, duration: int, color: str = "red") -> None:
	cmd = [
		"ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=160x160:rate=10",
		"-c:v", "libx264", "-pix_fmt", "yuv420p", path,
	]
	subprocess.run(cmd, capture_output=True, check=True)


def test_split_and_concat_video_chunks_roundtrip(tmp_path):
	"""Teste funcional real (roda ffmpeg de verdade, sem mock): um video de 6s dividido em
	pedacos de 2s deve virar >=3 pedacos, e remontar-los deve resultar num video com duracao
	proxima da original (stream-copy corta no keyframe mais proximo, entao pode variar um
	pouco - nao precisa ser exato)."""
	source = tmp_path / "video_longo_teste.mp4"
	_make_test_video(str(source), duration=6)

	chunks = asyncio.run(split_video_into_chunks(str(source), chunk_seconds=2, output_dir=str(tmp_path / "pedacos"), logger=TEST_LOGGER))
	assert len(chunks) >= 3

	concatenated = tmp_path / "remontado.mp4"
	asyncio.run(concat_video_chunks(chunks, str(concatenated), logger=TEST_LOGGER))
	assert concatenated.is_file()

	duration = asyncio.run(get_video_duration_seconds(str(concatenated)))
	assert 5.0 <= duration <= 7.0


def test_get_video_duration_reads_real_duration(tmp_path):
	source = tmp_path / "video_3s.mp4"
	_make_test_video(str(source), duration=3)
	duration = asyncio.run(get_video_duration_seconds(str(source)))
	assert 2.5 <= duration <= 3.5


async def _fake_confirm_yes(prompt):
	return True


def test_master_mode_requires_original_and_processed_video(monkeypatch):
	monkeypatch.setattr("vfx_gates.confirm", _fake_confirm_yes)
	args = build_parser().parse_args(["--mode", "master", "--auto-approve", "--output", "/tmp/saida.mkv"])
	logger = logging.getLogger("test-master-missing-args")
	logger.addHandler(logging.NullHandler())
	rc = asyncio.run(orchestrate(args, logger))
	assert rc == 1


def test_master_mode_rejects_missing_input_files(monkeypatch, tmp_path):
	monkeypatch.setattr("vfx_gates.confirm", _fake_confirm_yes)
	args = build_parser().parse_args([
		"--mode", "master", "--auto-approve",
		"--original", str(tmp_path / "nao_existe_original.mkv"),
		"--processed-video", str(tmp_path / "nao_existe_processado.mp4"),
		"--output", str(tmp_path / "saida.mkv"),
	])
	logger = logging.getLogger("test-master-missing-files")
	logger.addHandler(logging.NullHandler())
	rc = asyncio.run(orchestrate(args, logger))
	assert rc == 1


# --- Dry-run completo, do início ao fim, sem erro ---

def test_dry_run_full_pipeline_no_errors_and_no_prompts(monkeypatch):
	def fail_if_called(*args, **kwargs):
		raise AssertionError("confirm() nao deveria ser chamado em modo --dry-run")

	monkeypatch.setattr("vfx_gates.confirm", fail_if_called)
	args = build_parser().parse_args(["--dry-run", "--mode", "faceswap"])
	logger = logging.getLogger("test-dry-run")
	logger.addHandler(logging.NullHandler())
	rc = asyncio.run(orchestrate(args, logger))
	assert rc == 0
