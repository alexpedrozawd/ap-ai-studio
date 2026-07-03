# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).
Este arquivo registra **o quê e quando** de forma escaneável — a razão de cada mudança
(os "achados reais", causa raiz, decisões de arquitetura) continua documentada em
detalhe no [`PROMPT_MASTER.md`](PROMPT_MASTER.md), que este changelog não substitui.

## [Não lançado]

Trabalho já feito nesta sessão, ainda não commitado (aguardando confirmação do
usuário, conforme combinado).

### Corrigido
- **Gate 1 (jaula de memória) não era aplicado ao ComfyUI nos modos `inpaint`, `music`
  e `upscale`** — achado real de auditoria final: só o modo `video` chamava
  `ensure_comfyui_running_under_jail()`; os outros 3 só chamavam
  `poll_comfyui_system_stats()` (que so' espera o ComfyUI responder, sem garantir
  nenhuma jaula). Se o ComfyUI tivesse sido ligado pela webui (`POST
  /api/comfyui/start`, subprocesso sem jaula), esses 3 modos rodavam sem proteção
  nenhuma contra OOM no servidor inteiro. Confirmado ao vivo antes da correção
  (`systemctl status` mostrava o ComfyUI aninhado no cgroup do `vfx-webui.service`, não
  num scope próprio) e depois (religado sozinho em `vfx-comfyui-video.scope` com
  `MemoryMax` real aplicado, na primeira chamada de `--mode upscale`). 3 testes novos
  confirmando que os 3 modos chamam a jaula, não só o poll.
- **Job "fantasma"** em uploads de múltiplos arquivos (`faceswap`, `inpaint`, `master`,
  `dub`) e de arquivo único (`tts`, `denoise`, `removebg`, `video`): se um upload
  falhasse depois de outro já ter sido salvo, o job ficava preso em `queued` pra
  sempre e o arquivo já salvo ficava órfão em disco. Nova `save_uploads()` desfaz o
  job inteiro se qualquer upload falhar.
- `routes_tts.py` chamava `set_output()` antes dos uploads (ordem invertida das outras
  7 rotas) — deixava pasta de saída órfã em caso de falha. Ordem corrigida.
- `save_upload()`: cleanup de arquivo parcial ampliado pra qualquer exceção (não só
  `HTTPException`), e `upload.close()` garantido via `finally`.
- `nvidia-smi` chamado por caminho parcial (dependente do `PATH`) em `run_vfx.py` e
  `webui/backend/routes_status.py` — achado real do SAST (`bandit` B607), corrigido
  pro caminho absoluto `/usr/bin/nvidia-smi`.
- 1 warning do ESLint (`eslint-disable` órfão em `ComfyUINotice.tsx`).
- `RemoveBgPage.tsx` sempre renderizava o resultado como `<img>`, mesmo quando o alvo
  enviado era vídeo (a página aceita `image/*,video/*`) — corrigido ao adicionar a
  comparação antes/depois, que precisa detectar o tipo corretamente pra funcionar.
- `vfx_ffmpeg.py::process_long_faceswap`, `webui/backend/jobs.py::_run`,
  `webui/backend/routes_jobs.py::get_job` — 4 achados do `mypy` recém-adicionado
  (narrowing de tipo `Optional`), nenhum bug ativo (a condição de `None` nunca
  acontecia na prática), mas fecham um ponto que poderia quebrar silenciosamente numa
  refatoração futura.
- Contagem de falsos-positivos do `bandit` citada errado em auditorias anteriores
  (`AUDITORIA_2026-07-03_FINAL.md`/`_REVISAO2.md` diziam "3", o real sempre foi 34 —
  efeito de `tail` cortando a saída antes da contagem) — corrigido em
  `AUDITORIA_2026-07-03_REVISAO3.md`, sem mudança no veredito (0 issues reais em
  código de produção nas duas contagens).
- Nota anterior neste changelog/`PROMPT_MASTER.md` de que o block swap do Wan2.2
  existiria "principalmente por causa do Ollama" — incorreta. Os dois experts MoE
  (HighNoise+LowNoise) somam ~19.3GB sozinhos, mais que os 16GB da GPU, então o
  offload é obrigatório mesmo com a VRAM inteira livre (Ollama fechado ou não).

