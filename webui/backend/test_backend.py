import asyncio
import os
import shutil
import time

import httpx

from config import JOB_OUTPUT_DIR, UPLOAD_DIR
from jobs import JOBS, Job, cleanup_old_jobs
from main import app

# Assinaturas reais minimas de midia (achado de auditoria: jobs.py agora rejeita
# upload cujo conteudo nao seja reconhecido como imagem/video/audio de verdade - ver
# _reject_if_not_media - entao "fake-bytes" generico nao passa mais). Padding extra
# garante que tambem servem pros testes de limite de tamanho.
FAKE_JPEG_BYTES = bytes.fromhex("ffd8ffe000104a4649460001") + b"0" * 200
FAKE_PNG_BYTES = bytes.fromhex("89504e470d0a1a0a0000000d49484452") + b"0" * 200
FAKE_WAV_BYTES = b"RIFF" + b"\x24\x00\x00\x00" + b"WAVEfmt " + b"0" * 200
FAKE_MP4_BYTES = bytes.fromhex("00000018") + b"ftypmp42" + b"0" * 200


async def _wait_job_finished(client: httpx.AsyncClient, job_id: str, timeout: float = 15.0) -> dict:
	deadline = time.monotonic() + timeout
	while time.monotonic() < deadline:
		resp = await client.get(f"/api/jobs/{job_id}")
		data = resp.json()
		if data["status"] in ("done", "error"):
			return data
		await asyncio.sleep(0.1)
	raise TimeoutError(f"job {job_id} nao terminou dentro de {timeout}s")


def _cleanup_job(job_id: str) -> None:
	JOBS.pop(job_id, None)
	shutil.rmtree(os.path.join(UPLOAD_DIR, job_id), ignore_errors=True)
	shutil.rmtree(os.path.join(JOB_OUTPUT_DIR, job_id), ignore_errors=True)


def test_status_endpoint_returns_expected_shape():
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			resp = await client.get("/api/status")
			assert resp.status_code == 200
			data = resp.json()
			assert "comfyui_up" in data
			assert "disk_free_gb" in data
			assert "disk_total_gb" in data
	asyncio.run(run())


def test_faceswap_job_missing_required_files_is_rejected():
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			resp = await client.post("/api/jobs/faceswap", data={})
			assert resp.status_code == 422
	asyncio.run(run())


def test_video_job_missing_prompt_is_rejected():
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			resp = await client.post("/api/jobs/video", data={})
			assert resp.status_code == 422
	asyncio.run(run())


def test_job_output_404_for_unknown_job():
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			resp = await client.get("/api/jobs/nao-existe-esse-id/output")
			assert resp.status_code == 404
	asyncio.run(run())


def test_job_status_404_for_unknown_job():
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			resp = await client.get("/api/jobs/nao-existe-esse-id")
			assert resp.status_code == 404
	asyncio.run(run())


def test_faceswap_dry_run_saves_uploads_and_completes_without_touching_gpu():
	"""Ponta a ponta pela API de verdade (nao mockado), mas com --dry-run pra nao gastar
	GPU/tempo real - confirma upload salvo no lugar certo, subprocesso disparado de verdade
	(run_vfx.py real, env vfx-pipeline real) e o job terminando com status=done."""
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			files = {
				"source": ("origem.jpg", FAKE_JPEG_BYTES, "image/jpeg"),
				"target": ("alvo.jpg", FAKE_JPEG_BYTES, "image/jpeg"),
			}
			resp = await client.post("/api/jobs/faceswap", data={"dry_run": "true"}, files=files)
			assert resp.status_code == 200
			job_id = resp.json()["job_id"]

			assert os.path.isfile(os.path.join(UPLOAD_DIR, job_id, "origem.jpg"))
			assert os.path.isfile(os.path.join(UPLOAD_DIR, job_id, "alvo.jpg"))

			data = await _wait_job_finished(client, job_id)
			assert data["status"] == "done"
			assert data["returncode"] == 0
			assert any("DRY-RUN" in line for line in data["log_tail"])

			_cleanup_job(job_id)
	asyncio.run(run())


