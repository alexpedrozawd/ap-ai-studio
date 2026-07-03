"""Script standalone rodado dentro do ambiente Conda 'noise-pipeline'. Isolado por seguranca/
consistencia (mesmo padrao do FaceFusion e do TTS) - nao porque demucs por si so tenha
conflito de dependencia com os outros, mas pra nao arriscar puxar uma versao de torch pro
vfx-pipeline que quebre o WanVideoWrapper.
"""

import argparse
import os
import shutil
import sys


def main() -> int:
	parser = argparse.ArgumentParser(description="Isola voz/remove ruido de fundo via Demucs")
	parser.add_argument("--input", required=True)
	parser.add_argument("--output-vocals", required=True, help="Caminho de saida para a voz isolada")
	parser.add_argument("--output-instrumental", default=None, help="Caminho de saida para o resto (ruido/musica/fundo)")
	parser.add_argument("--model", default="htdemucs")
	args = parser.parse_args()

	work_dir = os.path.join(os.path.dirname(os.path.abspath(args.output_vocals)), ".demucs_tmp")
	os.makedirs(work_dir, exist_ok=True)

	from demucs.separate import main as demucs_main

	demucs_main(["--two-stems=vocals", "-n", args.model, "-o", work_dir, args.input])

	basename = os.path.splitext(os.path.basename(args.input))[0]
	vocals_path = os.path.join(work_dir, args.model, basename, "vocals.wav")
	instrumental_path = os.path.join(work_dir, args.model, basename, "no_vocals.wav")

	shutil.copy(vocals_path, args.output_vocals)
	if args.output_instrumental:
		shutil.copy(instrumental_path, args.output_instrumental)

	print(f"Voz isolada: {args.output_vocals}")
	return 0


if __name__ == "__main__":
	sys.exit(main())
