import os
from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile

from jobs import job_output_path, job_upload_dir, launch, new_job

router = APIRouter()


async def save_upload(dest_dir: str, upload: UploadFile) -> str:
	filename = os.path.basename(upload.filename or "arquivo")
	dest_path = os.path.join(dest_dir, filename)
	with open(dest_path, "wb") as f:
		while chunk := await upload.read(1024 * 1024):
			f.write(chunk)
	await upload.close()
	return dest_path


@router.post("/jobs/faceswap")
async def create_faceswap_job(
	source: UploadFile = File(...),
	target: UploadFile = File(...),
	chunk_seconds: Optional[int] = Form(None),
	dry_run: bool = Form(False),
):
	job = new_job("faceswap")
	upload_dir = job_upload_dir(job.id)
	source_path = await save_upload(upload_dir, source)
	target_path = await save_upload(upload_dir, target)
	output_path = job_output_path(job.id, "resultado_" + os.path.basename(target_path))
	job.output_path = output_path

	extra_args = ["--source", source_path, "--target", target_path, "--output", output_path]
	if chunk_seconds:
		extra_args += ["--chunk-seconds", str(chunk_seconds)]
	if dry_run:
		extra_args += ["--dry-run"]
	launch(job, extra_args)
	return {"job_id": job.id}