### Adicionado
- `LICENSE` (uso privado, todos os direitos reservados).
- `requirements/` — dependências reprodutíveis (`pip freeze`) dos 5 ambientes Conda,
  mais `webui/backend/requirements.txt`.
- Este `CHANGELOG.md`.
- Validação de assinatura real do arquivo no upload (`filetype`) — rejeita com
  mensagem amigável qualquer arquivo que não seja reconhecido como imagem/vídeo/áudio
  pelo conteúdo real dos bytes, não só pelo nome/extensão declarados.
- `.github/workflows/test.yml` (CI) e `.pre-commit-config.yaml` (lint local antes de
  cada commit, `ruff` + `eslint`, sem reformatar).
- **`--mode upscale`** (`run_vfx.py`): aumenta resolução 4x de foto/vídeo pronto,
  reaproveitando o `RealESRGAN_x4plus.pth` já instalado (`ImageUpscaleWithModel`/
  `UpscaleModelLoader` do ComfyUI; vídeo via `VHS_LoadVideo`/`VHS_VideoCombine`).
  Standalone — não gera nada novo, só amplia o que já existe. Exposto na webui
  (`POST /api/jobs/upscale`, página "Aumentar Resolução"). Testado ao vivo pela CLI
  (1024×1024 → 4096×4096) e pela webui em produção (256×256 → 1024×1024, job real
  sem `--dry-run`).
- Comparação antes/depois na interface web (`BeforeAfterCompare.tsx`), lado a lado,
  nas páginas que editam algo já existente (Trocar Rosto, Remover Fundo, Editar
  Imagem, Aumentar Resolução) — não faz sentido em geração do zero (Gerar Vídeo,
  Música), onde não há "antes".
- Aviso "modo rascunho, não produção" na página "Gerar Vídeo" da webui, explicando o
  teto de resolução/duração e apontando pra "Trocar Rosto"/"Aumentar Resolução" quando
  o objetivo é qualidade de entrega final.
- Testes de frontend cobrindo o estado "job concluído" (`output_ready: true`), antes
  sem cobertura em nenhuma página: `BeforeAfterCompare.test.tsx` (4 testes) +
  `RemoveBgPage.test.tsx`/`InpaintPage.test.tsx`/`UpscalePage.test.tsx` (novos) +
  2 testes novos em `FaceSwapPage.test.tsx`. Suíte de frontend foi de 7 para 21 testes.
  Exigiu um polyfill de `URL.createObjectURL`/`revokeObjectURL` em `src/test/setup.ts`
  (jsdom não implementa essa API).
- `mypy` em modo leve (`--ignore-missing-imports`, hook `pre-commit` não-bloqueante) —
  achado de auditoria (sugestão "checagem de tipo leve"). Achou e permitiu corrigir 4
  pontos reais de tipo (`vfx_ffmpeg.py`, `webui/backend/jobs.py`,
  `webui/backend/routes_jobs.py`) onde o código dependia de uma garantia de runtime
  (`Optional` que nunca é `None` na prática) sem provar isso pro type checker.
- Seção nova em `requirements/README.md` documentando que `bandit`/`pre-commit`/`mypy`
  vivem só no `webui-pipeline`, não nos outros 4 ambientes Conda — achado de auditoria
  SO/DevOps.
- `webui/frontend/e2e/` — formaliza a verificação visual manual (Chrome headless real,
  não mockado) que antes era um script descartável. Roda rotas estáticas + um fluxo
  real de upscale de ponta a ponta, limpa o job de teste sozinho. Deliberadamente fora
  do CI/pre-commit — ferramenta manual, não um teste automatizado.
- `src/lib/friendlyErrors.ts` — traduz os erros técnicos mais comuns (Gates 1/2/3,
  OOM-kill código 137, timeout do ComfyUI, erro de execução do ComfyUI) pra uma frase
  simples em português, mostrada acima do log técnico (que continua visível por
  completo) quando um job termina com erro. Achado de auditoria (perfil de uso
  profissional/iniciante).
