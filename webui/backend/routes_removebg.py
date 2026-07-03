import os

from fastapi import APIRouter, File, Form, UploadFile

from jobs import finish, job_upload_dir, new_job, save_uploads, set_output

router = APIRouter()


@router.post("/jobs/removebg")
async def create_removebg_job(
	target: UploadFile = File(...),
	dry_run: bool = Form(False),
):
	job = new_job("removebg")
	upload_dir = job_upload_dir(job.id)
	paths = await save_uploads(job, upload_dir, target=target)
	target_path = paths["target"]
	base, ext = os.path.splitext(os.path.basename(target_path))
	# Achado real (QA, job de verdade pela API): o proprio FaceFusion recusa rodar se a
	# extensao de saida nao for IDENTICA a extensao de entrada (validacao dele mesmo,
	# same_file_extension em background_remover/core.py) - "match the target and
	# output extension!". Forcar .png (pensando em transparencia) quebra pra qualquer
	# entrada que nao seja .png. Mantemos a extensao original; se quiser transparencia
	# de verdade, envie uma foto de origem ja' em .png.
	output_path = set_output(job, f"{base}_sem_fundo{ext}")

	extra_args = ["--target", target_path, "--output", output_path]
	return finish(job, extra_args, dry_run)
