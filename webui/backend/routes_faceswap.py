import os
from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile

from jobs import finish, job_upload_dir, new_job, save_upload, set_output

router = APIRouter()


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
	output_path = set_output(job, "resultado_" + os.path.basename(target_path))

	extra_args = ["--source", source_path, "--target", target_path, "--output", output_path]
	if chunk_seconds:
		extra_args += ["--chunk-seconds", str(chunk_seconds)]
	return finish(job, extra_args, dry_run)
