import asyncio
import os
import shutil
import subprocess
from typing import Optional

import aiohttp
from fastapi import APIRouter

from config import COMFYUI_DIR, COMFYUI_HOST, COMFYUI_PORT, VFX_PY

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


def _vram_info() -> Optional[dict]:
	try:
		out = subprocess.check_output(
			["nvidia-smi", "--query-gpu=memory.used,memory.free,memory.total", "--format=csv,noheader,nounits"],
			text=True, timeout=5,
		)
		used, free, total = (int(x) for x in out.strip().splitlines()[0].split(","))
		return {"used_mb": used, "free_mb": free, "total_mb": total}
	except Exception:
		return None


@router.get("/status")
async def get_status():
	disk = shutil.disk_usage("/")
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
	log_path = "/home/ap/ai_pipeline/logs/comfyui_boot.log"
	os.makedirs(os.path.dirname(log_path), exist_ok=True)
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