- **`friendlyErrors.ts` estendido pras outras funções do pipeline** — antes só cobria
  cenários ligados ao ComfyUI/Gates; agora também reconhece falha do FaceFusion (troca
  de rosto), remoção de fundo, TTS, Demucs (limpar áudio), FFmpeg (masterização) e
  modelo/arquivo ausente (`FileNotFoundError` de `.safetensors`/`.pth`/etc.). Padrões
  baseados no formato exato dos logs reais (`"{ferramenta} falhou (codigo N): ..."`,
  confirmado via grep no `run_vfx.py`), não inventados. 7 testes novos.
- **Processamento em lote** (`BatchJobQueue.tsx`) nas páginas "Aumentar Resolução" e
  "Remover Fundo" — selecionar mais de um arquivo no mesmo campo processa em fila
  sequencial (não paralelo, de propósito: a GPU é compartilhada com o Ollama e não há
  limite de concorrência entre jobs). Cada arquivo mostra seu próprio status/log/
  antes-depois/download. Fluxo de um único arquivo continua idêntico a antes (o modo
  lote só ativa quando mais de um arquivo é selecionado). Achado de auditoria (perfil
  de uso profissional) — testado ao vivo com 2 arquivos reais pela webui em produção,
  confirmado que o 2º job só começa depois do 1º terminar.
- **Processamento em lote estendido** pra "Trocar Rosto" (mesma foto de origem, vários
  alvos) e "Limpar Áudio" (vários áudios, com o mesmo player/download de voz isolada +
  resto opcional). `BatchJobQueue.tsx` generalizado: em vez de assumir sempre imagem/
  vídeo com antes-depois, agora recebe uma função `renderResult` de cada página — o
  componente só cuida da fila, cada página decide como mostrar seu próprio resultado
  (antes/depois de imagem, player de áudio, etc.). Verificado ao vivo: 2 jobs reais de
  Trocar Rosto com a mesma origem e alvos diferentes, sequenciais, ambos concluídos.
- `--blocks-to-swap` (avançado, opcional) no modo `video` — permite acelerar o render
  reduzindo o padrão (`20`) por sua conta e risco. Medido ao vivo: `5` rende ~33-38%
  mais rápido e é seguro até ~80 quadros em 480×480, mas travou o ComfyUI com OOM real
  nos 161 quadros padrão na mesma resolução — por isso o padrão **não** mudou, só foi
  exposta a opção avançada. Detalhes completos (tabela de medições) no
  `PROMPT_MASTER.md`.
- **ControlNet Depth no modo `inpaint`** (`--use-depth-controlnet`, opcional) — guia a
  edição por um mapa de profundidade (MiDaS) da própria imagem original, via ControlNet
  SDXL, além da máscara manual. Requer o pacote de nós `comfyui_controlnet_aux`
  (instalado, repositório nomeado e autorizado explicitamente pelo usuário) e o modelo
  `controlnet-depth-sdxl-1.0.safetensors` (2,4GB). Desligado por padrão — sem a flag, o
  workflow de inpaint fica idêntico ao de antes. Também disponível na webui (checkbox
  "Avançado" em "Editar Imagem"). Testado ao vivo, CLI e webui, ambos com sucesso.

### Corrigido
- **Costura visível na borda da máscara do modo `inpaint`** (achado real de um teste
  com ControlNet) — duas causas corrigidas: borda de máscara suavizada (`FeatherMask`,
  `feather_amount=24` por padrão) e o resultado gerado agora é colado de volta na
  **imagem original** (`ImageCompositeMasked`), não na imagem inteira redecodificada
  pelo VAE. Verificado com números: diferença de pixel numa região fora da máscara
  caiu de uma deriva real (porém pequena) pra **0.0**. Sempre ativo, sem flag — é
  correção de qualidade, não recurso opcional. Ambos os nodes já existem no ComfyUI
  core, nenhuma dependência nova.

