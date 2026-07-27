# Handoff para continuação autônoma — 2026-07-27

Documento de resgate para os wakeups encadeados. Se o contexto da conversa for
comprimido ou perdido entre um wakeup e outro, **este arquivo é a fonte da verdade**
sobre o que já foi feito e o que falta. Leia-o inteiro antes de agir.

## Teste do mecanismo de wakeup

- Agendado às ~00:38:10, disparou às **2026-07-27 00:40:04 -03** (delay pedido: 60s).
  Mecanismo confirmado funcional. A cadeia real de ~4h foi configurada em seguida.

## Regra de ouro desta sessão (gravada no CLAUDE.md global)

Antes de qualquer trabalho: agir como full stack sênior + arquiteto sênior + QA sênior
+ cybersec sênior, todos críticos do próprio trabalho. **Rodar de verdade vale mais que
ler** — vários dos piores bugs desta migração (VRAM_DIR sem import, IP hardcoded,
requirements com `pip freeze` de ambiente quebrado) só apareceram executando, nunca
lendo. Nunca declarar algo "pronto" sem ter executado.

## Estado no momento da pausa (2026-07-27, ~00:40)

### Já concluído e verificado (não refazer)
- Migração completa Ubuntu/NVIDIA → Bazzite/AMD RX 9070 XT (ROCm 7.13, gfx1201)
- Todos os caminhos consolidados em `Projetos/ap-ai-studio` — `~/ap-ai-studio` apagado
- Webui no ar via `systemd --user` (`vfx-webui.service`, enabled), testada com kill -9 (religa em 14s)
- 185 testes automatizados passando: `test_run_vfx` 87/87, `test_standalone` 6/6, `test_backend` 44/44, frontend Vitest 48/48
- **Render de vídeo real testado com sucesso**: Wan2.2, 17 frames/320x320 (upscale automático 4x → 1280x1280), sem OOM. Pico de VRAM medido: **9,57 GiB** (amostra pequena, não representativa de render grande — NÃO recalibrar `VRAM_PEAK_ALERT_GB` só com esse dado)
- Playwright instalado no contêiner (Node 24 LTS), `capture.mjs` criado e testado ao vivo contra a webui (screenshot de `/` e `/video`, leitura de texto confirmadas)
- Hook `~/.claude/hooks/bloqueia-pull-arvore-suja.sh` protegendo contra `git pull` em árvore suja (com exceções para `--autostash` e `git stash && pull`)
- Todo o trabalho até aqui está commitado e empurrado para `origin/main`

### Regra do usuário (2026-07-27, antes da pausa): NUNCA parar por decisão dele
Se durante a execução autônoma aparecer algo que só o usuário pode decidir: **não parar,
não esperar resposta**. Anotar a decisão pendente na seção abaixo (com contexto e a
recomendação), tomar o caminho mais seguro/reversível para continuar, e seguir
trabalhando. Perguntar tudo de uma vez só no resumo final, quando ele voltar.

### Decisões pendentes do usuário — anotar aqui, NÃO parar para perguntar
1. **Node do MusicGen** — upstream removido do GitHub, só resta fork de 10 estrelas
   (`ebrinz/ComfyUI-MusicGen-HF`, confirmado registrar as classes certas). Meu critério:
   mesmo padrão que o próprio projeto já usou para recusar código não-oficial
   (`vfx_facefusion.py`, sobre o build alternativo do onnxruntime). NÃO instalar sozinho.
   `--mode music` fica indisponível/pulado nos testes até decisão.
2. **`tailscale0` na zona `trusted` do firewalld** — exige root/senha, que esta sessão
   não tem. Sem isso, quando o usuário aplicar o hardening do `security-audit`, a webui
   ficaria inacessível via Tailscale. Fica documentado, sem ação possível daqui.
   <!-- Novas decisões pendentes encontradas durante a execução autônoma: adicionar aqui -->

### O que FALTA testar de verdade (é o trabalho dos próximos wakeups)

Nenhum destes modos foi executado de ponta a ponta ainda. Testar cada um é o que resta
para "tudo estar pronto":

