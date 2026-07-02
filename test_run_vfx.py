import asyncio
import logging
import socket

import pytest

from run_vfx import (
	CONDA_FALLBACK_PATHS,
	PIPELINE_PATH,
	WAN22_HIGH_NOISE_GGUF,
	WAN22_LOW_NOISE_GGUF,
	WAN22_VAE,
	GateDenied,
	build_facefusion_command,
	build_parser,
	build_subprocess_env,
	build_ffmpeg_mastering_command,
	build_wan22_video_workflow,
	check_binary,
	check_port_free,
	confirm,
	gate_1_memory_jail,
	gate_2_vram_check,
	gate_3_disk_check,
	orchestrate,
	run_in_memory_jail,
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

	monkeypatch.setattr("run_vfx.confirm", fake_confirm)
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

	monkeypatch.setattr("run_vfx.confirm", fake_confirm)
	with pytest.raises(GateDenied):
		asyncio.run(gate_1_memory_jail(TEST_LOGGER, mode="faceswap", auto_approve=False, dry_run=False))


# --- Fase 3: Gate 2 (VRAM/RAM/Swap) forçado ---

def test_gate2_forced_low_vram_triggers_alert_and_can_be_denied(monkeypatch):
	async def fake_vram():
		return 2000  # ~2GB, abaixo do alerta de 15GB

	async def fake_confirm(prompt):
		return False

	monkeypatch.setattr("run_vfx.get_vram_free_mb", fake_vram)
	monkeypatch.setattr("run_vfx.confirm", fake_confirm)
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

	monkeypatch.setattr("run_vfx.get_vram_free_mb", fake_vram)
	monkeypatch.setattr("run_vfx.confirm", fake_confirm)
	result = asyncio.run(gate_2_vram_check(TEST_LOGGER, mode="faceswap", auto_approve=False, dry_run=False))
	assert result["vram_free_mb"] is None


def test_gate2_auto_approve_skips_prompt(monkeypatch):
	called = {"confirm": False}

	async def fake_vram():
		return 16000

	async def fake_confirm(prompt):
		called["confirm"] = True
		return True

	monkeypatch.setattr("run_vfx.get_vram_free_mb", fake_vram)
	monkeypatch.setattr("run_vfx.confirm", fake_confirm)
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

	monkeypatch.setattr("run_vfx.get_vram_free_mb", fake_vram)
	monkeypatch.setattr("run_vfx.get_ram_free_mb", lambda: 2000)
	monkeypatch.setattr("run_vfx.get_swap_used_mb", lambda: 100)
	monkeypatch.setattr("run_vfx.confirm", fake_confirm)
	monkeypatch.setattr("run_vfx.unload_ollama_model", fake_unload)

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

	monkeypatch.setattr("run_vfx.get_vram_free_mb", fake_vram)
	monkeypatch.setattr("run_vfx.get_ram_free_mb", lambda: 2000)
	monkeypatch.setattr("run_vfx.get_swap_used_mb", lambda: 100)
	monkeypatch.setattr("run_vfx.confirm", fail_if_called)
	monkeypatch.setattr("run_vfx.unload_ollama_model", fake_unload)

	asyncio.run(gate_2_vram_check(TEST_LOGGER, mode="video", auto_approve=True, dry_run=False))
	assert calls["unload"] is True


# --- Fase 3: Gate 3 (disco) forçado, nunca pulável ---

def test_gate3_forced_low_disk_always_aborts_even_with_auto_approve(monkeypatch):
	monkeypatch.setattr("run_vfx.get_disk_free_gb", lambda path="/": 10.0)
	with pytest.raises(GateDenied):
		asyncio.run(gate_3_disk_check(TEST_LOGGER, auto_approve=True, dry_run=False))


def test_gate3_ignores_auto_approve_and_still_prompts(monkeypatch):
	called = {"confirm": False}

	async def fake_confirm(prompt):
		called["confirm"] = True
		return True

	monkeypatch.setattr("run_vfx.get_disk_free_gb", lambda path="/": 100.0)
	monkeypatch.setattr("run_vfx.confirm", fake_confirm)
	asyncio.run(gate_3_disk_check(TEST_LOGGER, auto_approve=True, dry_run=False))
	assert called["confirm"] is True


def test_gate3_denied_by_user_even_with_enough_space(monkeypatch):
	async def fake_confirm(prompt):
		return False

	monkeypatch.setattr("run_vfx.get_disk_free_gb", lambda path="/": 100.0)
	monkeypatch.setattr("run_vfx.confirm", fake_confirm)
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


# --- Fase 3B: estrutura do workflow Wan2.2 (validação estática, sem GPU real) ---

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


def test_wan22_workflow_applies_upscale_after_decode_before_save():
	wf = build_wan22_video_workflow("um teste")
	assert wf["upscale"]["inputs"]["image"] == ["decode", 0]
	assert wf["save"]["inputs"]["images"] == ["upscale", 0]


def test_wan22_workflow_uses_low_resolution_short_clip_by_default():
	wf = build_wan22_video_workflow("um teste")
	assert wf["empty_embeds"]["inputs"]["width"] <= 480
	assert wf["empty_embeds"]["inputs"]["height"] <= 480
	assert wf["empty_embeds"]["inputs"]["num_frames"] <= 33  # clipe curto (poucos segundos)


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


async def _fake_confirm_yes(prompt):
	return True


def test_master_mode_requires_original_and_processed_video(monkeypatch):
	monkeypatch.setattr("run_vfx.confirm", _fake_confirm_yes)
	args = build_parser().parse_args(["--mode", "master", "--auto-approve", "--output", "/tmp/saida.mkv"])
	logger = logging.getLogger("test-master-missing-args")
	logger.addHandler(logging.NullHandler())
	rc = asyncio.run(orchestrate(args, logger))
	assert rc == 1


def test_master_mode_rejects_missing_input_files(monkeypatch, tmp_path):
	monkeypatch.setattr("run_vfx.confirm", _fake_confirm_yes)
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

	monkeypatch.setattr("run_vfx.confirm", fail_if_called)
	args = build_parser().parse_args(["--dry-run", "--mode", "faceswap"])
	logger = logging.getLogger("test-dry-run")
	logger.addHandler(logging.NullHandler())
	rc = asyncio.run(orchestrate(args, logger))
	assert rc == 0