### Alterado
- `run_vfx.py` (~1500 linhas) dividido em 7 módulos por responsabilidade:
  `vfx_config.py` (constantes), `vfx_core.py` (validação/logging/confirm), `vfx_gates.py`
  (os 3 Gates), `vfx_comfyui.py` (comunicação HTTP com o ComfyUI), `vfx_workflows.py`
  (construtores de workflow), `vfx_facefusion.py` (comandos externos) e `vfx_ffmpeg.py`
  (FFmpeg/EXIF/chunking). `run_vfx.py` caiu pra 405 linhas — vira só o orquestrador
  (`orchestrate()`/`build_parser()`/`main()`), reexportando tudo dos módulos pra
  `from run_vfx import X` continuar funcionando sem mudança em quem já consome
  (atalhos `vfx-*`, webui, `test_run_vfx.py`). Verificado com os 62 testes existentes
  passando sem alteração de comportamento, e um job real (`removebg`) de ponta a ponta
  pela API depois da divisão.
- `webui/backend/requirements.txt` regenerado (`pip freeze` real do `webui-pipeline`,
  44→60 pacotes) — refletia um estado anterior à instalação do `mypy`/`pre-commit`.

## [2026-07-03] — Auditoria de sistema, supervisão systemd, segurança

Commit `91584da`.

### Adicionado
- `webui/vfx-webui.service` (`systemd --user`): supervisão automática da interface
  web, ativada em produção (`vfx-web-enable`/`-disable`/`-status`), testada com
  `kill -9` ao vivo.
- Limite de tamanho de upload (4GB) e checagem de espaço em disco *antes* de aceitar
  arquivo, via middleware em `main.py`.
- Limpeza automática de jobs/uploads com mais de 7 dias (`jobs.py:cleanup_old_jobs`).
- Rotação de log (`run_vfx.log`) e truncamento dos logs de boot do ComfyUI.
- `test_standalone_scripts.py` (6 testes reais via subprocesso, sem precisar de GPU).
- Suíte de testes do frontend (Vitest + React Testing Library, 7 testes).

### Corrigido
- **Crítico**: path traversal na rota catch-all da SPA (`main.py`) permitia ler
  qualquer arquivo do servidor — confirmado ao vivo lendo `/etc/passwd` de verdade,
  corrigido com `os.path.realpath()` + contenção via `os.path.commonpath()`.
- Limite de upload contornável com `Transfer-Encoding: chunked` — corrigido contando
  bytes reais durante a gravação.
- Crash 500 não tratado com filename `"."`/`".."` — corrigido com validação (400).
- Duplicação nas 9 rotas de job — extraído `finish()`/`set_output()`/`save_upload()`.
- `PROMPT_MASTER.md` desatualizado (contagem de testes, pendência de commit falsa).

## [2026-07-02] — Interface web e Fases 5-10

Commits `b4550bd`, `35dc3d0`.

### Adicionado
- Fases 5-10 do `run_vfx.py`: imagem→vídeo (I2V), inpainting, processamento de vídeo
  longo em pedaços, TTS/clonagem de voz, remoção de ruído (Demucs), geração de música
  (MusicGen).
- `vfx_aliases.sh`: atalhos de terminal (`vfx-rosto`, `vfx-video`, `vfx-ajuda` etc.).
- `webui/`: interface web completa (FastAPI + React/TypeScript/Tailwind/Bootstrap),
  cobrindo as 10 funções do pipeline.
- `MANUAL_USO.md`: manual do usuário didático.
- `tts_synthesize.py`, `demucs_separate.py`: scripts standalone.

## [2026-07-02] — Núcleo do orquestrador (Fases 1-4)

Commit `00e41fb`.

### Adicionado
- `run_vfx.py`: gates de segurança (memória, VRAM, disco), integração com FaceFusion
  (troca de rosto), Wan2.2 (geração de vídeo T2V), masterização final com FFmpeg.
- `test_run_vfx.py`: suíte de testes inicial.

## [2026-06-25] — Commit inicial

Commit `c56af75`.

### Adicionado
- `PROMPT_MASTER.md` e `README.md` — fundação do projeto (Fase 0, arquitetura lógica).
