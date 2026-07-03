"""Script standalone rodado dentro do ambiente Conda 'tts-pipeline' (isolado do vfx-pipeline
e do facefusion-pipeline por causa do conflito real de versao do 'transformers' - ver
PROMPT_MASTER.md Fase 8). Nao e um node de ComfyUI de proposito: coqui-tts precisa de
transformers==4.57.6, incompativel com o que o WanVideoWrapper exige no mesmo processo.
"""

import argparse
import os
import sys

os.environ.setdefault("COQUI_TOS_AGREED", "1")


def main() -> int:
	parser = argparse.ArgumentParser(description="Sintese/clonagem de voz via XTTS-v2")
	parser.add_argument("--text", required=True)
	parser.add_argument("--output", required=True)
	parser.add_argument("--language", default="pt")
	parser.add_argument("--speaker", default=None, help="Nome de um dos speakers embutidos do XTTS-v2")
	parser.add_argument("--speaker-wav", default=None, help="Caminho de audio de referencia para clonar a voz")
	args = parser.parse_args()

	if not args.speaker and not args.speaker_wav:
		print("Erro: informe --speaker (voz embutida) ou --speaker-wav (clonar de uma amostra)", file=sys.stderr)
		return 1

	from TTS.api import TTS

	tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2")
	tts.tts_to_file(
		text=args.text,
		language=args.language,
		speaker=args.speaker,
		speaker_wav=args.speaker_wav,
		file_path=args.output,
	)
	print(f"Audio gerado: {args.output}")
	return 0


if __name__ == "__main__":
	sys.exit(main())
