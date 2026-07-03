import os
from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile

from jobs import finish, job_upload_dir, new_job, save_uploads, set_output

router = APIRouter()


@router.post("/jobs/upscale")
async def create_upscale_job(
	target: UploadFile = File(...),
	fps: Optional[float] = Form(None),
	dry_run: bool = Form(False),
):
	"""Pedido do usuario (auditoria de uso profissional): aumentar a resolucao de uma
	foto/video ja existente (ex.: foto antiga de familia), reaproveitando o mesmo
	Real-ESRGAN ja usado internamente no modo `video`. `fps` so' importa se o alvo for
	video (run_vfx.py detecta pela extensao)."""
	job = new_job("upscale")
	upload_dir = job_upload_dir(job.id)
	paths = await save_uploads(job, upload_dir, target=target)
	target_path = paths["target"]
	base, ext = os.path.splitext(os.path.basename(target_path))
	output_path = set_output(job, f"{base}_upscale{ext}")

	extra_args = ["--target", target_path, "--output", output_path]
	if fps:
		extra_args += ["--fps", str(fps)]
	return finish(job, extra_args, dry_run)
