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
2. Abra no navegador: **`http://100.122.206.41:8299`** (funciona no navegador do
   próprio servidor ou de qualquer aparelho na sua rede Tailscale).
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
  Tailscale em `http://100.122.206.41:8299` — **rodando agora, supervisionada pelo
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

Durante a execução da arquitetura gerada pelo script, você pode encontrar alguns problemas decorrentes da complexidade de lidar com Hardware, I/O e Kernel simultaneamente no Ubuntu. Aqui está o guia de sobrevivência:

### 1. Erro de Permissão do `systemd-run` via SSH (Gate 1 Falha)
**Problema:** Ao rodar via SSH de outro computador, o Ubuntu pode negar a criação do escopo de memória do `systemd-run` retornando um erro de "Failed to connect to bus".
**Solução:** O script Python do AP AI Studio possui um Fallback automático para usar a biblioteca `resource`. Mas caso queira consertar isso permanentemente no servidor, habilite o "linger" para o seu usuário rodando: `loginctl enable-linger ap`. E certifique-se de que a variável de ambiente do DBus está ativa no terminal remoto executando `export DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus"`.

### 2. FFmpeg Gerando "Audio Drift" (Sincronia labial atrasada)
**Problema:** O vídeo final aparece com o áudio alguns milissegundos ou segundos atrasado em relação à imagem.
**Solução:** Isso ocorre se o vídeo original possui uma Taxa de Quadros Variável (VFR) originada de um celular, e o script de IA tentou processar como se fosse fixo. A automação deve ter um "Passo Zero" forçado. Você também pode rodar o FFmpeg manualmente para travar os quadros antes de jogar na IA:
`ffmpeg -i original.mp4 -r 24 -c:v libx264 -c:a copy cfr_original.mp4`

### 3. VRAM Estourando Repentinamente (Crash no Gate 2)
**Problema:** O script alerta no Gate 2 que a VRAM tem menos de 15.5GB livres. O ComfyUI recusa a renderização.
**Solução:** O seu Qwen 2.5 (Ollama/LM Studio) ou a Steam estão monopolizando a Placa de Vídeo em segundo plano. Rode o comando `nvidia-smi` no terminal para descobrir o PID (ID do Processo) que está usando a VRAM. Encerre o jogo ou descarregue temporariamente o modelo do Qwen da memória até a renderização do vídeo acabar.

### 4. Lentidão Extrema e Placa de Vídeo Ociosa (SATA Bottleneck)
**Problema:** O render do vídeo está sendo executado de forma absurdamente lenta, com processamento na GPU baixo.
**Solução:** O disco SATA não está conseguindo acompanhar o ritmo da gravação dos frames. Verifique se o script Python gerado pela IA realmente incluiu o formato de gravação compactado *lossless* (como `-c:v ffv1` no FFmpeg) ao invés de usar imagens PNG descompactadas pesadas. Se o FFmpeg estiver gerando PNGs crus, ele engasgará a velocidade (banda) do disco SATA.

### 5. Wayland Crash no Ubuntu 24.04 (Falta de Monitor)
**Problema:** O terminal acusa um erro de "Could not load the Qt platform plugin wayland". O script aborta.
**Solução:** Bibliotecas de processamento visual como o OpenCV tentaram invocar um renderizador de janelas e não encontraram uma tela gráfica disponível (comum em sessões remotas/SSH ou scripts sem janela). Confirme se a variável `export QT_QPA_PLATFORM=offscreen` está ativada (ou injetada no script) para forçar as bibliotecas a rodarem de modo "Headless" (Invisível).

### 6. Interface web recusa o upload (HTTP 413 ou 507)
**Problema:** Ao enviar um arquivo pela interface web, a resposta vem com erro em vez de criar o job.
**Solução:** `413` = arquivo maior que o limite de 4GB (`MAX_UPLOAD_BYTES` em `webui/backend/config.py`) — normal pra vídeos muito longos, considere usar `--chunk-seconds` pelo terminal em vez da interface pra esses casos. `507` = disco já está abaixo da margem de segurança de 30GB antes mesmo do upload começar — libere espaço (`vfx-status` ou a aba Status da webui mostram o espaço livre) antes de tentar de novo.
