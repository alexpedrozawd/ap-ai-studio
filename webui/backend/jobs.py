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
import shutil
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from fastapi import HTTPException, UploadFile

from config import JOB_OUTPUT_DIR, JOB_RETENTION_DAYS, MAX_UPLOAD_BYTES, UPLOAD_DIR, VFX_PY, VFX_SCRIPT

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


def set_output(job: Job, filename: str) -> str:
	"""Monta o caminho de saida do job (dentro de JOB_OUTPUT_DIR) e ja marca em job.output_path
	- as duas linhas que toda rota de job precisava repetir."""
	path = job_output_path(job.id, filename)
	job.output_path = path
	return path


async def save_upload(dest_dir: str, upload: UploadFile) -> str:
	"""Salva um arquivo enviado via multipart. os.path.basename() descarta qualquer
	componente de diretorio do nome original - o arquivo sempre cai dentro de dest_dir,
	nunca fora dele. Achado de auditoria (varredura de seguranca): um filename igual a
	"." ou ".." sobrevive ao basename() (ele so' remove tudo ATE' o ultimo separador -
	sem separador, a string fica igual) e vira um os.path.join(dest_dir, "..") que
	aponta pro diretorio pai - open(..., "wb") falhava com IsADirectoryError nao tratada
	(500 cru). Nao e' um escape de verdade (so' sobe um nivel, ainda dentro da propria
	arvore da aplicacao), mas e' entrada nao validada causando crash - rejeitada
	explicitamente agora com 400 antes de chegar no open()."""
	filename = os.path.basename(upload.filename or "arquivo")
	if not filename or filename in (".", ".."):
		raise HTTPException(400, "Nome de arquivo invalido.")
	dest_path = os.path.join(dest_dir, filename)
	# Achado de auditoria: o middleware de main.py so' checa o cabecalho Content-Length -
	# confirmado ao vivo que um cliente pode omiti-lo (Transfer-Encoding: chunked) e
	# passar direto por aquela checagem. Contamos os bytes de verdade aqui, na hora de
	# gravar, e abortamos assim que passar do limite - nao da' pra mentir sobre o
	# tamanho real dos bytes que estao sendo escritos em disco.
	written = 0
	try:
		with open(dest_path, "wb") as f:
			while chunk := await upload.read(1024 * 1024):
				written += len(chunk)
				if written > MAX_UPLOAD_BYTES:
					raise HTTPException(413, f"Upload maior que o limite de {MAX_UPLOAD_BYTES // (1024**3)}GB.")
				f.write(chunk)
	except HTTPException:
		if os.path.isfile(dest_path):
			os.remove(dest_path)
		raise
	await upload.close()
	return dest_path


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


def finish(job: Job, extra_args: list[str], dry_run: bool) -> dict:
	"""Achado de auditoria: as 8 rotas que passam por run_vfx.py (faceswap, video,
	inpaint, removebg, tts, denoise, music, master) terminavam todas com o mesmo trecho
	quase identico - anexar --dry-run se pedido, disparar o job e devolver o job_id pro
	frontend comecar o polling. Extraido aqui pra nao repetir esse fechamento 8 vezes."""
	if dry_run:
		extra_args = [*extra_args, "--dry-run"]
	launch(job, extra_args)
	return {"job_id": job.id}


def cleanup_old_jobs(now: Optional[float] = None) -> int:
	"""Achado de auditoria: JOBS crescia pra sempre em memoria (some tudo se a webui
	reiniciar), e as pastas de upload/output nunca eram limpas automaticamente. Remove
	jobs com mais de JOB_RETENTION_DAYS tanto do dict em memoria quanto do disco -
	e tambem varre pastas orfas em UPLOAD_DIR/JOB_OUTPUT_DIR sem entrada correspondente
	em JOBS (sobra de reinicios anteriores, que perdem o registro em memoria mas nao os
	arquivos). Chamada uma vez na subida do processo e periodicamente depois (ver
	main.py). Devolve quantos jobs foram removidos do registro em memoria."""
	now = now if now is not None else time.time()
	cutoff = now - JOB_RETENTION_DAYS * 86400
	removed = 0

	for job_id in [jid for jid, job in JOBS.items() if job.created_at < cutoff]:
		JOBS.pop(job_id, None)
		removed += 1

	for base_dir in (UPLOAD_DIR, JOB_OUTPUT_DIR):
		if not os.path.isdir(base_dir):
			continue
		for entry in os.listdir(base_dir):
			entry_path = os.path.join(base_dir, entry)
			try:
				if os.path.isdir(entry_path) and os.path.getmtime(entry_path) < cutoff:
					shutil.rmtree(entry_path, ignore_errors=True)
			except OSError:
				continue

	return removed