- [ ] **faceswap** (`--mode faceswap`) — FaceFusion nunca rodou de fato nesta migração, só o ambiente foi criado. Usar assets de exemplo oficiais do próprio FaceFusion (`facefusion/facefusion-assets` no GitHub — já usado como precedente no `PROMPT_MASTER.md`, não são fotos de pessoas reais). NÃO usar fotos reais de pessoas por privacidade.
- [ ] **inpaint** (`--mode inpaint`) — SDXL, ComfyUI. Testar com e sem `--use-depth-controlnet`.
- [ ] **removebg** (`--mode removebg`) — FaceFusion background_remover.
- [ ] **tts** (`--mode tts`) — XTTS-v2, ambiente `tts-pipeline`. Nunca invocado.
- [ ] **dublagem** (`vfx-dublar` / lip_syncer via FaceFusion direto) — CPU, decisão já tomada.
- [ ] **denoise** (`--mode denoise`) — Demucs, ambiente `noise-pipeline`. Nunca invocado.
- [ ] **upscale --upscale-method lanczos** — ffmpeg puro, deveria ser trivial.
- [ ] **upscale --upscale-method realesrgan** — ComfyUI/GPU.
- [ ] **master** (`--mode master`) — remuxagem ffmpeg/VAAPI. JÁ testado indiretamente pelo render de vídeo (o modo video não passa por master, então isto ainda não foi validado isoladamente).
- [ ] **Comparar VAAPI vs libx264** de verdade num output de master (ver `vfx_ffmpeg.py` — `video_codec="libx264"` como alternativa).
- [ ] **Render de vídeo em tamanho real** (161 frames, até 720x720) para medir o pico de VRAM de verdade e SÓ ENTÃO recalibrar `VRAM_PEAK_ALERT_GB` em `vfx_config.py` — hoje é 15GB e dispara alerta quase sempre porque o desktop já usa 2,5GB em repouso.
- [ ] Rodar `pytest` de novo depois de qualquer mudança de código.
- [ ] Se qualquer modo falhar: **investigar a causa raiz, corrigir, documentar em `MIGRACAO_BAZZITE.md`, e SÓ DEPOIS seguir** para o próximo modo. Não pular falha para "ver o resto".

### Como testar cada modo (padrão usado no render de vídeo que já funcionou)

O Gate 3 exige confirmação interativa mesmo com `--auto-approve`. Alimentar stdin com "y":

```bash
distrobox enter ai-studio -- bash -c '
R=/var/home/apsrv/Projetos/ap-ai-studio
printf "y\ny\ny\ny\ny\n" | $R/miniconda3/envs/vfx-pipeline/bin/python run_vfx.py \
  --mode <MODO> [args] --auto-approve 2>&1'
```

Rodar como `systemd-run --user --unit=ai-studio-teste-<modo> --collect` para sobreviver
a qualquer desconexão, exatamente como todo o resto desta sessão.

**Limpar arquivos de teste depois** (`ai_pipeline/tmp/`, saídas geradas) — não deixar
lixo nem commitar mídia gerada (o `.gitignore` já bloqueia extensões de mídia, mas
verificar mesmo assim).

## Regra de execução para os próximos wakeups

1. Ler este arquivo inteiro primeiro.
2. Pegar o próximo item não marcado da lista de "falta testar".
3. Executar de verdade, registrar o resultado (sucesso ou falha + causa) NESTE arquivo,
   marcando `[x]`.
4. Se achar bug: corrigir, testar a correção, commitar com mensagem explicando causa raiz
   (mesmo padrão dos commits já feitos nesta sessão — "o quê" + "por quê" + "como foi
   verificado").
5. Nunca declarar sucesso sem ter executado e visto o resultado.
6. Ao fim de cada wakeup de ~1h: commitar o progresso, atualizar este arquivo, e se ainda
   não chegou nas 4h totais, o próprio wakeup já está configurado para se repetir.
7. Quando todos os itens estiverem marcados (ou bloqueados e documentados como tal): parar
   e aguardar o usuário, com um resumo final claro do que foi feito.
