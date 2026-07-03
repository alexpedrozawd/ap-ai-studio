from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile

from jobs import finish, job_upload_dir, new_job, save_upload, set_output

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
	output_path = set_output(job, "video_final.mp4")

	extra_args = ["--original", original_path, "--processed-video", processed_path, "--output", output_path]
	if fps:
		extra_args += ["--fps", str(fps)]
	return finish(job, extra_args, dry_run)
