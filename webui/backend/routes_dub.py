import os

from fastapi import APIRouter, File, Form, UploadFile

from config import FACEFUSION_DIR, FACEFUSION_PY
from jobs import job_output_path, job_upload_dir, launch_cmd, new_job
from routes_faceswap import save_upload

router = APIRouter()


@router.post("/jobs/dub")
async def create_dub_job(
	audio: UploadFile = File(...),
	video: UploadFile = File(...),
	dry_run: bool = Form(False),
):
	"""Dublagem (sincronia labial) - nao passa por run_vfx.py (esse modo ainda nao tem
	--mode dedicado la', ver MANUAL_USO.md secao 4.9). Chama facefusion.py headless-run
	direto, no ambiente Conda proprio dele. Roda em CPU por decisao de arquitetura ja
	validada (incompatibilidade de driver com essa GPU nessa operacao especifica)."""
	job = new_job("dublagem")
	upload_dir = job_upload_dir(job.id)
	audio_path = await save_upload(upload_dir, audio)
	video_path = await save_upload(upload_dir, video)
	output_path = job_output_path(job.id, "dublado_" + os.path.basename(video_path))
	job.output_path = output_path

	if dry_run:
		# facefusion.py nao tem --dry-run - simulamos so' validando os arquivos e
		# devolvendo sem rodar, pra manter a mesma opcao de teste das outras paginas.
		job.log_lines.append("[webui] modo teste: dublagem nao rodou de verdade (facefusion.py nao tem --dry-run).")
		job.status = "done"
		job.returncode = 0
		return {"job_id": job.id}

	cmd = [
		FACEFUSION_PY, "facefusion.py", "headless-run",
		"--processors", "lip_syncer",
		"-s", audio_path, "-t", video_path, "-o", output_path,
		"--execution-providers", "cpu",
	]
	launch_cmd(job, cmd, cwd=FACEFUSION_DIR)
	return {"job_id": job.id}
