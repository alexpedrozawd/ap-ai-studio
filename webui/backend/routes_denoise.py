from fastapi import APIRouter, File, Form, UploadFile

from jobs import finish, job_output_path, job_upload_dir, new_job, save_uploads, set_output

router = APIRouter()


@router.post("/jobs/denoise")
async def create_denoise_job(
	target: UploadFile = File(...),
	want_instrumental: bool = Form(False),
	dry_run: bool = Form(False),
):
	job = new_job("denoise")
	upload_dir = job_upload_dir(job.id)
	paths = await save_uploads(job, upload_dir, target=target)
	target_path = paths["target"]
	output_path = set_output(job, "voz_isolada.wav")

	extra_args = ["--target", target_path, "--output", output_path]
	if want_instrumental:
		instrumental_path = job_output_path(job.id, "resto_audio.wav")
		job.secondary_output_path = instrumental_path
		extra_args += ["--output-instrumental", instrumental_path]
	return finish(job, extra_args, dry_run)
