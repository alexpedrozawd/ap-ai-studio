from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile

from jobs import finish, job_upload_dir, new_job, save_uploads, set_output

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
	paths = await save_uploads(job, upload_dir, original=original, processed_video=processed_video)
	original_path, processed_path = paths["original"], paths["processed_video"]
	output_path = set_output(job, "video_final.mp4")

	extra_args = ["--original", original_path, "--processed-video", processed_path, "--output", output_path]
	if fps:
		extra_args += ["--fps", str(fps)]
	return finish(job, extra_args, dry_run)
