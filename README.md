# AP AI Studio

Repositório principal da arquitetura do "AP AI Studio". Este repositório contém a fundação (Prompt Architect) e o código fonte (em desenvolvimento) para orquestração assíncrona, segura e de alto desempenho de IA generativa em vídeo (ComfyUI e FaceFusion) num servidor Linux multi-tarefa.

---

## Como usar

Existem duas formas de usar o pipeline — escolha a que preferir, elas fazem exatamente a mesma coisa por baixo dos panos.

> 📖 Este README é um começo rápido. O **guia completo, didático, explicando cada
> conceito do zero** está em [`MANUAL_USO.md`](MANUAL_USO.md) — comece por lá se
> nunca usou nenhuma dessas ferramentas antes.

### Opção A — Interface web (mais fácil, sem terminal)

> ✅ **Já está ligada agora**, supervisionada pelo `systemd --user`
> (`vfx-web-enable`, confirmado em 2026-07-03) — sobrevive a crash e a reboot do
> servidor sem precisar religar na mão. Pule direto pro passo 2. O passo 1 só é
> necessário se você desligou (`vfx-web-disable`) e quer religar.

1. Ligue a interface — duas formas:
   ```bash
   vfx-web           # primeiro plano, fica preso ao terminal (Ctrl+C desliga)
   vfx-web-enable    # supervisionada (systemd --user): reinicia sozinha se cair
                      # ou se o servidor reiniciar; vfx-web-status/-disable controlam
   ```
   Na primeira vez ela builda o frontend sozinha (demora um pouco); nas próximas, sobe
   direto.
2. Abra no navegador: **`http://<ip-tailscale-do-servidor>:8299`** (funciona no navegador
   do próprio servidor ou de qualquer aparelho na sua rede Tailscale). Descubra o IP com
   `tailscale ip -4`; ele fica no seu `~/.config/ap-ai-studio/webui.env`, fora do git.
3. Navegue pelo menu no topo:
   - **Status** — vê se o ComfyUI está ligado, VRAM e disco livres.
   - **Gerar Vídeo** — texto→vídeo ou imagem→vídeo.
   - **Imagem ▾** — Trocar Rosto, Editar Imagem, Remover Fundo, Aumentar Resolução.
   - **Áudio ▾** — Voz (TTS/clonagem), Dublagem, Limpar Áudio, Música.
   - **Masterizar** — junta áudio/legendas originais com o vídeo processado.
4. Em qualquer página: preencha o formulário, marque **"Modo teste (--dry-run)"** se
   quiser só validar sem gastar GPU, e clique **Iniciar**. Um painel de log ao vivo
   mostra o progresso; quando terminar, o resultado aparece com preview e botão de
   baixar.

Detalhes completos (o que cada campo faz, limitações conhecidas) na seção 11 do
[`MANUAL_USO.md`](MANUAL_USO.md).

### Opção B — Terminal (atalhos `vfx-*`)

Os atalhos já ficam disponíveis em qualquer terminal novo (carregados via `~/.bashrc`).
Para ver a lista completa a qualquer momento:

```bash
vfx-ajuda
```

Exemplo — trocar o rosto de uma foto/vídeo:

```bash
vfx-rosto minha_foto.jpg cena_do_filme.mp4 resultado.mp4
```

Exemplo — gerar um vídeo do zero a partir de texto:

```bash
vfx-video "um dragão azul voando sobre um vale verde ao pôr do sol"
```

Cada atalho tem seus argumentos obrigatórios explicados no próprio `vfx-ajuda`, e
qualquer flag extra do `run_vfx.py` (`--dry-run`, `--chunk-seconds`, `--width` etc.)
pode ser adicionada no final do comando. Passo a passo de cada função (com exemplos
reais e o que cada flag faz) nas [seções 4 e 10 do MANUAL_USO.md](MANUAL_USO.md).

### O que esperar ao rodar algo

Antes de qualquer processamento pesado (troca de rosto, geração de vídeo etc.), três
"Gates" de segurança verificam memória, VRAM e espaço em disco — protegendo o Ollama e
o resto do servidor de travar. No terminal isso aparece como confirmações `[Y/n]`; na
interface web, um clique em "Iniciar" já cobre isso, e as decisões aparecem no log ao
vivo. Ver [seção 3 do MANUAL_USO.md](MANUAL_USO.md) para o detalhe de cada Gate.

---

