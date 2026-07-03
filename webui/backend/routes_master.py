from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile

from jobs import job_output_path, job_upload_dir, launch, new_job
from routes_faceswap import save_upload

router = APIRouter()


@router.post("/jobs/master")
async def create_master_job(
	original: UploadFile = File(...),
	processed_video: UploadFile = File(...),
	fps: Optional[float] = Form(None),
	dry_run: bool = Form(False),
):
	job = new_job("master")
	upload_dir = job_upload_dir(job.id)
	original_path = await save_upload(upload_dir, original)
	processed_path = await save_upload(upload_dir, processed_video)
	output_path = job_output_path(job.id, "video_final.mp4")
	job.output_path = output_path

	extra_args = ["--original", original_path, "--processed-video", processed_path, "--output", output_path]
	if fps:
		extra_args += ["--fps", str(fps)]
	if dry_run:
		extra_args += ["--dry-run"]
	launch(job, extra_args)
	return {"job_id": job.id}