def test_video_dry_run_completes_without_touching_gpu():
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			resp = await client.post(
				"/api/jobs/video",
				data={"prompt": "um teste automatizado", "dry_run": "true"},
			)
			assert resp.status_code == 200
			job_id = resp.json()["job_id"]

			data = await _wait_job_finished(client, job_id)
			assert data["status"] == "done"
			assert data["returncode"] == 0

			_cleanup_job(job_id)
	asyncio.run(run())


# --- Fase B: inpaint, removebg, tts, dub, denoise, music, master ---


def test_inpaint_missing_files_is_rejected():
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			resp = await client.post("/api/jobs/inpaint", data={})
			assert resp.status_code == 422
	asyncio.run(run())


def test_inpaint_dry_run_completes():
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			files = {
				"source_image": ("foto.png", FAKE_PNG_BYTES, "image/png"),
				"mask_image": ("mascara.png", FAKE_PNG_BYTES, "image/png"),
			}
			resp = await client.post(
				"/api/jobs/inpaint", data={"prompt": "fundo azul", "dry_run": "true"}, files=files,
			)
			assert resp.status_code == 200
			job_id = resp.json()["job_id"]
			data = await _wait_job_finished(client, job_id)
			assert data["status"] == "done"
			assert data["returncode"] == 0
			_cleanup_job(job_id)
	asyncio.run(run())


def test_inpaint_dry_run_completes_with_depth_controlnet_enabled():
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			files = {
				"source_image": ("foto.png", FAKE_PNG_BYTES, "image/png"),
				"mask_image": ("mascara.png", FAKE_PNG_BYTES, "image/png"),
			}
			resp = await client.post(
				"/api/jobs/inpaint",
				data={
					"prompt": "fundo azul",
					"use_depth_controlnet": "true",
					"controlnet_strength": "0.8",
					"dry_run": "true",
				},
				files=files,
			)
			assert resp.status_code == 200
			job_id = resp.json()["job_id"]
			data = await _wait_job_finished(client, job_id)
			assert data["status"] == "done"
			assert data["returncode"] == 0
			_cleanup_job(job_id)
	asyncio.run(run())


def test_removebg_missing_file_is_rejected():
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			resp = await client.post("/api/jobs/removebg", data={})
			assert resp.status_code == 422
	asyncio.run(run())


def test_removebg_dry_run_completes():
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			files = {"target": ("foto.jpg", FAKE_JPEG_BYTES, "image/jpeg")}
			resp = await client.post("/api/jobs/removebg", data={"dry_run": "true"}, files=files)
			assert resp.status_code == 200
			job_id = resp.json()["job_id"]
			data = await _wait_job_finished(client, job_id)
			assert data["status"] == "done"
			_cleanup_job(job_id)
	asyncio.run(run())


def test_tts_without_speaker_or_wav_is_rejected():
	"""Pre-checagem propria (nao so' a validacao do run_vfx.py) - evita subir um
	subprocesso pra um caso de erro que ja sabemos de antemao."""
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			resp = await client.post("/api/jobs/tts", data={"text": "ola mundo"})
			assert resp.status_code == 400
	asyncio.run(run())


def test_tts_dry_run_completes_with_builtin_speaker():
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			resp = await client.post(
				"/api/jobs/tts",
				data={"text": "ola mundo", "speaker": "Ana Florence", "dry_run": "true"},
			)
			assert resp.status_code == 200
			job_id = resp.json()["job_id"]
			data = await _wait_job_finished(client, job_id)
			assert data["status"] == "done"
			_cleanup_job(job_id)
	asyncio.run(run())


def test_dub_missing_files_is_rejected():
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			resp = await client.post("/api/jobs/dub", data={})
			assert resp.status_code == 422
	asyncio.run(run())


def test_dub_dry_run_does_not_spawn_subprocess():
	"""facefusion.py nao tem --dry-run - a rota simula sem rodar nada. Confirma que o
	job fica pronto na hora (sem precisar de polling) e o log deixa claro que foi so'
	simulado."""
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			files = {
				"audio": ("fala.wav", FAKE_WAV_BYTES, "audio/wav"),
				"video": ("video.mp4", FAKE_MP4_BYTES, "video/mp4"),
			}
			resp = await client.post("/api/jobs/dub", data={"dry_run": "true"}, files=files)
			assert resp.status_code == 200
			job_id = resp.json()["job_id"]

			status_resp = await client.get(f"/api/jobs/{job_id}")
			data = status_resp.json()
			assert data["status"] == "done"
			assert any("modo teste" in line for line in data["log_tail"])
			_cleanup_job(job_id)
	asyncio.run(run())


