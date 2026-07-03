import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from config import WEBUI_HOST
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

app = FastAPI(title="AP AI Studio - Web UI")

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
		candidate = os.path.join(STATIC_DIR, full_path)
		if full_path and os.path.isfile(candidate):
			return FileResponse(candidate)
		return FileResponse(os.path.join(STATIC_DIR, "index.html"))
