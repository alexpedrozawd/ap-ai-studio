from typing import Optional

from fastapi import APIRouter, Form

from jobs import finish, new_job, set_output

router = APIRouter()


@router.post("/jobs/music")
async def create_music_job(
	prompt: str = Form(...),
	duration: Optional[float] = Form(None),
	dry_run: bool = Form(False),
):
	job = new_job("music")
	output_path = set_output(job, "musica_gerada.wav")

	extra_args = ["--prompt", prompt, "--output", output_path]
	if duration:
		extra_args += ["--music-duration", str(duration)]
	return finish(job, extra_args, dry_run)
