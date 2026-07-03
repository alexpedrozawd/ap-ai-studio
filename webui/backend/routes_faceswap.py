import os
from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile

from jobs import finish, job_upload_dir, new_job, save_uploads, set_output

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
	paths = await save_uploads(job, upload_dir, source=source, target=target)
	source_path, target_path = paths["source"], paths["target"]
	output_path = set_output(job, "resultado_" + os.path.basename(target_path))

	extra_args = ["--source", source_path, "--target", target_path, "--output", output_path]
	if chunk_seconds:
		extra_args += ["--chunk-seconds", str(chunk_seconds)]
	return finish(job, extra_args, dry_run)
