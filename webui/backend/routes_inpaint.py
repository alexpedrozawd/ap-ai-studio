import os
from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile

from jobs import finish, job_upload_dir, new_job, save_uploads, set_output

router = APIRouter()


@router.post("/jobs/inpaint")
async def create_inpaint_job(
	source_image: UploadFile = File(...),
	mask_image: UploadFile = File(...),
	prompt: Optional[str] = Form(None),
	use_depth_controlnet: bool = Form(False),
	controlnet_strength: float = Form(0.6),
	dry_run: bool = Form(False),
):
	job = new_job("inpaint")
	upload_dir = job_upload_dir(job.id)
	paths = await save_uploads(job, upload_dir, source_image=source_image, mask_image=mask_image)
	source_path, mask_path = paths["source_image"], paths["mask_image"]
	output_path = set_output(job, "editado_" + os.path.basename(source_path))

	extra_args = ["--source-image", source_path, "--mask-image", mask_path, "--output", output_path]
	if prompt:
		extra_args += ["--prompt", prompt]
	if use_depth_controlnet:
		extra_args += ["--use-depth-controlnet", "--controlnet-strength", str(controlnet_strength)]
	return finish(job, extra_args, dry_run)
