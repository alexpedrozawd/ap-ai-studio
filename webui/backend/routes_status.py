import asyncio
import glob
import os
import shutil
from typing import Optional

import aiohttp
from fastapi import APIRouter

from config import COMFYUI_DIR, COMFYUI_HOST, COMFYUI_PORT, VFX_DIR, VFX_PY
from utils import truncate_log_if_large

router = APIRouter()


async def comfyui_up() -> bool:
	try:
		async with aiohttp.ClientSession() as session:
			async with session.get(
				f"http://{COMFYUI_HOST}:{COMFYUI_PORT}/system_stats",
				timeout=aiohttp.ClientTimeout(total=2),
			) as resp:
				return resp.status == 200
	except Exception:
		return False


AMDGPU_VRAM_TOTAL_GLOB = "/sys/class/drm/card*/device/mem_info_vram_total"
AMDGPU_VRAM_USED_GLOB = "/sys/class/drm/card*/device/mem_info_vram_used"


def _vram_info() -> Optional[dict]:
	"""VRAM da GPU AMD lida do sysfs do amdgpu (migrado de nvidia-smi).

	Sem subprocesso: some junto o achado do SAST (bandit B607) sobre caminho absoluto de
	binario, porque nao ha mais binario externo envolvido. O amdgpu expoe total e usado em
	bytes; o livre e' a diferenca (nao existe campo 'free' direto, como havia no nvidia-smi).
	"""
	try:
		total_files = sorted(glob.glob(AMDGPU_VRAM_TOTAL_GLOB))
		used_files = sorted(glob.glob(AMDGPU_VRAM_USED_GLOB))
		if not total_files or not used_files:
			return None
		with open(total_files[0]) as f:
			total_bytes = int(f.read().strip())
		with open(used_files[0]) as f:
			used_bytes = int(f.read().strip())
		free_bytes = total_bytes - used_bytes
		if free_bytes < 0:
			return None
		mb = 1024 * 1024
		return {"used_mb": used_bytes // mb, "free_mb": free_bytes // mb, "total_mb": total_bytes // mb}
	except Exception:
		return None


@router.get("/status")
async def get_status():
	# Nao medir "/": no Bazzite a raiz e' composefs somente-leitura (~44MB, sempre 100%
	# ocupada). Medir VFX_DIR, que e' onde os arquivos sao de fato gravados.
	disk = shutil.disk_usage(VFX_DIR)
	return {
		"comfyui_up": await comfyui_up(),
		"vram": _vram_info(),
		"disk_free_gb": round(disk.free / (1024**3), 1),
		"disk_total_gb": round(disk.total / (1024**3), 1),
	}


@router.post("/comfyui/start")
async def start_comfyui():
	if await comfyui_up():
		return {"already_running": True}
	log_path = f"{VFX_DIR}/ai_pipeline/logs/comfyui_boot.log"
	os.makedirs(os.path.dirname(log_path), exist_ok=True)
	truncate_log_if_large(log_path)
	with open(log_path, "ab") as log_file:
		await asyncio.create_subprocess_exec(
			VFX_PY, "main.py", "--port", str(COMFYUI_PORT), "--listen", COMFYUI_HOST,
			cwd=COMFYUI_DIR, stdout=log_file, stderr=log_file, start_new_session=True,
		)
	return {"starting": True}


@router.post("/comfyui/stop")
async def stop_comfyui():
	proc = await asyncio.create_subprocess_exec(
		"fuser", "-k", f"{COMFYUI_PORT}/tcp",
		stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
	)
	await proc.wait()
	return {"stopped": True}
