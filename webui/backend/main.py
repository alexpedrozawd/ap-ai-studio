import asyncio
import os
import shutil
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from config import DISK_SAFETY_MARGIN_GB, MAX_UPLOAD_BYTES, WEBUI_HOST
from jobs import cleanup_old_jobs
from routes_denoise import router as denoise_router
from routes_dub import router as dub_router
from routes_faceswap import router as faceswap_router
from routes_inpaint import router as inpaint_router
from routes_jobs import router as jobs_router
from routes_master import router as master_router
from routes_music import router as music_router
from routes_removebg import router as removebg_router
from routes_status import router as status_router
from routes_tts import router as tts_router
from routes_video import router as video_router

CLEANUP_INTERVAL_SECONDS = 6 * 3600


async def _cleanup_loop() -> None:
	while True:
		await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
		cleanup_old_jobs()


@asynccontextmanager
async def lifespan(app: FastAPI):
	# Roda uma vez na subida (varre sobras de jobs de antes de um restart, ver
	# cleanup_old_jobs) e depois periodicamente enquanto o processo estiver de pe.
	cleanup_old_jobs()
	task = asyncio.create_task(_cleanup_loop())
	yield
	task.cancel()


app = FastAPI(title="AP AI Studio - Web UI", lifespan=lifespan)

# So' usado em desenvolvimento (Vite dev server em porta separada). Em uso normal, o
# frontend buildado e' servido pelo mesmo processo/origem (StaticFiles abaixo), sem CORS.
app.add_middleware(
	CORSMiddleware,
	allow_origins=[
		"http://127.0.0.1:5173", "http://localhost:5173", f"http://{WEBUI_HOST}:5173",
	],
	allow_methods=["*"],
	allow_headers=["*"],
)

@app.middleware("http")
async def enforce_upload_limits(request: Request, call_next):
	"""Achado de auditoria: o upload multipart era salvo em disco antes do Gate 3 do
	run_vfx.py ter qualquer chance de checar espaco livre, e nao havia limite de
	tamanho. Este middleware roda ANTES do FastAPI/Starlette ler o corpo da requisicao -
	rejeita uploads grandes demais (Content-Length) e requisicoes de criacao de job
	quando o disco ja esta abaixo da margem de seguranca, sem gastar tempo/IO com o
	corpo da requisicao."""
	if request.method == "POST" and request.url.path.startswith("/api/jobs/"):
		content_length = request.headers.get("content-length")
		if content_length and int(content_length) > MAX_UPLOAD_BYTES:
			limit_gb = MAX_UPLOAD_BYTES / (1024**3)
			return JSONResponse(
				{"detail": f"Upload maior que o limite de {limit_gb:.0f}GB."}, status_code=413,
			)
		free_gb = shutil.disk_usage("/").free / (1024**3)
		if free_gb < DISK_SAFETY_MARGIN_GB:
			return JSONResponse(
				{
					"detail": (
						f"Espaco em disco abaixo da margem de seguranca "
						f"({free_gb:.1f}GB livres, minimo {DISK_SAFETY_MARGIN_GB}GB) - "
						"job recusado antes do upload."
					)
				},
				status_code=507,
			)
	return await call_next(request)


app.include_router(status_router, prefix="/api")
app.include_router(faceswap_router, prefix="/api")
app.include_router(video_router, prefix="/api")
app.include_router(inpaint_router, prefix="/api")
app.include_router(removebg_router, prefix="/api")
app.include_router(tts_router, prefix="/api")
app.include_router(dub_router, prefix="/api")
app.include_router(denoise_router, prefix="/api")
app.include_router(music_router, prefix="/api")
app.include_router(master_router, prefix="/api")
app.include_router(jobs_router, prefix="/api")

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
STATIC_DIR_REAL = os.path.realpath(STATIC_DIR)


def _safe_static_path(full_path: str) -> Optional[str]:
	"""Achado CRITICO de auditoria (varredura de seguranca): a versao anterior fazia
	os.path.join(STATIC_DIR, full_path) com full_path vindo direto da URL, sem checar
	'..' - confirmado explorável ao vivo (GET /../../../../etc/passwd, com os pontos
	url-encoded pra nao serem normalizados pelo cliente HTTP antes de sair, devolvia o
	conteudo real de /etc/passwd). os.path.realpath() resolve '..'/symlinks de verdade,
	e so' devolvemos o caminho se ele continuar DENTRO de STATIC_DIR_REAL depois de
	resolvido - qualquer tentativa de escapar do diretorio cai no None (serve index.html)."""
	candidate = os.path.realpath(os.path.join(STATIC_DIR, full_path))
	if os.path.commonpath([candidate, STATIC_DIR_REAL]) != STATIC_DIR_REAL:
		return None
	return candidate


if os.path.isdir(STATIC_DIR):
	# Achado real (QA no navegador): StaticFiles(html=True) sozinho NAO faz fallback de
	# SPA - navegar direto pra uma sub-rota do React Router (ex.: /voz, ou dar F5 nela)
	# devolvia 404, porque so' existe um arquivo fisico (index.html) na raiz. Esse
	# catch-all serve o arquivo estatico se ele existir (JS/CSS/imagens) e cai pro
	# index.html em qualquer outra rota, deixando o React Router decidir o resto.
	@app.get("/{full_path:path}")
	async def serve_spa(full_path: str):
		if full_path.startswith("api/"):
			raise HTTPException(status_code=404)
		candidate = _safe_static_path(full_path) if full_path else None
		if candidate and os.path.isfile(candidate):
			return FileResponse(candidate)
		return FileResponse(os.path.join(STATIC_DIR, "index.html"))
