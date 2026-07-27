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

### Riscos reais encontrados — não bloqueiam, mas o usuário precisa saber
1. **Crash de GPU real no `inpaint` (2026-07-27 02:00)** — page fault de hardware
   confirmado no kernel (`amdgpu`/ROCm, `GCVM_L2_PROTECTION_FAULT`, `SDMA0`) ao carregar
   SDXL num processo ComfyUI de longa duração que antes tinha processado Wan2.2. GPU não
   travou, se recuperou sozinha, e o retry funcionou (a arquitetura já se
   autorrecupera). Mas na **primeira** vez, o usuário real da webui veria o job falhar e
   precisaria clicar em "Iniciar" de novo. Não reproduzido de propósito por falta de
   tempo — hipótese não confirmada de que reaproveitar ComfyUI de longa duração entre
   tipos de modelo diferentes (vídeo → imagem) é o gatilho. Se isso se repetir em uso
   real, considerar: reiniciar o ComfyUI preventivamente ao trocar de tipo de workflow,
   ou investigar se é uma imaturidade conhecida do ROCm 7.13 em gfx1201 (RDNA4 tem
   suporte oficial só desde ROCm 7.2, muito recente).

### O que FALTA testar de verdade (é o trabalho dos próximos wakeups)

Nenhum destes modos foi executado de ponta a ponta ainda. Testar cada um é o que resta
para "tudo estar pronto":

