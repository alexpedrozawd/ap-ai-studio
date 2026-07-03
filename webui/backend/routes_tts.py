from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from jobs import finish, job_upload_dir, new_job, save_uploads, set_output

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
	# Achado de auditoria (revisao de seguimento): set_output() estava sendo chamado
	# ANTES do upload - job_output_path() cria a pasta de saida como efeito colateral
	# (os.makedirs), entao se o upload falhasse depois, sobrava uma pasta vazia orfa em
	# JOB_OUTPUT_DIR mesmo com save_uploads() ja limpando o job e a pasta de upload.
	# Confirmado ao vivo. Corrigido: upload primeiro (pode falhar e desfazer o job
	# inteiro via save_uploads), set_output() so' depois - mesma ordem das outras 7 rotas.
	extra_args = ["--text", text, "--language", language]
	if speaker:
		extra_args += ["--speaker", speaker]
	if has_speaker_wav:
		paths = await save_uploads(job, upload_dir, speaker_wav=speaker_wav)
		extra_args += ["--speaker-wav", paths["speaker_wav"]]

	output_path = set_output(job, "fala_gerada.wav")
	extra_args += ["--output", output_path]
	return finish(job, extra_args, dry_run)
