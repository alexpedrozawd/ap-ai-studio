import os

from fastapi import APIRouter, File, Form, UploadFile

from jobs import job_output_path, job_upload_dir, launch, new_job
from routes_faceswap import save_upload

router = APIRouter()


@router.post("/jobs/removebg")
async def create_removebg_job(
	target: UploadFile = File(...),
	dry_run: bool = Form(False),
):
	job = new_job("removebg")
	upload_dir = job_upload_dir(job.id)
	target_path = await save_upload(upload_dir, target)
	base, ext = os.path.splitext(os.path.basename(target_path))
	# Achado real (QA, job de verdade pela API): o proprio FaceFusion recusa rodar se a
	# extensao de saida nao for IDENTICA a extensao de entrada (validacao dele mesmo,
	# same_file_extension em background_remover/core.py) - "match the target and
	# output extension!". Forcar .png (pensando em transparencia) quebra pra qualquer
	# entrada que nao seja .png. Mantemos a extensao original; se quiser transparencia
	# de verdade, envie uma foto de origem ja' em .png.
	output_path = job_output_path(job.id, f"{base}_sem_fundo{ext}")
	job.output_path = output_path

	extra_args = ["--target", target_path, "--output", output_path]
	if dry_run:
		extra_args += ["--dry-run"]
	launch(job, extra_args)
	return {"job_id": job.id}