def test_denoise_missing_file_is_rejected():
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			resp = await client.post("/api/jobs/denoise", data={})
			assert resp.status_code == 422
	asyncio.run(run())


def test_denoise_dry_run_completes_without_instrumental_by_default():
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			files = {"target": ("audio.wav", FAKE_WAV_BYTES, "audio/wav")}
			resp = await client.post("/api/jobs/denoise", data={"dry_run": "true"}, files=files)
			assert resp.status_code == 200
			job_id = resp.json()["job_id"]
			data = await _wait_job_finished(client, job_id)
			assert data["status"] == "done"
			assert data["secondary_output_ready"] is False
			_cleanup_job(job_id)
	asyncio.run(run())


def test_denoise_with_instrumental_flag_sets_secondary_output_path():
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			files = {"target": ("audio.wav", FAKE_WAV_BYTES, "audio/wav")}
			resp = await client.post(
				"/api/jobs/denoise", data={"want_instrumental": "true", "dry_run": "true"}, files=files,
			)
			assert resp.status_code == 200
			job_id = resp.json()["job_id"]
			assert JOBS[job_id].secondary_output_path is not None
			await _wait_job_finished(client, job_id)
			_cleanup_job(job_id)
	asyncio.run(run())


def test_music_missing_prompt_is_rejected():
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			resp = await client.post("/api/jobs/music", data={})
			assert resp.status_code == 422
	asyncio.run(run())


def test_music_dry_run_completes():
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			resp = await client.post("/api/jobs/music", data={"prompt": "trilha de teste", "dry_run": "true"})
			assert resp.status_code == 200
			job_id = resp.json()["job_id"]
			data = await _wait_job_finished(client, job_id)
			assert data["status"] == "done"
			_cleanup_job(job_id)
	asyncio.run(run())


def test_master_missing_files_is_rejected():
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			resp = await client.post("/api/jobs/master", data={})
			assert resp.status_code == 422
	asyncio.run(run())


def test_master_dry_run_completes():
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			files = {
				"original": ("original.mp4", FAKE_MP4_BYTES, "video/mp4"),
				"processed_video": ("processado.mp4", FAKE_MP4_BYTES, "video/mp4"),
			}
			resp = await client.post("/api/jobs/master", data={"dry_run": "true"}, files=files)
			assert resp.status_code == 200
			job_id = resp.json()["job_id"]
			data = await _wait_job_finished(client, job_id)
			assert data["status"] == "done"
			_cleanup_job(job_id)
	asyncio.run(run())


# --- middleware de limite de upload / margem de disco (achado de auditoria) ---

def test_upload_above_max_size_is_rejected_with_413(monkeypatch):
	import main
	monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 10)  # qualquer upload real ja' excede

	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			files = {
				"target": ("foto.jpg", FAKE_JPEG_BYTES, "image/jpeg"),  # bem maior que 10 bytes
			}
			resp = await client.post("/api/jobs/removebg", data={"dry_run": "true"}, files=files)
			assert resp.status_code == 413
	asyncio.run(run())


def test_job_creation_rejected_when_disk_below_safety_margin(monkeypatch):
	import main

	class FakeUsage:
		total = 100 * 1024**3
		used = 99 * 1024**3
		free = 1 * 1024**3  # 1GB - bem abaixo dos 30GB de margem

	monkeypatch.setattr(main.shutil, "disk_usage", lambda path: FakeUsage())

	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			files = {"target": ("foto.jpg", b"conteudo", "image/jpeg")}
			resp = await client.post("/api/jobs/removebg", data={"dry_run": "true"}, files=files)
			assert resp.status_code == 507
	asyncio.run(run())


def test_status_endpoint_unaffected_by_upload_limit_middleware():
	"""O middleware so' se aplica a POST /api/jobs/* - GET /api/status continua livre
	mesmo com disco/upload apertados, porque ela nao grava nada em disco."""
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			resp = await client.get("/api/status")
			assert resp.status_code == 200
	asyncio.run(run())


# --- limpeza automatica de jobs antigos (achado de auditoria) ---

