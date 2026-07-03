from typing import Optional

from fastapi import APIRouter, Form

from jobs import job_output_path, launch, new_job

router = APIRouter()


@router.post("/jobs/music")
async def create_music_job(
	prompt: str = Form(...),
	duration: Optional[float] = Form(None),
	dry_run: bool = Form(False),
):
	job = new_job("music")
	output_path = job_output_path(job.id, "musica_gerada.wav")
	job.output_path = output_path

	extra_args = ["--prompt", prompt, "--output", output_path]
	if duration:
		extra_args += ["--music-duration", str(duration)]
	if dry_run:
		extra_args += ["--dry-run"]
	launch(job, extra_args)
	return {"job_id": job.id}
