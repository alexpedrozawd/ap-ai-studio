"""Utilitarios pequenos e sem estado, compartilhados entre os modulos do backend."""

import os

LOG_TRUNCATE_THRESHOLD_BYTES = 5 * 1024 * 1024


def truncate_log_if_large(log_path: str, threshold_bytes: int = LOG_TRUNCATE_THRESHOLD_BYTES) -> None:
	"""Log cru de boot do ComfyUI (redirecionamento de stdout/stderr de subprocesso, nao
	um logging.Logger) - sem rotacao, cresce pra sempre. Truncamento simples e' suficiente
	pra um log de diagnostico de boot (mesma logica usada em run_vfx.py, copia deliberada
	- ver config.py sobre por que os dois modulos nao compartilham codigo)."""
	try:
		if os.path.isfile(log_path) and os.path.getsize(log_path) > threshold_bytes:
			open(log_path, "w").close()
	except OSError:
		pass