def test_cleanup_old_jobs_removes_expired_entry_from_memory():
	old_job = Job(id="job-antigo-teste", mode="faceswap", created_at=0.0)  # epoch = bem antigo
	JOBS[old_job.id] = old_job
	try:
		removed = cleanup_old_jobs(now=time.time())
		assert removed >= 1
		assert old_job.id not in JOBS
	finally:
		JOBS.pop(old_job.id, None)


def test_cleanup_old_jobs_keeps_recent_entry_in_memory():
	recent_job = Job(id="job-recente-teste", mode="faceswap", created_at=time.time())
	JOBS[recent_job.id] = recent_job
	try:
		cleanup_old_jobs(now=time.time())
		assert recent_job.id in JOBS
	finally:
		JOBS.pop(recent_job.id, None)


def test_cleanup_old_jobs_deletes_expired_upload_dir_but_keeps_recent_one():
	old_dir = os.path.join(UPLOAD_DIR, "pasta-antiga-teste")
	recent_dir = os.path.join(UPLOAD_DIR, "pasta-recente-teste")
	os.makedirs(old_dir, exist_ok=True)
	os.makedirs(recent_dir, exist_ok=True)
	old_cutoff_time = time.time() - 30 * 86400  # 30 dias atras, alem da retencao de 7
	os.utime(old_dir, (old_cutoff_time, old_cutoff_time))
	try:
		cleanup_old_jobs(now=time.time())
		assert not os.path.isdir(old_dir)
		assert os.path.isdir(recent_dir)
	finally:
		shutil.rmtree(old_dir, ignore_errors=True)
		shutil.rmtree(recent_dir, ignore_errors=True)


# --- path traversal na rota catch-all da SPA (achado CRITICO de seguranca) ---

def test_spa_catchall_rejects_path_traversal_to_etc_passwd():
	"""Achado real (varredura de seguranca, nao teorico): a rota catch-all fazia
	os.path.join(STATIC_DIR, full_path) sem checar '..' - confirmado explorado ao vivo
	contra o servidor rodando de verdade (GET com '..' url-encoded devolvia o conteudo
	real de /etc/passwd, leitura arbitraria de arquivo como o usuario do servidor).
	Corrigido com os.path.realpath() + contencao via os.path.commonpath() em
	_safe_static_path(). Reproduz aqui o mesmo payload que funcionou ao vivo."""
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			resp = await client.get("/%2e%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/etc/passwd")
			assert resp.status_code == 200
			assert "root:" not in resp.text
			assert "<!doctype html" in resp.text.lower()
	asyncio.run(run())


def test_spa_catchall_rejects_plain_dotdot_traversal():
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			resp = await client.get("/../../../../../../etc/passwd")
			assert resp.status_code == 200
			assert "root:" not in resp.text
	asyncio.run(run())


def test_spa_catchall_still_serves_real_static_assets():
	"""Confirma que a correcao nao quebrou o caso normal - arquivos reais dentro de
	static/ (ex.: os hashes gerados pelo build do Vite) continuam sendo servidos."""
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			resp = await client.get("/")
			assert resp.status_code == 200
			assert "<!doctype html" in resp.text.lower()

			resp_unknown_route = await client.get("/rosto")
			assert resp_unknown_route.status_code == 200
			assert "<!doctype html" in resp_unknown_route.text.lower()
	asyncio.run(run())


# --- upload com filename "." ou ".." (achado de auditoria, IsADirectoryError nao tratada) ---

def test_upload_with_dotdot_filename_is_rejected_cleanly():
	"""Achado real: filename "..' sobrevive ao os.path.basename() (sem separador, a
	string fica igual) e derrubava save_upload com IsADirectoryError nao tratada (500
	cru). Confirmado ao vivo contra o servidor rodando de verdade antes da correcao.
	Agora deve devolver 400 limpo, nao 500."""
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			files = {"target": ("..", b"conteudo", "image/jpeg")}
			resp = await client.post("/api/jobs/removebg", data={"dry_run": "true"}, files=files)
			assert resp.status_code == 400
	asyncio.run(run())


def test_upload_with_single_dot_filename_is_rejected_cleanly():
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			files = {"target": (".", b"conteudo", "image/jpeg")}
			resp = await client.post("/api/jobs/removebg", data={"dry_run": "true"}, files=files)
			assert resp.status_code == 400
	asyncio.run(run())


