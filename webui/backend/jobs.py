"""Registro de jobs em memoria + execucao do run_vfx.py como subprocesso.

Decisao de arquitetura (ver plano da Fase A): o backend nao reimplementa Gates nem fala
direto com ComfyUI/FaceFusion - ele chama run_vfx.py exatamente como os atalhos vfx-*
(interprete do env vfx-pipeline pelo caminho absoluto, subprocesso assincrono), com
--auto-approve. O Gate 3 (disco) nao e' pulavel mesmo com --auto-approve (por design,
ver run_vfx.py) - alimentamos stdin com "y" pra equivaler ao clique de "Iniciar" ja ter
aprovado a execucao (mesma coisa que apertar Enter no terminal).
"""

import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from config import JOB_OUTPUT_DIR, UPLOAD_DIR, VFX_PY, VFX_SCRIPT

MAX_LOG_LINES = 2000


@dataclass
class Job:
	id: str
	mode: str
	status: str = "queued"  # queued -> running -> done | error
	returncode: Optional[int] = None
	log_lines: list = field(default_factory=list)
	output_path: Optional[str] = None
	# So' usado pelo modo denoise (--output-instrumental e' opcional e separado do
	# --output principal, que sempre e' a voz isolada).
	secondary_output_path: Optional[str] = None
	created_at: float = field(default_factory=time.time)


JOBS: dict[str, Job] = {}


def new_job(mode: str) -> Job:
	job = Job(id=uuid.uuid4().hex[:12], mode=mode)
	JOBS[job.id] = job
	return job


def job_upload_dir(job_id: str) -> str:
	path = os.path.join(UPLOAD_DIR, job_id)
	os.makedirs(path, exist_ok=True)
	return path


def job_output_path(job_id: str, filename: str) -> str:
	out_dir = os.path.join(JOB_OUTPUT_DIR, job_id)
	os.makedirs(out_dir, exist_ok=True)
	return os.path.join(out_dir, filename)


async def _stream_output(job: Job, stream: asyncio.StreamReader) -> None:
	while True:
		line = await stream.readline()
		if not line:
			break
		text = line.decode(errors="replace").rstrip("\n")
		job.log_lines.append(text)
		if len(job.log_lines) > MAX_LOG_LINES:
			job.log_lines = job.log_lines[-MAX_LOG_LINES:]


async def _run(job: Job, cmd: list[str], cwd: Optional[str], env: Optional[dict]) -> None:
	job.status = "running"
	try:
		proc = await asyncio.create_subprocess_exec(
			*cmd, cwd=cwd, env=env,
			stdin=asyncio.subprocess.PIPE,
			stdout=asyncio.subprocess.PIPE,
			stderr=asyncio.subprocess.STDOUT,
		)
		if proc.stdin is not None:
			proc.stdin.write(b"y\n" * 5)
			await proc.stdin.drain()
			proc.stdin.close()
		await _stream_output(job, proc.stdout)
		returncode = await proc.wait()
		job.returncode = returncode
		job.status = "done" if returncode == 0 else "error"
	except Exception as exc:
		job.log_lines.append(f"[webui] excecao ao rodar subprocesso: {exc}")
		job.returncode = -1
		job.status = "error"


def launch(job: Job, extra_args: list[str], cwd: Optional[str] = None, env: Optional[dict] = None) -> None:
	"""Dispara run_vfx.py --mode <job.mode> --auto-approve <extra_args...> - usado por
	todo modo que passa pelo orquestrador (faceswap, video, inpaint, removebg, tts,
	denoise, music, master)."""
	cmd = [VFX_PY, VFX_SCRIPT, "--mode", job.mode, "--auto-approve", *extra_args]
	launch_cmd(job, cmd, cwd=cwd, env=env)


def launch_cmd(job: Job, cmd: list[str], cwd: Optional[str] = None, env: Optional[dict] = None) -> None:
	"""Dispara um comando arbitrario como subprocesso (mesma jaula de log/stdin que
	launch()). Usado pela dublagem, que chama facefusion.py headless-run diretamente
	(nao passa por run_vfx.py - ver MANUAL_USO.md secao 4.9, esse modo nao tem --mode
	dedicado no orquestrador)."""
	asyncio.create_task(_run(job, cmd, cwd, env))
