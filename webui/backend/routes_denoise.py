from fastapi import APIRouter, File, Form, UploadFile

from jobs import job_output_path, job_upload_dir, launch, new_job
from routes_faceswap import save_upload

router = APIRouter()


@router.post("/jobs/denoise")
async def create_denoise_job(
	target: UploadFile = File(...),
	want_instrumental: bool = Form(False),
	dry_run: bool = Form(False),
):
	job = new_job("denoise")
	upload_dir = job_upload_dir(job.id)
	target_path = await save_upload(upload_dir, target)
	output_path = job_output_path(job.id, "voz_isolada.wav")
	job.output_path = output_path

	extra_args = ["--target", target_path, "--output", output_path]
	if want_instrumental:
		instrumental_path = job_output_path(job.id, "resto_audio.wav")
		job.secondary_output_path = instrumental_path
		extra_args += ["--output-instrumental", instrumental_path]
	if dry_run:
		extra_args += ["--dry-run"]
	launch(job, extra_args)
	return {"job_id": job.id}