def test_save_upload_enforces_real_byte_limit_even_without_content_length(monkeypatch):
	"""Achado real: o middleware de main.py so' checa o cabecalho Content-Length, e
	confirmado ao vivo que um cliente com 'Transfer-Encoding: chunked' passa por essa
	checagem sem declarar o tamanho. jobs.save_upload() agora conta os bytes de verdade
	enquanto grava e aborta sozinho, independente do que o cabecalho dizia (ou nao
	dizia)."""
	import jobs
	monkeypatch.setattr(jobs, "MAX_UPLOAD_BYTES", 10)

	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			files = {"target": ("grande.jpg", FAKE_JPEG_BYTES, "image/jpeg")}  # bem maior que 10 bytes
			resp = await client.post("/api/jobs/removebg", data={"dry_run": "true"}, files=files)
			assert resp.status_code == 413
	asyncio.run(run())


# --- job "fantasma" quando o 2o arquivo de um upload multi-arquivo falha (achado de auditoria) ---

def test_faceswap_partial_upload_failure_does_not_leave_orphaned_job_or_files():
	"""Achado real (revisao de seguimento da auditoria): faceswap recebe 2 arquivos
	(source, target). Antes da correcao, se 'source' fosse salvo com sucesso e 'target'
	falhasse a validacao (ex.: filename ".."), o job ja criado ficava preso em
	status="queued" pra sempre (launch() nunca era chamado) e o arquivo de 'source'
	ficava orfao em disco - confirmado ao vivo contra o servidor rodando de verdade.
	Agora save_uploads() desfaz o job inteiro (remove de JOBS, apaga upload_dir) se
	qualquer upload da mesma requisicao falhar."""
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			jobs_before = set(JOBS.keys())
			files = {
				"source": ("origem.jpg", FAKE_JPEG_BYTES, "image/jpeg"),
				"target": ("..", b"nome invalido", "image/jpeg"),
			}
			resp = await client.post("/api/jobs/faceswap", data={"dry_run": "true"}, files=files)
			assert resp.status_code == 400

			novos_jobs = set(JOBS.keys()) - jobs_before
			assert novos_jobs == set(), "job nao deveria sobrar em JOBS apos falha parcial de upload"

			# nenhuma pasta de upload nova deveria ter sobrevivido a falha
			leftover_dirs = [
				d for d in os.listdir(UPLOAD_DIR)
				if os.path.isdir(os.path.join(UPLOAD_DIR, d))
			]
			for d in leftover_dirs:
				# se sobrou alguma pasta, ela nao pode conter o arquivo "origem.jpg" que
				# teria sido salvo com sucesso antes da falha do segundo upload
				assert not os.path.isfile(os.path.join(UPLOAD_DIR, d, "origem.jpg"))
	asyncio.run(run())


def test_master_partial_upload_failure_does_not_leave_orphaned_job():
	"""Mesmo achado do teste acima, aplicado a master (original + processed_video)."""
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			jobs_before = set(JOBS.keys())
			files = {
				"original": ("original.mp4", FAKE_MP4_BYTES, "video/mp4"),
				"processed_video": (".", b"nome invalido", "video/mp4"),
			}
			resp = await client.post("/api/jobs/master", data={"dry_run": "true"}, files=files)
			assert resp.status_code == 400
			assert set(JOBS.keys()) == jobs_before
	asyncio.run(run())


def test_tts_upload_failure_does_not_leave_orphaned_output_dir():
	"""Achado real (auditoria #3): routes_tts.py chamava set_output() ANTES de
	save_uploads() - diferente das outras 7 rotas. job_output_path() cria a pasta de
	saida como efeito colateral (os.makedirs) mesmo sem nenhum arquivo ainda existir,
	entao um upload de speaker_wav que falhasse depois deixava uma pasta vazia orfa em
	JOB_OUTPUT_DIR, mesmo com save_uploads() ja limpando o job e a pasta de upload.
	Confirmado ao vivo antes da correcao. Corrigido invertendo a ordem."""
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			jobs_before = set(JOBS.keys())
			dirs_before = set(os.listdir(JOB_OUTPUT_DIR)) if os.path.isdir(JOB_OUTPUT_DIR) else set()

			files = {"speaker_wav": ("..", b"nome invalido", "audio/wav")}
			resp = await client.post(
				"/api/jobs/tts", data={"text": "teste", "dry_run": "true"}, files=files,
			)
			assert resp.status_code == 400
			assert set(JOBS.keys()) == jobs_before

			dirs_after = set(os.listdir(JOB_OUTPUT_DIR)) if os.path.isdir(JOB_OUTPUT_DIR) else set()
			assert dirs_after == dirs_before, "nenhuma pasta de output nova deveria sobrar"
	asyncio.run(run())


