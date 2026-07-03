import asyncio
import os
import shutil
import time

import httpx

from config import JOB_OUTPUT_DIR, UPLOAD_DIR
from jobs import JOBS
from main import app


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
				"source": ("origem.jpg", b"fake-source-bytes", "image/jpeg"),
				"target": ("alvo.jpg", b"fake-target-bytes", "image/jpeg"),
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
				"source_image": ("foto.png", b"fake-png-bytes", "image/png"),
				"mask_image": ("mascara.png", b"fake-mask-bytes", "image/png"),
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
			files = {"target": ("foto.jpg", b"fake-photo-bytes", "image/jpeg")}
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
				"audio": ("fala.wav", b"fake-wav-bytes", "audio/wav"),
				"video": ("video.mp4", b"fake-mp4-bytes", "video/mp4"),
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
			files = {"target": ("audio.wav", b"fake-wav-bytes", "audio/wav")}
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
			files = {"target": ("audio.wav", b"fake-wav-bytes", "audio/wav")}
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
				"original": ("original.mp4", b"fake-original-bytes", "video/mp4"),
				"processed_video": ("processado.mp4", b"fake-processed-bytes", "video/mp4"),
			}
			resp = await client.post("/api/jobs/master", data={"dry_run": "true"}, files=files)
			assert resp.status_code == 200
			job_id = resp.json()["job_id"]
			data = await _wait_job_finished(client, job_id)
			assert data["status"] == "done"
			_cleanup_job(job_id)
	asyncio.run(run())
