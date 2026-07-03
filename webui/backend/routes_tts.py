from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from jobs import finish, job_upload_dir, new_job, save_upload, set_output

router = APIRouter()


@router.post("/jobs/tts")
async def create_tts_job(
	text: str = Form(...),
	language: str = Form("pt"),
	speaker: Optional[str] = Form(None),
	speaker_wav: Optional[UploadFile] = File(None),
	dry_run: bool = Form(False),
):
	has_speaker_wav = speaker_wav is not None and bool(speaker_wav.filename)
	if not speaker and not has_speaker_wav:
		raise HTTPException(400, "Informe 'speaker' (voz pronta) ou envie uma amostra em 'speaker_wav'.")

	job = new_job("tts")
	upload_dir = job_upload_dir(job.id)
	output_path = set_output(job, "fala_gerada.wav")

	extra_args = ["--text", text, "--language", language, "--output", output_path]
	if speaker:
		extra_args += ["--speaker", speaker]
	if has_speaker_wav:
		speaker_wav_path = await save_upload(upload_dir, speaker_wav)
		extra_args += ["--speaker-wav", speaker_wav_path]
	return finish(job, extra_args, dry_run)