# --- validacao de assinatura real do arquivo (achado da auditoria QA/Cybersecurity) ---

def test_upload_rejects_file_that_is_not_recognized_as_media():
	"""Achado de auditoria (perspectiva QA/Cybersecurity, pedido explicito de nao
	exagerar na blindagem): um upload de texto puro disfarcado de .jpg passava direto
	antes, e so' ia falhar la' na frente dentro do FFmpeg/FaceFusion com um erro tecnico
	cru. Agora e' rejeitado cedo, com mensagem amigavel, verificando o CONTEUDO real do
	arquivo (assinatura de bytes), nao so' o nome/extensao."""
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			files = {"target": ("foto.jpg", b"isso aqui e' so' texto, nao uma imagem de verdade", "image/jpeg")}
			resp = await client.post("/api/jobs/removebg", data={"dry_run": "true"}, files=files)
			assert resp.status_code == 400
			assert "nao parece ser" in resp.json()["detail"].lower()
	asyncio.run(run())


def test_upload_accepts_real_media_regardless_of_declared_content_type_header():
	"""A checagem e' pela assinatura real dos bytes, nao pelo cabecalho Content-Type
	que o cliente declara (facil de estar errado ou ser mentiroso) - um arquivo PNG de
	verdade e' aceito mesmo se o cliente disser 'image/jpeg' por engano."""
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			files = {"target": ("foto.jpg", FAKE_PNG_BYTES, "image/jpeg")}
			resp = await client.post("/api/jobs/removebg", data={"dry_run": "true"}, files=files)
			assert resp.status_code == 200
			job_id = resp.json()["job_id"]
			data = await _wait_job_finished(client, job_id)
			assert data["status"] == "done"
			_cleanup_job(job_id)
	asyncio.run(run())


def test_upload_rejects_non_media_even_with_empty_content():
	"""Arquivo vazio (0 bytes) e' deixado passar pela checagem de assinatura (nao ha'
	nada pra' inspecionar) - vai falhar mais na frente, no proprio run_vfx.py/FaceFusion,
	com um erro claro de arquivo vazio, nao um 400 confuso de 'tipo invalido'."""
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			files = {"target": ("vazio.jpg", b"", "image/jpeg")}
			resp = await client.post("/api/jobs/removebg", data={"dry_run": "true"}, files=files)
			# dry-run nao chega a processar o conteudo de verdade - so' confirma que nao
			# foi rejeitado erroneamente como "tipo invalido" na validacao de upload
			assert resp.status_code == 200
			job_id = resp.json()["job_id"]
			await _wait_job_finished(client, job_id)
			_cleanup_job(job_id)
	asyncio.run(run())


# --- upscale standalone (pedido do usuario, auditoria de uso profissional) ---

def test_upscale_missing_file_is_rejected():
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			resp = await client.post("/api/jobs/upscale", data={})
			assert resp.status_code == 422
	asyncio.run(run())


def test_upscale_dry_run_completes():
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			files = {"target": ("foto.jpg", FAKE_JPEG_BYTES, "image/jpeg")}
			resp = await client.post("/api/jobs/upscale", data={"dry_run": "true"}, files=files)
			assert resp.status_code == 200
			job_id = resp.json()["job_id"]
			data = await _wait_job_finished(client, job_id)
			assert data["status"] == "done"
			_cleanup_job(job_id)
	asyncio.run(run())


def test_upscale_with_fps_for_video():
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
			files = {"target": ("cena.mp4", FAKE_MP4_BYTES, "video/mp4")}
			resp = await client.post("/api/jobs/upscale", data={"dry_run": "true", "fps": "30"}, files=files)
			assert resp.status_code == 200
			job_id = resp.json()["job_id"]
			data = await _wait_job_finished(client, job_id)
			assert data["status"] == "done"
			_cleanup_job(job_id)
	asyncio.run(run())
