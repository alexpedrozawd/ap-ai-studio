import os
from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile

from jobs import finish, job_upload_dir, new_job, save_upload, set_output

router = APIRouter()


@router.post("/jobs/inpaint")
async def create_inpaint_job(
	source_image: UploadFile = File(...),
	mask_image: UploadFile = File(...),
	prompt: Optional[str] = Form(None),
	dry_run: bool = Form(False),
):
	job = new_job("inpaint")
	upload_dir = job_upload_dir(job.id)
	source_path = await save_upload(upload_dir, source_image)
	mask_path = await save_upload(upload_dir, mask_image)
	output_path = set_output(job, "editado_" + os.path.basename(source_path))

	extra_args = ["--source-image", source_path, "--mask-image", mask_path, "--output", output_path]
	if prompt:
		extra_args += ["--prompt", prompt]
	return finish(job, extra_args, dry_run)
