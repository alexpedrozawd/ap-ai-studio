from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile

from jobs import job_output_path, job_upload_dir, launch, new_job
from routes_faceswap import save_upload

router = APIRouter()


@router.post("/jobs/video")
async def create_video_job(
	prompt: str = Form(...),
	width: Optional[int] = Form(None),
	height: Optional[int] = Form(None),
	num_frames: Optional[int] = Form(None),
	source_image: Optional[UploadFile] = File(None),
	dry_run: bool = Form(False),
):
	job = new_job("video")
	upload_dir = job_upload_dir(job.id)

	extra_args = ["--prompt", prompt]
	if width:
		extra_args += ["--width", str(width)]
	if height:
		extra_args += ["--height", str(height)]
	if num_frames:
		extra_args += ["--num-frames", str(num_frames)]
	if source_image is not None and source_image.filename:
		source_image_path = await save_upload(upload_dir, source_image)
		extra_args += ["--source-image", source_image_path]

	output_path = job_output_path(job.id, "video_resultado.mp4")
	job.output_path = output_path
	extra_args += ["--output", output_path]
	if dry_run:
		extra_args += ["--dry-run"]

	launch(job, extra_args)
	return {"job_id": job.id}