## Estrutura do Repositório
- `PROMPT_MASTER.md`: O "código-fonte" lógico (Prompt Nível 10) que deve ser usado para inicializar a criação ou atualização da infraestrutura do estúdio pela IA.
- `MANUAL_USO.md`: Manual do usuário passo a passo (didático, para quem nunca usou o pipeline) — como rodar cada função (`--mode`) do `run_vfx.py`: troca de rosto, geração de vídeo, edição de imagem, clonagem de voz, dublagem, remoção de ruído, geração de música e masterização final.
- `vfx_aliases.sh`: atalhos de terminal (`vfx-rosto`, `vfx-video`, `vfx-ajuda` etc.), carregados automaticamente via `~/.bashrc` — ver seção 10 do `MANUAL_USO.md`.
- `requirements/`: dependências reprodutíveis (`pip freeze`) de cada ambiente Conda — ver `requirements/README.md` pra recriar qualquer um do zero. `CHANGELOG.md`: histórico de mudanças por data/versão. `LICENSE`: uso privado, todos os direitos reservados.
- `.github/workflows/test.yml`: CI no GitHub Actions. Roda de verdade (e tem que passar) o frontend inteiro e os testes dos scripts standalone — são portáveis. O resto de `test_run_vfx.py` roda como "melhor esforço" (pode falhar em runner sem GPU/ambientes Conda deste servidor — comentário no próprio arquivo explica por quê). `.pre-commit-config.yaml`: `ruff`/`eslint` só de lint (detecção de erro, sem reformatar) antes de cada commit — `pre-commit install` uma vez pra ativar.
- `run_vfx.py`: orquestrador principal (`orchestrate()`/`build_parser()`/`main()`) — 466 linhas, dividido em módulos por responsabilidade: `vfx_config.py` (constantes), `vfx_core.py` (validação/logging/confirm), `vfx_gates.py` (os 3 Gates de segurança), `vfx_comfyui.py` (comunicação com o ComfyUI), `vfx_workflows.py` (construtores de workflow, incluindo `--mode upscale`), `vfx_facefusion.py` (comandos externos), `vfx_ffmpeg.py` (FFmpeg/EXIF/chunking). `test_run_vfx.py` testa tudo isso via `run_vfx.py` (77 testes). `--mode upscale` amplia 4x uma foto/vídeo pronto (Real-ESRGAN, standalone, sem gerar nada novo) — ver seção 4.13 do `MANUAL_USO.md`. ControlNet Depth opcional no `--mode inpaint` (`--use-depth-controlnet`) e `--blocks-to-swap` avançado no `--mode video`.
- `tts_synthesize.py` / `demucs_separate.py`: scripts standalone chamados pelo `run_vfx.py` (modos `tts` e `denoise`), cada um no seu próprio ambiente Conda. `test_standalone_scripts.py` testa os dois via subprocesso real (6 testes).
- `webui/`: interface web (FastAPI + React/TypeScript/Tailwind/Bootstrap), acessível via
  Tailscale na porta `8299` — supervisionada pelo
  `systemd --user`** (`vfx-web-enable`, ativado em 2026-07-03; `vfx-web-status` mostra o
  estado). Todas as 11 funções do `run_vfx.py` (Fases A+B + upscale) — ver seção 11 do `MANUAL_USO.md`.
  `webui/backend/` (env Conda `webui-pipeline`, 44 testes em `test_backend.py`) chama
  `run_vfx.py` como subprocesso, mesma lógica dos atalhos `vfx-*` — não duplica a
  lógica dos Gates (exceção: dublagem chama o FaceFusion direto, igual ao atalho
  `vfx-dublar`). Também limita tamanho de upload (checado de verdade nos bytes
  gravados, não só no cabeçalho declarado) e checa espaço em disco antes de aceitar
  qualquer arquivo, e limpa jobs/uploads com mais de 7 dias automaticamente
  (`jobs.py:cleanup_old_jobs`). `webui/frontend/` (Vite, 48 testes via Vitest,
  incluindo processamento em lote em 3 páginas e mensagens de erro amigáveis):
  `npm run build`/`vfx-web-build` gera `webui/backend/static/`. `webui/vfx-webui.service`:
  unidade `systemd --user` que supervisiona a interface web (ativa, `vfx-web-status`
  mostra o estado; `vfx-web-disable` desliga). `webui/frontend/e2e/`: verificação
  visual manual com Chrome headless (fora do CI, ferramenta pra rodar quando quiser
  confirmar visualmente uma mudança de UI).

## Segurança

A interface web já passou por uma varredura dedicada de segurança (2026-07-03), que
encontrou e corrigiu uma falha real de leitura arbitrária de arquivo (path traversal na
rota que serve o frontend) e duas falhas menores de validação de entrada em upload —
todas confirmadas por exploração real contra o servidor rodando, e reexploradas depois
da correção pra confirmar que fecharam. Nenhuma delas dependia de autenticação: mesmo
com a barreira do Tailscale, qualquer dispositivo na tailnet conseguiria explorar. Log
técnico completo (payloads usados, causa raiz, correção) no `PROMPT_MASTER.md`.

