"""Achado de auditoria: tts_synthesize.py e demucs_separate.py (os dois scripts
standalone chamados pelo run_vfx.py em ambientes Conda proprios) nao tinham nenhum
teste que os executasse de verdade - so' havia testes checando que run_vfx.py monta o
comando certo pra chamar-los (build_tts_command/build_demucs_command).

Os dois scripts importam suas dependencias pesadas (TTS, demucs) DENTRO de main(),
depois de qualquer validacao de argumento - de proposito, isso permite testar a
validacao de argumentos de verdade (via subprocesso real, nao mock) rodando com
QUALQUER interprete Python, sem precisar do ambiente Conda pesado (tts-pipeline/
noise-pipeline) nem de GPU. So' testamos o que e' alcancavel sem essas dependencias;
a geracao de audio de verdade continua validada manualmente (ver PROMPT_MASTER.md
Fases 8/9) - reproduzir isso automaticamente exigiria os modelos e a GPU disponiveis
no ambiente de teste, o que este projeto nao tem hoje."""

import subprocess
import sys
import os

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
TTS_SCRIPT = os.path.join(REPO_DIR, "tts_synthesize.py")
DEMUCS_SCRIPT = os.path.join(REPO_DIR, "demucs_separate.py")


def _run(script: str, args: list[str]) -> subprocess.CompletedProcess:
	return subprocess.run(
		[sys.executable, script, *args],
		capture_output=True, text=True, timeout=10,
	)


def test_tts_synthesize_rejects_missing_text_argument():
	result = _run(TTS_SCRIPT, ["--output", "/tmp/nao_gerado.wav"])
	assert result.returncode == 2  # argparse: argumento obrigatorio faltando
	assert "--text" in result.stderr


def test_tts_synthesize_rejects_missing_output_argument():
	result = _run(TTS_SCRIPT, ["--text", "ola"])
	assert result.returncode == 2
	assert "--output" in result.stderr


def test_tts_synthesize_requires_speaker_or_speaker_wav():
	"""Validacao real do script (nao do run_vfx.py) - roda antes do 'from TTS.api import
	TTS', entao nao precisa do pacote TTS instalado pra testar isso de verdade."""
	result = _run(TTS_SCRIPT, ["--text", "ola", "--output", "/tmp/nao_gerado.wav"])
	assert result.returncode == 1
	assert "speaker" in result.stderr.lower()


def test_demucs_separate_rejects_missing_input_argument():
	result = _run(DEMUCS_SCRIPT, ["--output-vocals", "/tmp/nao_gerado.wav"])
	assert result.returncode == 2
	assert "--input" in result.stderr


def test_demucs_separate_rejects_missing_output_vocals_argument():
	result = _run(DEMUCS_SCRIPT, ["--input", "/tmp/entrada.wav"])
	assert result.returncode == 2
	assert "--output-vocals" in result.stderr


def test_demucs_separate_model_argument_is_optional():
	"""--model tem valor default - omitir nao deveria falhar no parsing de argumentos.
	O comando ainda falha logo depois (tentando importar demucs.separate ou abrir um
	arquivo de entrada inexistente) - isso e' esperado, so' confirmamos que a falha nao
	e' por causa de --model faltando (returncode 2 seria erro do argparse)."""
	result = _run(DEMUCS_SCRIPT, ["--input", "/tmp/entrada_nao_existe.wav", "--output-vocals", "/tmp/saida.wav"])
	assert result.returncode != 2
	assert "--model" not in result.stderr
