# Dependências por ambiente Conda

Achado de auditoria (2026-07-03): nenhum dos 5 ambientes Conda deste projeto tinha um
arquivo de dependências reprodutível — recriar qualquer um exigia garimpar comandos
`pip install` espalhados em prosa no `PROMPT_MASTER.md`. Estes arquivos são a saída
real de `pip list --format=freeze` de cada ambiente, gerados em 2026-07-03 (Python
3.11.15 em todos).

| Ambiente | Arquivo | Usado por |
|---|---|---|
| `vfx-pipeline` | `vfx-pipeline.txt` | `run_vfx.py`, ComfyUI |
| `facefusion-pipeline` | `facefusion-pipeline.txt` | FaceFusion |
| `tts-pipeline` | `tts-pipeline.txt` | `tts_synthesize.py` (XTTS-v2) |
| `noise-pipeline` | `noise-pipeline.txt` | `demucs_separate.py` (Demucs) |
| `webui-pipeline` | `../webui/backend/requirements.txt` | `webui/backend/` (FastAPI) |

## Como recriar um ambiente do zero

```bash
conda create -n <nome-do-ambiente> python=3.11 -y
conda activate <nome-do-ambiente>
pip install -r requirements/<nome-do-ambiente>.txt
```

**Atenção:** estes arquivos são um `pip freeze` puro — centenas de pacotes com versão
exata, incluindo transitivos (ex.: `vfx-pipeline.txt` tem ~190 linhas por causa do
`torch`/CUDA). Isso é proposital: garante reprodução byte-a-byte do ambiente que foi
validado de verdade neste servidor, não uma lista mínima "capa" que poderia resolver
pra versões diferentes das testadas. Se algum pacote falhar ao instalar em outra
máquina (driver de GPU diferente, arquitetura diferente), ver os "achados reais"
específicos de cada ambiente no `PROMPT_MASTER.md` (Fases 1, 8, 9) — várias
incompatibilidades de versão já foram encontradas e documentadas lá.

Ambientes são descartáveis por design (`conda env remove -n <nome>` e recriar do zero
não afeta o resto do sistema) — ver Fase 1 do `PROMPT_MASTER.md`.

## Ferramentas de lint/tipo vivem só no `webui-pipeline` (achado de auditoria SO/DevOps)

`bandit`, `pre-commit` e `mypy` (usados pelo CI/lint local, não pelo pipeline em si)
estão instalados **somente** no ambiente `webui-pipeline`, não nos outros 4. Isso é
proposital (evita inflar os ambientes de produção com tooling de desenvolvimento), mas
significa que se o `webui-pipeline` for removido/recriado sem reinstalar essas três
ferramentas, o lint local (`pre-commit run --all-files`) para de funcionar
silenciosamente na próxima vez que alguém tentar rodar. Se isso acontecer:

```bash
conda activate webui-pipeline
pip install pre-commit bandit mypy
```

(`ruff` e `eslint` **não** dependem disso — o hook `ruff-check` usa o repositório
hospedado `astral-sh/ruff-pre-commit`, que gerencia seu próprio venv isolado, e o
`eslint` já vive dentro de `webui/frontend/node_modules`.)