- [x] **faceswap** — ✅ SUCESSO (2026-07-27 01:54, 11min26s em CPU). Assets oficiais do FaceFusion (`releases/download/examples-3.0.0/source.jpg` + `target-240p.mp4`, confirmados via URL do próprio `tests/test_cli_face_swapper.py` do FaceFusion). Output h264 426x226 10.8s, frame extraído e inspecionado visualmente — rosto coerente, sem artefato.
- [x] **inpaint** — ✅ SUCESSO no 2º teste (2026-07-27 02:03), com achado real e grave no meio do caminho. 1ª tentativa: o processo do ComfyUI (vivo desde ~00:22, reaproveitado entre o render de vídeo Wan2.2 e o inpaint SDXL) **morreu com um page fault de hardware real** — confirmado no kernel (`journalctl -k`): `amdgpu 0000:03:00.0: GCVM_L2_PROTECTION_FAULT_STATUS`, `Faulty UTCL2 client ID: SDMA0`, crash com stack trace dentro de `libhsa-runtime64.so` (`rocr::core::Runtime::VMFaultHandler`). NÃO é bug de código — é o driver ROCm/gfx1201 relatando falta de página na GPU. Verificado que a GPU NÃO travou/resetou (sem "gpu reset" no kernel log) e continuou 100% operacional depois (multiplicação de matriz real confirmada, VRAM voltou ao nível ocioso). **2ª tentativa, processo reiniciado do zero: sucesso em 15s** — a arquitetura já se autorrecupera (`ensure_comfyui_running_under_jail` detecta que o scope morreu e sobe um processo limpo sozinho), mas a 1ª tentativa do usuário falharia e precisaria de retry manual. **Hipótese não confirmada**: o fault pode estar ligado a reaproveitar um processo ComfyUI de longa duração (1h38min, `24.8G memory peak`) para carregar um tipo de modelo novo (SDXL) depois de já ter processado Wan2.2 — não teve tempo de reproduzir de propósito para confirmar. Registrado como risco real de produção, não resolvido nesta sessão (ver seção de risco abaixo). Output: JPEG 1024x1024, 1.4MB, inspecionado visualmente — edição coerente, com leve linha visível na borda da máscara (esperado: minha máscara de teste é um retângulo sintético de borda dura via ffmpeg, não uma máscara orgânica real — o código de suavização (`feather_amount`) já é validado no histórico do projeto). Teste com `--use-depth-controlnet`: ✅ SUCESSO (02:06, 66s, reaproveitando o mesmo processo já reiniciado — reforça a hipótese de que o crash foi específico à troca vídeo→imagem, não instabilidade geral do SDXL/ControlNet). Output JPEG 1.4MB válido.
- [x] **removebg** — ✅ SUCESSO no 2º teste (2026-07-27 01:56). 1º teste falhou com "match the target and output extension!" (source.jpg → output.png) — mas essa é uma **restrição real do próprio FaceFusion, em TODOS os processadores dele** (confirmado no código-fonte: mesma checagem em background_remover, face_swapper, face_enhancer etc.). NÃO é bug do projeto — `webui/backend/routes_removebg.py` já trata isso corretamente (mantém a extensão do target, com comentário próprio documentando o achado). O bug real estava na **documentação**: `MANUAL_USO.md` tinha 3 exemplos ensinando `--target F.jpg --output O.png` (removebg), que falharia sempre. Corrigido nos 3 lugares. Também corrigidas 44 ocorrências do caminho pré-consolidação (`/var/home/apsrv/ap-ai-studio/` → `/var/home/apsrv/Projetos/ap-ai-studio/`) no mesmo arquivo, que ficaram de fora da consolidação porque o foco tinha sido código/config, não documentação longa.
- [x] **tts** — ✅ SUCESSO após corrigir bug real (2026-07-27 01:54). BUG: `pip install coqui-tts` sem fixar versão puxou `transformers==5.14.1`, que remove `isin_mps_friendly` de `transformers.pytorch_utils` — `ImportError` na primeira linha, o próprio `PROMPT_MASTER.md` já documentava a exigência de `transformers==4.57.6` exato mas o script de build não fixava. Também faltava `torchcodec` (torch>=2.9 exige p/ I/O de áudio). Corrigido: `stage2_apps.sh` fixa a versão + instala torchcodec; `requirements/tts-pipeline.txt` regenerado do ambiente são. Teste real: WAV 24kHz mono 5.43s, voz embutida "Claribel Dervla", 6min55s (inclui download do modelo ~1.4GB na primeira execução).
- [x] **dublagem** — ✅ SUCESSO (2026-07-27 02:03, 136,47s em CPU — quase idêntico aos ~136s já documentados no `PROMPT_MASTER.md` na era RTX, confirma que o caminho é CPU-bound de verdade, independente da GPU). Output h264+flac válido, 10.8s.
- [x] **denoise** — ✅ SUCESSO (2026-07-27 01:56, 38s, acelerado por ROCm). Dependia da correção do bug do `numpy` (ver acima). Áudio oficial de teste do próprio Demucs (`github.com/facebookresearch/demucs/raw/main/test.mp3`). Dois WAVs de 3,5MB gerados (voz + instrumental).
- [x] **upscale --upscale-method lanczos** — ✅ SUCESSO (2026-07-27 01:46). 1024x1024 → 4096x4096 confirmado via ffprobe, 0,3s. Gates passaram normalmente.
- [x] **upscale --upscale-method realesrgan** — ✅ SUCESSO (2026-07-27 02:07, 15s). 1024x4096 confirmado.
- [x] **master** — ✅ SUCESSO com VAAPI (padrão, 02:07, 0,4s). Remux confirmado correto: vídeo do `--processed-video` (426x226, do faceswap), áudio do `--original` (AAC, do vídeo sintético com áudio gerado pra este teste). **Achado real:** nem o CLI (`run_vfx.py`) nem a webui (`routes_master.py`) expõem forma de escolher `video_codec="libx264"` — o parâmetro existe em `vfx_ffmpeg.py` mas só é alcançável chamando a função Python direto. Lacuna de usabilidade documentada, não corrigida nesta sessão (implicaria feature nova: flag CLI + campo na webui + testes).
- [x] **Comparar VAAPI vs libx264** — ✅ feito chamando `build_ffmpeg_mastering_command` direto (já que não há flag exposta). Mesmo conteúdo: VAAPI 209KB/130kbps, libx264 165KB/98kbps — libx264 mais eficiente em bits (esperado, é típico de encoder por software vs hardware). Frames extraídos e comparados visualmente lado a lado: **sem diferença perceptível de qualidade** para este conteúdo (rosto estático, fundo liso).
- [~] **Render de vídeo em tamanho real** — PARCIAL, achado real e importante.
  - **720x720 (máximo permitido por `MAX_VIDEO_WIDTH/HEIGHT`) + 161 frames (default de `--num-frames`): OOM CONFIRMADO** (2026-07-27 02:10, 21s até falhar). Erro real do PyTorch/ROCm: `CUDA out of memory. Tried to allocate 3.17 GiB. GPU 0 has a total capacity of 15.92 GiB of which 3.22 GiB is free. Of the allocated memory 12.02 GiB is allocated by PyTorch`. Falhou no `WanVideoSampler` (segundo/low-noise sampler). Isso é exatamente o risco que o próprio `vfx_config.py` já documentava por escrito (`MAX_VIDEO_FRAMES = 241 # ... ainda NAO testado nessa escala`) — agora confirmado ao vivo: **161 frames em 720x720 não cabe nos 16GB desta GPU com `--blocks-to-swap` no padrão (20)**.
  - **IMPORTANTE — isto NÃO é o default real que a webui oferece.** A `VideoPage.tsx` tem placeholder 320x320/161 frames, não 720x720 (720 é só o teto permitido, não o valor padrão). Rodando 320x320/161 frames (o default de verdade) para saber se ESTE caso — o que a maioria dos usuários vai realmente disparar — funciona. Iniciado 02:11:30, unidade `ai-studio-render-default`, resultado ainda não disponível no momento deste commit (ver próximo wakeup).
  - `VRAM_PEAK_ALERT_GB` **NÃO foi recalibrado ainda** — falta o dado do teste em 320x320/161 frames primeiro, e idealmente também confirmar se aumentar `--blocks-to-swap` (mais offload pra CPU RAM, mais lento) resolve o caso 720x720 antes de decidir se o limite de `MAX_VIDEO_WIDTH/HEIGHT=720` no código é realista pra esta GPU ou se deveria ser menor.
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