---

## ⚠️ Troubleshooting (Problemas Possíveis e Soluções)

Guia de sobrevivência para os problemas que aparecem ao lidar com hardware, I/O e kernel ao mesmo tempo. Atualizado para **Bazzite (Fedora Kinoite, imutável/ostree)** e **AMD Radeon RX 9070 XT**.

### 1. `systemd-run` falha via SSH (Gate 1)
**Problema:** Ao rodar via SSH, o `systemd-run --user` retorna "Failed to connect to bus".
**Solução:** O `run_vfx.py` já cai automaticamente para o plano B (`resource.setrlimit`), então o pipeline não para. Para resolver de vez, o *linger* precisa estar ativo (`loginctl enable-linger apsrv` — **já está ativo nesta máquina**) e o DBus da sessão precisa estar visível no terminal remoto: `export DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus"`.

### 2. FFmpeg gerando "audio drift" (sincronia labial atrasada)
**Problema:** O vídeo final sai com o áudio adiantado ou atrasado em relação à imagem.
**Solução:** Acontece quando o original tem taxa de quadros variável (VFR), típico de celular, e foi processado como se fosse fixa. Trave os quadros antes:
`ffmpeg -i original.mp4 -r 24 -c:v libx264 -c:a copy cfr_original.mp4`

### 3. VRAM estourando (alerta no Gate 2)
**Problema:** O Gate 2 avisa que há menos de 15 GB de VRAM livres e o ComfyUI recusa renderizar.
**Solução:** Nesta máquina a GPU é compartilhada com o desktop KDE e o Steam — um jogo aberto, ou vários navegadores com aceleração, consomem VRAM em segundo plano. Para ver o consumo:
```bash
vfx-status                                          # já mostra VRAM e disco
cat /sys/class/drm/card*/device/mem_info_vram_used   # leitura crua, em bytes
```
Feche o jogo antes de renderizar. (Se o Ollama estiver instalado, o Gate 2 também oferece descarregar o modelo automaticamente; sem ele, essa etapa é ignorada em silêncio.)

### 4. Render lento com a GPU ociosa (gargalo de disco)
**Problema:** O render arrasta e a GPU fica com uso baixo.
**Solução:** O disco não acompanha a gravação dos frames. Confirme que a gravação intermediária usa formato compactado *lossless* (`-c:v ffv1`) em vez de PNGs crus, que saturam a banda do disco.

### 5. Erro de plugin Qt/Wayland (sem monitor)
**Problema:** "Could not load the Qt platform plugin wayland" e o script aborta.
**Solução:** Bibliotecas como o OpenCV tentam abrir uma janela e não encontram tela — comum em sessão SSH. Force o modo headless: `export QT_QPA_PLATFORM=offscreen`.

### 6. FFmpeg falha com "Function not implemented" no encoder
**Problema:** A masterização quebra ao usar `h264_vaapi`.
**Solução:** VAAPI exige inicializar o dispositivo e subir os frames para a GPU — não basta trocar o nome do codec. O `build_ffmpeg_mastering_command` já monta isso (`-vaapi_device` + `format=nv12,hwupload`). Se persistir, confirme que o dispositivo existe e que o encoder está disponível:
```bash
ls -la /dev/dri/renderD128
vainfo | grep -i encslice
```
Alternativa: passar `video_codec="libx264"` desliga o caminho de hardware e volta para CPU — mais lento, qualidade melhor a mesmo bitrate.

### 7. Pipeline aborta com "espaço insuficiente" tendo disco sobrando
**Problema:** O Gate 3 recusa executar alegando disco cheio, mas `df -h` mostra centenas de GB livres.
**Solução:** Sintoma clássico de medir o caminho errado no ostree. A raiz `/` é **composefs somente-leitura** (~44 MB, 100% ocupada por definição) — medir ali sempre devolve zero. O código mede `DISK_CHECK_PATH` (padrão: `AP_AI_STUDIO_HOME`). Se você sobrescreveu essa variável, aponte-a para um diretório dentro de `/var/home`.

### 6. Interface web recusa o upload (HTTP 413 ou 507)
**Problema:** Ao enviar um arquivo pela interface web, a resposta vem com erro em vez de criar o job.
**Solução:** `413` = arquivo maior que o limite de 4GB (`MAX_UPLOAD_BYTES` em `webui/backend/config.py`) — normal pra vídeos muito longos, considere usar `--chunk-seconds` pelo terminal em vez da interface pra esses casos. `507` = disco já está abaixo da margem de segurança de 30GB antes mesmo do upload começar — libere espaço (`vfx-status` ou a aba Status da webui mostram o espaço livre) antes de tentar de novo.
