# AP AI Studio

Repositório principal da arquitetura do "AP AI Studio". Este repositório contém a fundação (Prompt Architect) e o código fonte (em desenvolvimento) para orquestração assíncrona, segura e de alto desempenho de IA generativa em vídeo (ComfyUI e FaceFusion) num servidor Linux multi-tarefa.

---

## Como usar

Existem duas formas de usar o pipeline — escolha a que preferir, elas fazem exatamente a mesma coisa por baixo dos panos.

> 📖 Este README é um começo rápido. O **guia completo, didático, explicando cada
> conceito do zero** está em [`MANUAL_USO.md`](MANUAL_USO.md) — comece por lá se
> nunca usou nenhuma dessas ferramentas antes.

### Opção A — Interface web (mais fácil, sem terminal)

1. Num terminal, ligue a interface:
   ```bash
   vfx-web
   ```
   Na primeira vez ele builda o frontend sozinho (demora um pouco); nas próximas, sobe
   direto. Deixe esse terminal aberto — `Ctrl+C` desliga.
2. Abra no navegador: **`http://100.122.206.41:8299`** (funciona no navegador do
   próprio servidor ou de qualquer aparelho na sua rede Tailscale).
3. Navegue pelo menu no topo:
   - **Status** — vê se o ComfyUI está ligado, VRAM e disco livres.
   - **Gerar Vídeo** — texto→vídeo ou imagem→vídeo.
   - **Imagem ▾** — Trocar Rosto, Editar Imagem, Remover Fundo.
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
- `run_vfx.py` / `test_run_vfx.py`: orquestrador principal e sua suíte de testes.
- `tts_synthesize.py` / `demucs_separate.py`: scripts standalone chamados pelo `run_vfx.py` (modos `tts` e `denoise`), cada um no seu próprio ambiente Conda.
- `webui/`: interface web (FastAPI + React/TypeScript/Tailwind/Bootstrap), acessível via
  Tailscale em `http://100.122.206.41:8299` (`vfx-web` liga). Todas as 10 funções do
  `run_vfx.py` (Fases A+B) — ver seção 11 do `MANUAL_USO.md`. `webui/backend/` (env
  Conda `webui-pipeline`, testes em `webui/backend/test_backend.py`) chama `run_vfx.py`
  como subprocesso, mesma lógica dos atalhos `vfx-*` — não duplica a lógica dos Gates
  (exceção: dublagem chama o FaceFusion direto, igual ao atalho `vfx-dublar`).
  `webui/frontend/` (Vite): `npm run build` gera `webui/backend/static/`.

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
