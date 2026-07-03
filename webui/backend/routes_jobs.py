import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from jobs import JOBS

router = APIRouter()

LOG_TAIL_LINES = 300


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
	job = JOBS.get(job_id)
	if job is None:
		raise HTTPException(404, "job nao encontrado")
	return {
		"id": job.id,
		"mode": job.mode,
		"status": job.status,
		"returncode": job.returncode,
		"log_tail": job.log_lines[-LOG_TAIL_LINES:],
		"output_ready": job.status == "done" and bool(job.output_path) and os.path.isfile(job.output_path),
		"secondary_output_ready": (
			job.status == "done" and bool(job.secondary_output_path) and os.path.isfile(job.secondary_output_path)
		),
	}


@router.get("/jobs/{job_id}/output")
async def get_job_output(job_id: str):
	job = JOBS.get(job_id)
	if job is None:
		raise HTTPException(404, "job nao encontrado")
	if not job.output_path or not os.path.isfile(job.output_path):
		raise HTTPException(404, "arquivo de saida ainda nao disponivel")
	return FileResponse(job.output_path, filename=os.path.basename(job.output_path))


@router.get("/jobs/{job_id}/output-secondary")
async def get_job_secondary_output(job_id: str):
	"""So' usado pelo modo denoise (--output-instrumental e' opcional)."""
	job = JOBS.get(job_id)
	if job is None:
		raise HTTPException(404, "job nao encontrado")
	if not job.secondary_output_path or not os.path.isfile(job.secondary_output_path):
		raise HTTPException(404, "arquivo de saida secundaria ainda nao disponivel")
	return FileResponse(job.secondary_output_path, filename=os.path.basename(job.secondary_output_path))
