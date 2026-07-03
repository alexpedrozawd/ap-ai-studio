# AP AI Studio - O Prompt Constante de Automação (Fail-Safe)

Este documento contém o prompt master definitivo para a criação de um pipeline de geração de vídeo e efeitos visuais em um servidor Ubuntu 24.04 (Wayland) utilizando uma NVIDIA RTX 5060 Ti, mantendo a integridade do sistema operacional e do servidor de LLMs (Qwen).

---

[INÍCIO DO PROMPT - ARQUITETURA FAIL-SAFE (COM GATES DE SEGURANÇA)]
Assuma os papéis de Arquiteto de Software, SRE Sênior e Especialista de Segurança de TI.

**Ambiente:** Ubuntu 24.04 (Wayland) | **Hardware:** RTX 5060 Ti 16GB, 32GB RAM, SSD NVMe M.2 Samsung (OS + Dados do pipeline, temporariamente — o SSD SATA está com problema e será substituído; migrar de volta para o SATA depois da troca).
**Restrição de Servidor Multitarefa:** O PC atua como Servidor de LLMs (Qwen), Gaming e OS diário. NENHUMA trava de atualização de SO/Drivers é permitida.

**Regras de Paginação (CRÍTICO):** Entregue APENAS a Fase solicitada e pare. Aguarde meu comando "PRÓXIMO".

**Verificação de Estado Real (CRÍTICO):** Antes de agir em qualquer Fase, verifique o estado real do servidor (disco, portas, binários instalados, serviços) em vez de assumir que este documento já reflete a realidade atual — ele é editado incrementalmente e pode estar desatualizado em relação ao que já foi executado.

**Fase 0: Design e Arquitetura Lógica**
Gere o Fluxograma Lógico focando em isolamento extremo. Aguarde aprovação. NÃO codifique.
**Critério de Conclusão:** fluxograma aprovado por mim antes de prosseguir para a Fase 1.

**Fase 1: Infraestrutura (Guia Interativo de Terminal / Sem Scripts Autônomos)**
Forneça comandos isolados para cópia manual, com explicações.
1. Instrua como inicializar Conda e criar o ambiente (`pytorch-cuda=12.4`). Ambiente é descartável: se quebrar, `conda env remove -n <nome>` e recriar do zero, sem afetar o resto do sistema. **Nota de execução (Fase 1 real):** o `pip install -r requirements.txt` do ComfyUI não fixa versão de torch e reinstalou `torch 2.12.1+cu130` (CUDA 13.0) por cima do `pytorch-cuda=12.4` inicial. Decisão tomada: manter CUDA 13.0 — bate com o driver instalado (`595.71.05`/CUDA 13.2) e `torch.cuda.is_available()` confirmou True. `pytorch-cuda=12.4` na criação do env serve só de ponto de partida; a versão final que importa é a que sobra depois dos requirements do ComfyUI. Também apareceu um `ImportError: undefined symbol: iJIT_NotifyEvent` logo após criar o env — incompatibilidade de ABI entre o `torch` da conda e `mkl 2025.x` puxado do canal `defaults`; corrigido fixando `mkl<2025` (`conda install -n vfx-pipeline "mkl<2025"`).
2. Redirecionamento permanente de variáveis (`TMPDIR`, `TEMP`) e do `/models_hub` para **`/home/ap/ai_pipeline`** (NVMe M.2 Samsung principal — o SATA está com problema e será substituído; quando o disco novo chegar, migrar este caminho de volta para lá). Como agora esse diretório compartilha o mesmo disco do SO, monitorar espaço livre (`df -h /`) antes de cada render e alertar se cair abaixo de uma margem de segurança (ex.: 30GB), já que não há mais um disco separado para conter o estouro. Confirmar que esse caminho foi adicionado à exclusão do `/etc/cron.d/clamav-nightly` (mesma lógica das exclusões do Ollama), para não sobrecarregar o scan noturno com os arquivos de modelo. Instale o **ComfyUI-Manager** e use-o para baixar/verificar modelos (catálogo curado + checagem de hash já embutida) apontando `extra_model_paths.yaml` para esse diretório, em vez de escrever validação de hash manual.
3. Inicialização do ComfyUI em porta exótica (ex: `--port 8288`), **bindando exclusivamente em `127.0.0.1` ou no IP Tailscale** (nunca `0.0.0.0`) e **sem criar regra `ufw allow`** para essa porta — acesso remoto só via Tailscale, mantendo o `deny-incoming` do firewall. Mesma regra vale para o Gradio do FaceFusion (porta 7860, livre — não colide com o Gradio já existente em `100.122.206.41:7861`). **Nota de execução (Fase 1 real):** o FaceFusion roda num ambiente Conda **separado** (`facefusion-pipeline`, distinto do `vfx-pipeline` do ComfyUI) — seu `requirements.txt` fixa `numpy==2.2.1`, que colidiria com o `numpy` mais novo puxado pelas dependências do ComfyUI no mesmo ambiente (mesma classe de problema que o conflito de `mkl` no item 1 acima). O comando de subida usa `GRADIO_SERVER_NAME=127.0.0.1 GRADIO_SERVER_PORT=7860 python facefusion.py run --execution-providers cuda`, já que o `ui.launch()` do FaceFusion não expõe flag de porta/host — depende só das env vars padrão do Gradio.
4. Habilitar `sudo loginctl enable-linger ap` (ação única). Sem isso, o Gate 1 (`systemd-run --user --scope`) só funciona enquanto houver uma sessão de login ativa — qualquer execução desacoplada (terminal fechado, cron, sessão SSH caindo no meio do render) cai direto no Plano B (`resource`) em vez do mecanismo principal. Não altera SSH/UFW/Tailscale/driver.
**Critério de Conclusão:** ambiente Conda ativo, ComfyUI respondendo em `/system_stats` via `127.0.0.1:8288` ou IP Tailscale, FaceFusion acessível, `loginctl show-user ap -p Linger` retornando `Linger=yes`.

**Fase 2: Validação Leve Pré-Código (`test_run_vfx.py`)**
Em vez de uma suíte `pytest-mock` completa simulando todo cenário, escreva só os testes essenciais que evitam quebrar algo real antes do código existir: validação de caminho (`/home/ap/ai_pipeline` existe e é gravável), sanity check dos binários externos (`ffmpeg`, `conda`, porta 8288 livre) e parsing de argumentos. Não é necessário mockar cada gate aqui — isso já é coberto pelo teste de aceitação com falha forçada da Fase 3, evitando duplicar esforço de teste num projeto pessoal.
**Critério de Conclusão:** validações essenciais passam com `pytest`, sem tocar GPU/disco real.

**Fase 3: Motor de Orquestração com "Authorization Gates" (`run_vfx.py`)**
Escreva o script `asyncio` principal, registrando cada decisão de gate (aprovado/negado), erro e timestamp em log persistente (`/home/ap/ai_pipeline/logs/run_vfx.log`), pra permitir diagnóstico depois de uma execução desacoplada/sem alguém acompanhando o terminal. Regras de Segurança, Performance e Checkpoints Manuais:
1. **Portões de Autorização (CRÍTICO):** Antes de tarefas críticas, o script DEVE pausar e exigir `[Y/n]` no terminal:
   * **Gate 1 - A Jaula de Memória:** Antes de invocar subprocessos envelopados por `systemd-run --user --scope -p MemoryMax=24G` (modo padrão: face-swap/imagem). **No modo vídeo generativo (Fase 3B), usar `MemoryMax=28G` + `MemorySwapMax=4G`** — o offload de blocos de modelo para RAM (ver Fase 3B) consome bem mais que o teto padrão de 24GB, e com o Qwen descarregado (Gate 2) sobram ~4GB de margem pro SO nos 32GB totais. O `MemorySwapMax` é só um colchão de emergência do nosso próprio subprocesso — não altera o `/swapfile` compartilhado nem o acesso do Ollama a ele, só evita que o pipeline entre em *thrashing* consumindo o swap todo, o que deixaria o servidor inteiro (inclusive a sessão SSH/Tailscale) lento. Medir o uso real de RSS num teste antes de fixar esses valores em produção; não assumir os números como definitivos. **Teste de aceitação:** forçar um estouro de memória de propósito num teste e confirmar que só o subprocesso morre — a sessão SSH/terminal continua viva (o `systemd-run --scope` cria um scope novo, isolado da sessão de login; validar que a implementação realmente escopa só a árvore de processos do pipeline, não a sessão inteira). Plano B (Fallback): Caso falhe por falta de sessão DBus via SSH (ver `loginctl enable-linger` na Fase 1), use limite interno via biblioteca `resource`. **Nota de execução (Fase 3 real, achado importante):** o teste de aceitação forçado revelou que `MemoryMax` sozinho **não mata o processo** quando há swap disponível — o kernel (cgroup v2) prefere reclamar memória (empurrar páginas anônimas pro `/swapfile` compartilhado) em vez de acionar o OOM-killer. Confirmado ao vivo: um subprocesso alocando 300MB sob `MemoryMax=50M` seguia rodando normalmente até o `MemorySwapMax=0` ser adicionado, aí sim foi morto (SIGKILL/137). Por isso o modo padrão (face-swap) também define `MemorySwapMax=0` explicitamente — não só o modo vídeo — senão a "jaula" na prática não contém nada, ela só empurra o excesso pro swap do servidor inteiro (o mesmo risco de thrashing que o texto original só reconhecia pro modo vídeo). **Nota de execução (auditoria pós-Fase 3B, achado crítico):** uma revisão de código (3 ângulos independentes, dois convergindo no mesmo achado) encontrou que o Gate 1 calculado no modo vídeo nunca era de fato aplicado — `orchestrate()` computava `MemoryMax=28G`/`MemorySwapMax=4G` e pedia aprovação, mas o modo vídeo só faz HTTP para o ComfyUI já em execução, sem nenhum `systemd-run`/`resource.setrlimit` envolvendo o processo que realmente processa o render. Confirmado ao vivo: o ComfyUI rodando estava no cgroup da própria sessão SSH (`memory.max=max`, `memory.swap.max=max`), sem limite nenhum. Corrigido com `ensure_comfyui_running_under_jail()`, que reinicia o ComfyUI dentro de um `systemd-run --scope` dedicado (`vfx-comfyui-video.scope`) com os limites do Gate 1 e `PYTORCH_CUDA_ALLOC_CONF` aplicados antes de qualquer render de vídeo.
   * **Gate 2 - Pico de VRAM, RAM e Swap:** Antes do POST para a API do ComfyUI. Mostrar VRAM livre, alertar pico de 15GB e pedir aprovação (respeito ao Qwen). **No modo vídeo generativo (Fase 3B), mostrar também RAM livre e uso atual de swap do sistema** (o offload de blocos usa RAM/swap ativamente, não é mais só memória ociosa do SO) — se RAM, VRAM ou swap estiverem apertados por causa do Qwen carregado, oferecer `[Y/n]` para descarregar o modelo do Ollama antes de prosseguir (via `ollama stop <modelo>`/API `keep_alive=0`, sem parar o serviço `ollama.service`), em vez de falhar silenciosamente.
   * **Gate 3 - I/O de Disco (NVENC Chunking):** Antes do FFmpeg usar `nvenc` e gravar os arquivos intermediários no formato *ffv1* ou *libx264 -crf 0* em `/home/ap/ai_pipeline` (NVMe compartilhado com o SO). Checar espaço livre em `/` antes de iniciar e abortar se estiver abaixo da margem de segurança, já que não há mais um disco isolado para conter o consumo.
2. **Modo de Confiança (opcional, flag `--auto-approve`):** depois de validar os 3 gates manualmente nos primeiros runs de uma sessão, permitir pular a confirmação interativa dos Gates 1 e 2 em renders curtos/de teste (útil na iteração da Fase 3B, onde se espera bastante tentativa e erro) — a decisão continua sendo registrada no log (`run_vfx.log`) mesmo sem prompt, pra não perder rastreabilidade. **O Gate 3 (espaço em disco crítico) nunca é pulável com essa flag** — sempre aborta se estiver abaixo da margem de segurança, independente do modo.
3. *Wayland Guard* (`QT_QPA_PLATFORM=offscreen`) e `--dry-run` puro (somente stdout).
4. Seleção de rosto no FaceFusion via **modo de rosto de referência** (`--face-selector-mode reference` + foto de referência da pessoa a inserir), evitando depender de filtros de idade/gênero para escolher o alvo — confirme o nome exato do flag na versão instalada. Polling dinâmico de `/system_stats`. Higiene de metadados EXIF da foto via `exiftool -all=` (ou `mat2`), em vez de lógica custom com `PIL` — cobre mais formatos e campos de metadado. **Nota de execução (Fase 3 real):** `exiftool` instalado via `sudo apt install libimage-exiftool-perl` (v12.76) e `sanitize_exif` testada ponta a ponta com imagem real contendo `Artist`/`GPS` — campos confirmados removidos após a limpeza. **Achado adicional (primeiro face-swap real, pós-Fase 4):** `build_facefusion_command` usava `"python"` genérico, que resolvia pro interprete do ambiente Conda ativo no processo do `run_vfx.py` (`vfx-pipeline`, do ComfyUI) — sem `onnxruntime` instalado lá, já que o FaceFusion vive num ambiente Conda **separado** (`facefusion-pipeline`, ver Fase 1). Corrigido usando o caminho explícito `~/miniconda3/envs/facefusion-pipeline/bin/python`. Testado ponta a ponta com as imagens de exemplo oficiais do próprio FaceFusion (`facefusion/facefusion-assets`, não são fotos de pessoas reais identificáveis) — rosto trocado com sucesso, mantendo pose/iluminação da cena de destino.
**Critério de Conclusão:** os 3 gates disparam corretamente em teste forçado (memória, VRAM, disco), teste de aceitação do Gate 1 (isolamento de scope) validado, e um dry-run completo roda do início ao fim sem erro.

**Fase 3B: Modo Vídeo Generativo / Reencenação de Movimento (Baixo-VRAM, experimental)**
Aplicável somente quando a tarefa exigir mais do que troca de identidade facial (FaceFusion) — ex.: reencenação de expressão, geração de movimento/interação corporal nova que não existia na filmagem original. **Expectativa calibrada:** na RTX 5060 Ti (16GB VRAM) isso é viável, mas não "com folga" — é um modo experimental, com resolução reduzida, clipes curtos e renders significativamente mais lentos (o offload RAM↔VRAM depende da banda da RAM DDR4 3200MHz dual-channel e do PCIe, então espere de 3x a 10x+ mais lento que um render que coubesse inteiro na VRAM — não é "um pouco mais lento"). As técnicas abaixo reduzem bastante a frequência de erros de falta de memória (OOM), mas não os eliminam.

1. **Modelos quantizados (GGUF):** priorizar a versão GGUF (Q4/Q8) do modelo de vídeo escolhido via node pack de quantização da comunidade ComfyUI, em vez da versão em precisão cheia. Antes de comprometer com um modelo específico, **confirmar que existe release GGUF/quantizado mantido para ele** — a disponibilidade varia por modelo e muda rápido nesse ecossistema, não assumir que todo modelo tem.
2. **Block swap / offload para RAM:** usar o parâmetro de offload de blocos disponível no wrapper do modelo de vídeo escolhido (mantém a maior parte do modelo na RAM, só trazendo pra VRAM o bloco em processamento). Trade-off explícito: menos OOM, muito mais lento — aceito neste projeto. Dimensionar dentro do teto do Gate 1 (28GB).
3. **VAE Decode em modo Tiled:** usar o node nativo de decodificação em blocos do ComfyUI para o passo de decode do vídeo, em vez de decodificar tudo de uma vez — esse é o ponto onde mais estoura VRAM no fim do processo.
4. **`PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`:** definir essa variável de ambiente no processo do ComfyUI para reduzir OOM por fragmentação de memória (quando cabe nominalmente mas falta um bloco contíguo).
5. **Qwen descarregado antes do render:** reforça o Gate 2 — nesse modo, verificar RAM livre além de VRAM, e oferecer descarregar o Qwen via `[Y/n]` se necessário.
6. **Resolução baixa + clipe curto como padrão, com upscale posterior:** gerar em resolução reduzida (ex.: 480p) e poucos segundos por vez; rodar um upscaler leve (ex.: Real-ESRGAN, que cabe folgado em 16GB) como passo separado depois, em vez de tentar gerar direto em alta resolução.
**Critério de Conclusão:** um clipe curto de teste (poucos segundos, baixa resolução) renderiza do início ao fim sem OOM, com upscale aplicado depois.

**Nota de execução (Fase 3B real, CONCLUÍDA):** modelo usado: Wan2.2 T2V-A14B GGUF Q4_K_M (MoE high/low noise, `QuantStack/Wan2.2-T2V-A14B-GGUF`), node packs `kijai/ComfyUI-WanVideoWrapper` + `city96/ComfyUI-GGUF`, text encoder `Kijai/WanVideo_comfy` (umt5-xxl fp8 não-scaled), VAE `Wan2.1_VAE.safetensors`, upscale `RealESRGAN_x4plus`. Render de teste: prompt de texto, 320×320, 17 frames, 10 steps (5 high-noise + 5 low-noise) — concluído com sucesso, arquivo final `1280×1280` (upscale 4x confirmado), 17 frames, VRAM/RAM voltaram ao normal depois (sem vazamento). Três bugs reais encontrados e corrigidos durante a execução real (nenhum decorre do design do documento, todos de detalhes de integração):
1. **Gate 1 não era aplicado no modo vídeo** (achado de auditoria antes do render) — corrigido com `ensure_comfyui_running_under_jail()`, que reinicia o ComfyUI dentro de um `systemd-run --scope` dedicado antes de qualquer render.
2. **`conda run` não repassa stdin** — os prompts `[Y/n]` do Gate 3 (nunca pulável) travavam com `EOFError` mesmo com `--auto-approve`. Usar `conda activate` em vez de `conda run` para invocações interativas do `run_vfx.py`. Não é bug do pipeline (script lê stdin normalmente com `conda activate`), mas `confirm()` foi ajustada para capturar esse `EOFError` e devolver uma mensagem clara explicando a causa, em vez de um traceback cru.
3. **Arquivo errado de text encoder**: o `umt5_xxl_fp8_e4m3fn_scaled.safetensors` (variante "scaled", do repo `Comfy-Org/Wan_2.2_ComfyUI_Repackaged`, pensado pro loader nativo do ComfyUI) é rejeitado pelo `LoadWanVideoT5TextEncoder` do WanVideoWrapper (`ValueError: fp8 scaled is not supported by this node`). O arquivo certo pra esse node é `Kijai/WanVideo_comfy/umt5-xxl-enc-fp8_e4m3fn.safetensors` (não-scaled).

**Atualização de escopo (pedido do usuário, pós-Fase 4):** duração mínima passou a ser 5s, média 10-15s (o texto original da Fase 3B previa só "clipes curtos" sem número). Confirmado nos workflows de exemplo do próprio Kijai que o modelo **A14B roda nativamente a 16fps** (24fps é especifico do modelo 5B, que não usamos) — nosso teste original usava `frame_rate=16` errado como `8` no `VHS_VideoCombine`, o que teria deixado qualquer clipe gerado em câmera lenta (2x mais devagar) sem ninguém perceber, já que o número de frames em si sempre esteve certo. Corrigido: `frame_rate=16`, novo padrão `num_frames=161` (~10s), `MAX_VIDEO_FRAMES=241` (~15s). **Testado nessa escala nova (CONCLUÍDO):** 161 frames (~10s), render completo em ~9min15s, sem OOM, dentro da jaula de 28GB/4GB swap. Arquivo final confirmado via `ffprobe`: **10.7 segundos**, 1280×1280, **321 frames reais** (não só um número de frame_rate mudado).

**Interpolação de frames (pedido do usuário — cinema/TV usa ~24-30fps, não os 16fps nativos do modelo):** usuário corretamente notou que 16fps nativo é mais baixo que o padrão de cinema (24fps) ou TV (30fps) — mas mudar só o `frame_rate` de salvamento não teria resolvido isso de verdade (só mudaria a velocidade de reprodução, é o mesmo tipo de bug do item acima, só que ao contrário: acelerar em vez de desacelerar). A correção real é **interpolação de frames**: o nó nativo `FrameInterpolate` do ComfyUI (`comfy_extras/nodes_frame_interpolation.py`, já vem com a instalação, não precisou de node pack extra) usa um modelo RIFE (`Comfy-Org/frame_interpolation/rife_v4.25.safetensors`, ~22.6MB, adicionada categoria `frame_interpolation` no `extra_model_paths.yaml`) pra gerar quadros intermediários de verdade entre os frames existentes. `multiplier=2` dobra os 16fps nativos pra ~32 quadros reais por segundo, salvos a `WAN22_OUTPUT_FPS=30`. Testado e confirmado: os 321 frames reais no arquivo final batem exatamente com `(161-1)*2+1=321`, confirmando que a interpolação rodou de verdade, não é só cosmético.
4. **`WanVideoVAELoader` exige `precision` mesmo aparecendo como "optional" no `/object_info`** — sem isso, o ComfyUI derruba o job com `TypeError` depois de já ter rodado os dois samplers (caro, quase 1min de processamento perdido). Sempre passar `precision` explicitamente.

**Fase 4: Render Final e Masterização**
1. Costura final: FFmpeg com Frame Rate Constante (CFR) e Matriz bt709.
2. Mapeamento bruto (`-map 0 -c:a copy -c:s copy -map_metadata 0`) preservando Áudio Surround 5.1/7.1 e legendas originais intactas.
**Critério de Conclusão:** arquivo final joga certo, áudio/legendas sincronizados, sem artefato visível de troca de quadro.

**Nota de execução (Fase 4 real, CONCLUÍDA):** `-vsync` está deprecated no ffmpeg 6.1.1 instalado neste servidor — usar `-fps_mode cfr` no lugar. Comando final: dois inputs (`-i original -i processado`), vídeo vem do processado (`-map 1:v:0`), áudio/legendas/metadados vêm do original sem recodificar (`-map 0:a? -map 0:s? -c:a copy -c:s copy -map_metadata 0`, os `?` tornam opcional caso não exista). Testado ponta a ponta com um vídeo sintético (h264+AAC, título nos metadados) + o clipe real do Wan2.2: saída final confirmada via `ffprobe` com vídeo 1280×1280 do clipe processado, **24fps CFR**, matriz **bt709** nos três campos de cor, áudio AAC e metadados (`title`) preservados do original. **Achado importante durante o teste:** o `SaveAnimatedWEBP` nativo do ComfyUI gera um WebP animado que o demuxer do ffmpeg **não lê direito** (`skipping unsupported chunk: ANIM/ANMF`, decode falha) — troquei o nó final do workflow da Fase 3B de `SaveAnimatedWEBP` para `VHS_VideoCombine` (node pack `Kosinkadink/ComfyUI-VideoHelperSuite`, formato `video/h264-mp4`), que gera MP4 de verdade sem esse problema. Isso afeta a Fase 3B também — o clipe de teste gerado lá agora sai em `.mp4`, não `.webp`.

**Fase 5 (pedido do usuário, CONCLUÍDA): Imagem para Vídeo (I2V)**
Hoje o pipeline só faz **texto → vídeo** (T2V). O usuário pediu também **imagem → vídeo** (I2V) —
animar uma foto existente, em vez de partir só de uma descrição em texto. Isso é o modo mais
alinhado com o objetivo original do projeto (reencenar cenas/fotos de família), mas ainda não
foi implementado. Escopo estimado, sem inventar números além do que já foi confirmado:
1. Baixar os pesos GGUF do **Wan2.2-I2V-A14B** (repo `QuantStack/Wan2.2-I2V-A14B-GGUF` na
   HuggingFace — ainda não confirmei tamanho exato, mas pelo padrão do T2V deve ficar na casa
   de ~20-26GB pros dois experts MoE + text encoder, similar ao que já baixamos).
2. Adaptar o workflow: trocar `WanVideoEmptyEmbeds` por `LoadImage` + `WanVideoImageToVideoEncode`
   (nós que já identifiquei durante a pesquisa da Fase 3B, ao inspecionar o workflow de exemplo
   `wanvideo_2_2_I2V_A14B_example_WIP.json` do próprio Kijai).
3. Adicionar `--source-image` (ou modo `--mode video-i2v`) ao `run_vfx.py`.
4. Testar de ponta a ponta com uma imagem real, do mesmo jeito que validamos o T2V.
**Critério de Conclusão (proposto):** uma foto de teste anima com movimento coerente, sem OOM,
mesma duração mínima/média definida acima (5s mínimo, 10-15s média).

**Nota de execução (Fase 5 real, CONCLUÍDA):** pesos `QuantStack/Wan2.2-I2V-A14B-GGUF` (HighNoise+LowNoise, ~19.3GB), VAE e text encoder reaproveitados do T2V (mesmos arquivos). Workflow: `build_wan22_video_workflow` ganhou parâmetro opcional `source_image_path` — quando informado, troca `WanVideoEmptyEmbeds` por `LoadImage` → `ImageScale` (nativo, em vez do `ImageResizeKJv2` do Kijai que não temos instalado) → `WanVideoImageToVideoEncode`, mantendo o resto do grafo (block swap, samplers, decode, interpolação, upscale, save) idêntico ao T2V. Achado: `LoadImage` só aceita nomes de arquivo dentro de `ComfyUI/input/`, não caminho absoluto — criada `stage_image_for_comfyui()` que copia a foto de origem pra lá com nome único antes de montar o workflow. Testado ponta a ponta com a foto de exemplo oficial do FaceFusion + prompt pedindo "vira a cabeça pra olhar de lado": confirmado visualmente comparando frame de 1s (de frente) com frame de 4s (perfil) — a animação é real, não uma imagem estática repetida. Arquivo final: 1280×1280, 30fps, 5.37s, sem OOM.

**Fase 6 (pedido do usuário, CONCLUÍDA): Inpainting / edição geral de imagem**
Checkpoint `sd_xl_base_1.0_inpainting_0.1.safetensors` (conversão single-file do modelo
oficial `diffusers/stable-diffusion-xl-1.0-inpainting-0.1`, ~6.94GB). `build_inpaint_workflow`
usa nós nativos do ComfyUI (`CheckpointLoaderSimple` → `VAEEncodeForInpaint` com uma mascara
separada carregada via `LoadImage`+`ImageToMask` → `KSampler` → `VAEDecode` → `SaveImage`).
Escopo deliberado: máscara manual (branco=apagar, preto=manter), não segmentação automática
por texto (exigiria baixar GroundingDINO+SAM, deixado de fora por ora). Modo `--mode inpaint`
no `run_vfx.py`.

**Nota de execução (Fase 6 real, CONCLUÍDA):** testado de ponta a ponta duas vezes.
**Achado real #1:** com `positive_prompt` vazio, o SDXL às vezes preenche a área mascarada com
conteúdo sem relação nenhuma com a cena (gerou um padrão tipo bandeira do zero) em vez de
continuar o fundo naturalmente — mecanismo funcionava, qualidade ruim. Corrigido não no
código, mas na orientação: `run_vfx.py` agora avisa (`logger.warning`) quando `--mode
inpaint` é chamado sem `--prompt`, recomendando descrever o que deveria aparecer no lugar
(ex.: "fundo gradiente rosa e azul liso"). Reteste com prompt descritivo: fundo ficou
coerente com o restante da cena, resultado bem melhor. **Achado real #2:** `--output` estava
sendo completamente ignorado — o resultado sempre caía com nome fixo dentro de
`ComfyUI/output/`, sem nenhum jeito de saber onde parou. Corrigido com
`get_comfyui_output_file()`, que lê `/history` do ComfyUI pra achar o arquivo real gravado e
copia pro caminho pedido em `--output`.

**Fase 7 (pedido do usuário, CONCLUÍDA): Processar vídeos longos em pedaços**
`split_video_into_chunks`/`concat_video_chunks`/`process_long_faceswap`, novo
`--chunk-seconds` no modo faceswap. **Achado real (pego por um teste funcional rodando
ffmpeg de verdade, não mock):** dividir com `-c copy` (stream-copy) só corta em keyframes —
um vídeo de teste com poucos keyframes virou 1 pedaço em vez dos 3+ esperados, quebrando
silenciosamente o propósito de limitar o tamanho por pedaço. Corrigido recodificando no
corte (`libx264 -preset ultrafast` + `-force_key_frames`), sem custo real de qualidade
composta porque cada pedaço já ia ser recodificado pelo FaceFusion na etapa seguinte de
qualquer jeito. **Achado real #2 (teste de ponta a ponta pelo orquestrador completo, não só
a unidade):** o primeiro pedaço falhou com `Failed to allocate memory for requested buffer
of size 294912` (só 288KB!) mesmo com "8.1GB livres" segundo o Gate 2 — o ComfyUI (processo
GPU separado) tinha 7GB de VRAM presos num checkpoint SDXL de um teste de inpainting anterior,
sem nenhuma relação com o FaceFusion. ComfyUI e FaceFusion são processos independentes, cada
um só enxerga a própria memória — o Gate 2 do `run_vfx.py` mede VRAM livre do sistema todo,
mas isso não garante que o ComfyUI vá *liberar* o que já reservou pra si. Corrigido com
`free_comfyui_vram()`, que chama o endpoint `/free` do próprio ComfyUI (`unload_models` +
`free_memory`) antes de qualquer operação pesada do FaceFusion (face-swap normal, face-swap
em pedaços, remoção de fundo) — tolerante a falha caso o ComfyUI não esteja rodando. Testado
ao vivo: 7499MiB → 811MiB de uso depois da chamada, reteste do face-swap em pedaços com
sucesso total (3/3 pedaços, vídeo final de 10.875s, rosto trocado confirmado até no último
pedaço).

**Fase 8 (pedido do usuário, CONCLUÍDA): TTS / clonagem de voz / dublagem**
XTTS-v2 (Coqui, licença CPML — compatível com uso privado/não-comercial) rodando como script
standalone (`tts_synthesize.py`) num ambiente Conda **separado** (`tts-pipeline`), mesma
lógica do FaceFusion. **Achado real:** o pacote `coqui-tts` (e o node ComfyUI-XTTS que
tentamos primeiro, removido) tem uma inconsistência interna de versão — declara
`transformers>=4.57` mas o código vendorizado do XTTS ainda chama uma função
(`isin_mps_friendly`) removida no `transformers` 5.x. Único intervalo que funciona:
`transformers==4.57.6`. Testado ponta a ponta: fala real em português gerada (24kHz, ~8s),
depois aplicada a um vídeo via `lip_syncer` do FaceFusion (dublagem completa, boca
sincronizada com a voz nova) — confirmado com o arquivo final tendo trilha de áudio nova e
vídeo válido.

**Fase 9 (pedido do usuário, CONCLUÍDA): Remoção de ruído / isolamento de voz**
Correção da Fase 8: `voice_extractor` do FaceFusion não é usável standalone. Solução real:
**Demucs** (Meta AI, `facebookresearch/demucs`, padrão da indústria pra separação de fontes de
áudio), rodando como script standalone (`demucs_separate.py`) num ambiente Conda próprio
(`noise-pipeline`). **Achado real #1:** o torch instalado por padrão via pip (2.6.0+cu124) dá
`CUDA error: no kernel image is available for execution on the device` nessa RTX 5060 Ti —
GPU nova demais pros kernels pré-compilados dessa versão. Corrigido instalando torch
2.12.1+cu130 (mesma versão que já funciona no `vfx-pipeline`/ComfyUI). **Achado real #2:**
precisou também do pacote `torchcodec` extra — o `torchaudio` dessa versão de torch usa ele
por padrão pra salvar áudio, e não vem junto na instalação normal. Testado ponta a ponta com
áudio sintético (fala + ruído rosa misturados): arquivos de saída com hash MD5 diferentes do
original (confirma processamento real, não cópia), voz e ruído separados em arquivos distintos.
Modo `--mode denoise` no `run_vfx.py`, com `--output-instrumental` opcional pra guardar o que
foi removido também. **Escopo deliberado:** o "instrumental"/ruído separado é a "sobra" do
processo, não uma classificação específica de tipo de ruído (vento, chiado, etc.) — serve bem
pra separar voz de música/fundo, é uma abordagem diferente de um denoiser espectral dedicado
(ex.: DeepFilterNet), que ficou fora de escopo por ora.

**Fase 10 (pedido do usuário, CONCLUÍDA): Geração de música**
MusicGen (Meta AI) via node pack `ebrinz/ComfyUI-MusicGen-HF`, rodando dentro do próprio
processo do ComfyUI (não precisou de ambiente Conda separado — ao contrário de TTS/Demucs,
não teve conflito de dependência com o WanVideoWrapper). Modo `--mode music`, novo
`--music-duration`. **Achado real (autocrítica: eu tinha dito "todas as 6 lacunas fechadas"
numa mensagem anterior sem ter testado isso de verdade — só tinha instalado as dependências,
nunca rodei uma geração real; usuário perguntou "só falta o commit?" e essa verificação
revelou o gap):** primeira tentativa falhou com `FileNotFoundError` — o node
`MusicGenAudioToFile` não cria a pasta `ComfyUI/output/audio/` sozinho antes de salvar (bug
do node pack, não nosso). Corrigido com `ensure_comfyui_audio_output_dir()`, chamado antes de
qualquer job de música. **Achado real #2:** esse node não registra o arquivo de saída em
`entry["outputs"]` do jeito que `SaveImage`/`VHS_VideoCombine` fazem (retorna só uma STRING,
sem marcar como saída de UI) — `get_comfyui_output_file()` não serve aqui. Resolvido achando
o arquivo mais recente com o prefixo esperado por data de modificação. Testado ponta a ponta
pelo `run_vfx.py` real: música real gerada (5.94s, pedido de 6s), copiada pro caminho certo.

**Achados de infraestrutura que afetam TUDO que passa pelo FaceFusion (Fases 6/7/8):**
1. **`onnxruntime-gpu` caía pra CPU silenciosamente** (sem erro nenhum no retorno) porque as
   bibliotecas CUDA 12.x instaladas via pip (`nvidia-cublas-cu12` etc) ficam dentro do
   `site-packages`, fora do caminho de busca do linker dinâmico — diferente do `torch`, que
   se auto-registra. Corrigido com `build_facefusion_env()`, que monta um `LD_LIBRARY_PATH`
   explícito. Medido ao vivo: 46s (cold start GPU) → 1.5s (GPU quente) vs os ~2.7s que
   estavam rodando em CPU sem ninguém perceber.
2. **`lip_syncer` (wav2lip) roda em CPU por decisão oficial (não é mais um bug pendente).**
   Falha em CUDA com `CUBLAS failure 3: the resource allocation failed`, mesmo com VRAM de
   sobra (14.9GB livres no teste) e mesmo `LD_LIBRARY_PATH` que funcionou pro
   `background_remover`. **Causa raiz encontrada (investigação aprofundada, sem correção
   limpa disponível):** a RTX 5060 Ti é arquitetura Blackwell,
   compute capability **12.0 (sm_120)** — o pacote oficial `onnxruntime-gpu` do PyPI (testado
   1.26.0 e 1.27.0) não traz kernels cuBLAS pré-compilados pra essa arquitetura ainda (achado
   confirmado via issues abertas no repo oficial `microsoft/onnxruntime`, ex. #26245 e #26177).
   O `background_remover` (modnet) "funciona" provavelmente via compilação JIT de PTX
   (explica o 46s→1.5s: a primeira execução compila, a segunda reaproveita o cache) — o
   `wav2lip` usa uma operação de cuBLAS que aparentemente não tem esse caminho de fallback JIT,
   e falha direto. **Tentativas que NÃO resolveram:** (a) atualizar pra `onnxruntime-gpu==1.27.0`
   — passou a exigir `libcudart.so.13`, e os pacotes pip `nvidia-cuda-runtime-cu13`/
   `nvidia-cublas-cu13`/`nvidia-cufft-cu13`/etc falham ao compilar wheel neste ambiente (só
   `nvidia-cudnn-cu13` instalou, sem trazer o cudart necessário); (b) forçar
   `--execution-providers tensorrt` — o SDK completo do TensorRT não está instalado (só a
   biblioteca do provider), cai pra CPU do mesmo jeito. **Rejeitado de propósito:** existe um
   build não-oficial (`Natfii/onnxruntime-gpu-blackwell`) com kernels sm_120, mas tem 0 estrelas
   e um único commit em fev/2026 sem manutenção — instalar um binário pré-compilado dessa fonte
   seria um risco de segurança real, não vale a pena pra um problema que já tem contorno
   funcional. **Decisão formalizada com o usuário (2026-07-02):** confirmado que não há
   alternativa viável sem trocar esse problema contornável por um risco maior (binário não
   verificado) ou esforço desproporcional (SDK completo do TensorRT sem garantia de
   funcionar; reescrever o wav2lip em PyTorch exigiria patchear o FaceFusion, frágil contra
   atualizações). **CPU é o modo oficial e definitivo** em `build_lip_syncer_command`
   (~136s pra um clipe de 270 frames, validado ponta a ponta duas vezes) — não é mais
   tratado como bug pendente, é uma decisão de arquitetura aceita. Os parâmetros
   `cuda`/`tensorrt` continuam disponíveis na função pra reavaliar no futuro sem precisar
   mudar código, quando o ecossistema onnxruntime/CUDA amadurecer suporte oficial pra
   Blackwell (GPU lançada recentemente).
3. **Correção de um erro meu de pesquisa anterior:** eu tinha dito que `voice_extractor` do
   FaceFusion já cobria "remoção de ruído/isolamento de voz" como processador pronto pra usar.
   **Isso estava errado** — `--processors voice_extractor` não existe nessa versão instalada
   (`error: invalid choice`). `voice_extractor` só existe como componente interno
   (`facefusion/voice_extractor.py`), usado automaticamente pelo `lip_syncer` antes de
   sincronizar os lábios, não como ferramenta standalone pra limpar um áudio qualquer. Função
   `build_voice_extractor_command` removida do código (não correspondia a um recurso real).
   **Correção posterior (Fase 9, ver acima):** essa lacuna foi de fato fechada depois, com o
   Demucs — a frase acima descrevia o estado *antes* da Fase 9 existir, mantida só pelo
   histórico de como o erro foi descoberto e corrigido.

**Fase 11 (pedido do usuário, CONCLUÍDA): Atalhos de terminal e Interface Web**
Duas camadas de acesso não-técnico construídas sobre o `run_vfx.py`, sem duplicar sua
lógica: `vfx_aliases.sh` (funções de shell curtas, `vfx-rosto`/`vfx-video`/etc., chamam o
interpretador certo pelo caminho absoluto do env — nunca `conda activate`/`conda run`,
que tem bug de stdin) e `webui/` (FastAPI + React/TypeScript/Tailwind/Bootstrap),
cobrindo as 10 funções do pipeline pelo navegador via Tailscale
(`100.122.206.41:8299`, nunca `0.0.0.0`, sem `ufw allow`). Documentação operacional
completa fica em `MANUAL_USO.md` (seções 10-11) — não duplicada aqui de propósito, esse
documento cataloga decisões/achados, o manual ensina o uso do dia a dia.

Decisão de arquitetura central: a webui não reimplementa os Gates nem fala direto com
ComfyUI/FaceFusion — chama `run_vfx.py` como subprocesso (mesmo padrão dos atalhos), com
`--auto-approve` e stdin alimentado com `"y"` pro Gate 3 (nunca pulável por design, ver
Fase 3). `run_vfx.py` continua sendo a única fonte de verdade da lógica de segurança.

**Achado real:** o modo `video` não aceitava `--output` (só logava onde o ComfyUI salvou
o resultado, sem copiar pra lugar nenhum) — pré-requisito pra webui conseguir entregar o
vídeo pro navegador de forma confiável. Corrigido reaproveitando `get_comfyui_output_file()`
(já existia, usada por `inpaint`/`removebg`/etc. — só faltava o modo `video` também
capturar o `history_entry` de `wait_for_comfyui_prompt()` e chamá-la). **Achado real #2
(QA no navegador de verdade):** `StaticFiles(html=True)` sozinho não faz fallback de SPA —
navegar direto pra uma sub-rota do React Router (ou dar F5 nela) devolvia 404. Resolvido
com um catch-all em `main.py` que serve `index.html` pra qualquer rota que não seja
`/api/*` e não bata com um arquivo estático real. **Achado real #3 (job real disparado
pela API, não mock):** o `background_remover` do FaceFusion recusa rodar se a extensão de
saída não for idêntica à de entrada (validação própria dele) — `routes_removebg.py`
preserva a extensão original em vez de forçar `.png`.

Exceção arquitetural: **dublagem não tem `--mode` dedicado no `run_vfx.py`** — a webui
(`routes_dub.py`) e o atalho `vfx-dublar` chamam `facefusion.py headless-run
--processors lip_syncer` diretamente, no ambiente Conda do FaceFusion, em vez de passar
pelo orquestrador.

**Auditoria de sistema (2026-07-02) e correções aplicadas na mesma sessão:** uma
auditoria completa (documentação, arquitetura, código, estabilidade) encontrou este
próprio documento desatualizado — contagem de testes errada e uma pendência de "não
commitado" que já não era mais verdade (o repositório já estava commitado e no
`origin/main`) — além de uma lista de lacunas reais de maturidade operacional,
corrigidas em seguida:
1. **`run_vfx.log` sem rotação** → `logging.handlers.RotatingFileHandler` (5MB × 5
   backups); logs crus de boot do ComfyUI (`comfyui_boot.log`/`comfyui_video_mode.log`,
   não passam por `logging.Logger`) truncados quando passam de 5MB.
2. **Debris de 63 scopes `systemd --user` em estado `failed`** (sobra dos testes de
   aceitação do Gate 1, que forçam OOM de propósito) → limpos com `systemctl --user
   reset-failed`.
3. **Sem supervisão de processo pra webui** (crash ou reboot exigia religar na mão) →
   `webui/vfx-webui.service` (`systemd --user`, `Restart=on-failure`), instalável via
   `vfx-web-enable`. **Ativado em produção em 2026-07-03** (exigiu confirmação explícita
   do usuário — é uma mudança de persistência real, o sistema bloqueou a primeira
   tentativa por ter sido feita sem consentimento genuíno, só um timeout). Testado ao
   vivo de verdade: `kill -9` no processo → systemd religou sozinho em poucos segundos
   (`Active: active (running)`, novo PID), sem precisar de intervenção manual. **ComfyUI
   de propósito NÃO ganhou essa supervisão:** o modo `video` já mata e religa o ComfyUI
   dentro da própria jaula de memória (`ensure_comfyui_running_under_jail`) toda vez que
   roda — um serviço com auto-restart brigaria com isso (o systemd tentaria religar o
   processo "solto" bem na hora que o `run_vfx.py` acabou de religar ele "preso"). Pra
   ComfyUI, o botão Ligar/`vfx-ligar` continua sendo o jeito certo.
4. **Upload multipart era salvo em disco antes do Gate 3 ter qualquer chance de checar
   espaço livre, e sem limite de tamanho configurado** → middleware novo em
   `webui/backend/main.py` que checa `Content-Length` e espaço livre em `/` *antes* de
   aceitar o corpo da requisição.
5. **Registro de jobs em memória (`JOBS`) crescia sem limite, uploads/resultados nunca
   eram limpos automaticamente** → `cleanup_old_jobs()` (retenção de 7 dias), rodando
   uma vez na subida do processo (varre sobras de antes de um restart) e depois a cada
   6h.
6. **Duplicação quase idêntica nas 9 rotas de criação de job** → extraídos `finish()`/
   `set_output()`/`save_upload()` únicos em `webui/backend/jobs.py`, reaproveitados por
   todas as rotas.
7. **`tts_synthesize.py`/`demucs_separate.py` sem nenhum teste real** (só havia teste do
   comando que o `run_vfx.py` monta pra chamá-los) → `test_standalone_scripts.py`,
   subprocesso real dos dois scripts, cobrindo os caminhos de validação alcançáveis sem
   precisar da GPU/dos modelos pesados instalados.
8. **Frontend sem nenhum teste automatizado** → Vitest + React Testing Library
   (`webui/frontend/src/**/*.test.tsx`), cobrindo o painel de log/status de job e a
   validação de formulário de pelo menos uma página.

**Achado de compatibilidade (Node 18.19.1 instalado, mais antigo que o que os pacotes
mais recentes esperam):** `create-vite` mais novo, `tailwindcss` v4 e `vitest` v4 falham
em tempo de execução (não só aviso `EBADENGINE`) porque usam `node:util.styleText`,
disponível só a partir do Node ~20. Fixado em versões compatíveis: `create-vite@5`,
`tailwindcss@^3.4`, `vitest@^1.6` + `jsdom@^24`. Atualizar o Node do sistema resolveria
de raiz, mas está fora de escopo por ora (ver regra de não travar atualização de SO,
Fase 0) — revisitar se algum pacote futuro exigir Node mais novo de novo.

**Varredura de segurança (2026-07-03) — 1 achado crítico real, explorado e corrigido ao
vivo:** com a webui já rodando em produção (supervisionada pelo systemd), uma segunda
auditoria com foco em QA/Cybersecurity encontrou e corrigiu 3 falhas, todas confirmadas
por exploração real contra o servidor rodando (não análise teórica) e reexploradas
depois da correção pra confirmar que fecharam:

1. **CRÍTICO — leitura arbitrária de arquivo (path traversal) na rota catch-all da
   SPA.** `main.py` montava `os.path.join(STATIC_DIR, full_path)` com `full_path` vindo
   direto da URL, sem checar `..`. **Exploração real confirmada:** `GET
   /%2e%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/etc/passwd` (pontos url-encoded pra não
   serem normalizados pelo cliente HTTP antes de sair) devolveu o conteúdo real de
   `/etc/passwd` do servidor — qualquer dispositivo na Tailscale conseguiria ler
   qualquer arquivo legível pelo usuário `ap` (potencialmente chaves SSH, código-fonte,
   o próprio baseline de segurança do servidor), sem autenticação nenhuma, já que a
   webui não tem login por decisão (ver seção 11 do `MANUAL_USO.md`). **Corrigido** com
   `os.path.realpath()` + contenção via `os.path.commonpath()` em
   `_safe_static_path()` — só serve o arquivo se ele continuar dentro de `STATIC_DIR`
   depois de resolvido. Reexplorado o mesmo payload após a correção: cai limpo no
   `index.html`, sem vazar nada. Testes de regressão em `test_backend.py`
   (`test_spa_catchall_rejects_*`).
2. **MÉDIO — limite de tamanho de upload contornável.** O middleware de `main.py` só
   olhava o cabeçalho `Content-Length`. **Confirmado ao vivo** (`curl -H
   "Transfer-Encoding: chunked"`) que um cliente pode omitir esse cabeçalho e passar
   direto pela checagem, sem declarar tamanho nenhum. **Corrigido:** `save_upload()`
   (`jobs.py`) agora conta os bytes de verdade enquanto grava o arquivo em disco e
   aborta sozinho (413) ao ultrapassar `MAX_UPLOAD_BYTES`, independente do que o
   cliente declarou ou deixou de declarar no cabeçalho.
3. **BAIXO — crash não tratado (500) com filename `".."`.** `os.path.basename("..")`
   devolve `".."` sem mudança (não tem separador pra remover) — um upload com esse
   filename exato virava `os.path.join(dest_dir, "..")`, apontando pro diretório pai, e
   `open(..., "wb")` derrubava com `IsADirectoryError` não tratada. **Não é um escape
   de verdade** (só sobe um nível, ainda dentro da própria árvore de
   `webui_uploads/`), mas é entrada não validada quebrando a aplicação — confirmado ao
   vivo via `journalctl` (traceback real capturado). **Corrigido:** `save_upload()`
   rejeita explicitamente `""`/`"."`/`".."` com 400 limpo antes de chegar no `open()`.

**Observação registrada, não corrigida (fora do modelo de ameaça atual):** não há
limite de jobs simultâneos — qualquer dispositivo na Tailscale pode disparar vários
jobs pesados ao mesmo tempo (os Gates do `run_vfx.py` ainda protegem RAM/VRAM/disco
individualmente, mas nada impede várias execuções concorrentes). Consistente com a
decisão já tomada de não ter autenticação (mesmo padrão do ComfyUI/FaceFusion Gradio) —
não é uma falha nova, só um lembrete caso um limite de concorrência vire prioridade no
futuro.

Serviço reiniciado (`systemctl --user restart vfx-webui.service`) após cada uma das 3
correções, com reexploração ao vivo confirmando o fechamento antes de seguir pra
próxima. 109 testes no total após esta rodada (103 + 6 novos: 3 de path traversal + 2 de
filename inválido + 1 de limite via streaming, ver tabela abaixo).

**Auditoria multi-perspectiva (2026-07-03) — código, SO, QA/segurança e uso
profissional, cada uma com nota própria — e correções aplicadas em seguida:**
1. **`LICENSE`** adicionado — todos os direitos reservados (uso privado, decisão do
   usuário; MIT/Apache permitiria redistribuição, o que contradiz o objetivo do
   projeto).
2. **`requirements/`** — `pip freeze` real dos 5 ambientes Conda (`vfx-pipeline` 190
   pacotes, `facefusion-pipeline` 75, `tts-pipeline` 110, `noise-pipeline` 62,
   `webui-pipeline` 44) + `webui/backend/requirements.txt`. Antes, recriar qualquer
   ambiente exigia garimpar comandos `pip install` na prosa deste documento.
3. **`CHANGELOG.md`** — histórico por data/versão, reconstruído do `git log` real.
4. **`.github/workflows/test.yml` + `.pre-commit-config.yaml`** — CI e lint local
   (`ruff`/`eslint`, só detecção de erro, sem reformatar o código com TAB do projeto).
   Transparência importante: o CI roda de verdade (e tem que passar) só o que é
   portável (frontend inteiro, scripts standalone) — o resto de `test_run_vfx.py` roda
   como "melhor esforço" porque depende de GPU/ambientes Conda/sessão `systemd --user`
   deste servidor especifico, que um runner genérico não tem.
5. **Validação de assinatura real do arquivo no upload** (achado QA/Cybersecurity,
   pedido explícito de não exagerar na blindagem) — biblioteca `filetype` (pura
   Python), rejeita com mensagem amigável qualquer upload cujo conteúdo real não seja
   reconhecido como imagem/vídeo/áudio, antes de chegar no FFmpeg/FaceFusion com um
   erro técnico cru. Verificação pelo conteúdo, não pelo nome/Content-Type declarado.
6. **`run_vfx.py` dividido em 7 módulos** (achado Engenheiro de Software: monólito de
   ~1500 linhas) — `vfx_config.py`, `vfx_core.py`, `vfx_gates.py`, `vfx_comfyui.py`,
   `vfx_workflows.py`, `vfx_facefusion.py`, `vfx_ffmpeg.py`. `run_vfx.py` caiu pra 405
   linhas, vira só o orquestrador, reexportando tudo dos módulos pra `from run_vfx
   import X` continuar funcionando sem mudança em quem já consome (atalhos `vfx-*`,
   webui, testes). **Achado real da própria migração:** os testes que usavam
   `monkeypatch.setattr("run_vfx.confirm", ...)` pararam de funcionar — `confirm()`
   agora é *chamado* de dentro de `vfx_gates.py`, então o patch precisa mirar
   `vfx_gates.confirm` (onde o nome é resolvido em tempo de execução), não
   `run_vfx.confirm` (que só teria efeito se a chamada também estivesse em
   `run_vfx.py`). Mesma lógica pra `get_vram_free_mb`/`get_disk_free_gb`/etc. Já os
   patches de `ensure_comfyui_running_under_jail`/`submit_comfyui_prompt`/
   `wait_for_comfyui_prompt` continuam em `run_vfx.X` sem mudança, porque essas
   chamadas ficam dentro de `orchestrate()`, que continua em `run_vfx.py`. Testado:
   62 testes de `test_run_vfx.py` passando sem alteração de comportamento (só de
   *onde* cada patch mira), e um job real (`removebg`) de ponta a ponta pela API
   depois da divisão.
7. **`--mode upscale` novo** (achado do perfil "uso profissional/edição de IA": não
   havia upscale standalone pra fotos antigas — só o de dentro do modo `video`,
   embutido no fluxo de geração). Reaproveita o mesmo `RealESRGAN_x4plus.pth` já
   baixado, via os nodes nativos do ComfyUI `UpscaleModelLoader` +
   `ImageUpscaleWithModel` (confirmados ao vivo no `/object_info` antes de implementar).
   Aceita imagem (`LoadImage`/`SaveImage`) ou vídeo (`VHS_LoadVideo`/`VHS_VideoCombine`,
   detectado pela extensão via `is_video_file()`) — mesmo grafo, sem gerar nada novo, só
   amplia 4x o que já existe (custo baixo: nenhuma dependência nova, modelo de 64MB já
   em disco). Exposto também na webui (`POST /api/jobs/upscale`, página "Aumentar
   Resolução" no dropdown Imagem). Testado ao vivo ponta a ponta duas vezes: direto via
   CLI (1024×1024 → 4096×4096) e depois pela própria webui em produção (imagem
   256×256 → 1024×1024 real, sem `--dry-run`, confirmado pelo tamanho do arquivo
   baixado via `GET /api/jobs/{id}/output`). 6 testes novos em `test_run_vfx.py`
   (workflow de imagem/vídeo, detecção de extensão, validação de `--target`/`--output`)
   e 3 em `test_backend.py` (arquivo faltando, dry-run com imagem, dry-run com vídeo
   passando `fps`).

8. **Comparação antes/depois na webui** (achado do perfil uso profissional) —
   `BeforeAfterCompare.tsx`, componente reaproveitado nas 4 páginas que editam algo já
   existente (Trocar Rosto, Remover Fundo, Editar Imagem, Aumentar Resolução), lado a
   lado, usando `URL.createObjectURL()` no arquivo original que já está no navegador
   (sem re-upload). Não entra nas páginas de geração do zero (Gerar Vídeo, Música),
   onde não existe "antes". Achado colateral corrigido no processo:
   `RemoveBgPage.tsx` sempre mostrava o resultado como `<img>`, mesmo com alvo em
   vídeo — corrigido junto, já que a comparação precisa detectar o tipo certo pra
   funcionar.
9. **Aviso "modo rascunho, não produção"** direto na página "Gerar Vídeo" da webui
   (além do reforço já feito no `MANUAL_USO.md`, seção 0 e 4.4) — deixa explícito o
   teto de 720×720/poucos segundos e aponta pra "Trocar Rosto" (produção) ou "Aumentar
   Resolução" (upscale de algo pronto) quando o objetivo é qualidade final.
10. **Processamento em lote** (achado do perfil uso profissional) —
    `BatchJobQueue.tsx`, novo componente reaproveitado nas páginas "Aumentar Resolução"
    e "Remover Fundo": selecionar mais de um arquivo no campo de upload entra em modo
    lote automaticamente (o fluxo de um único arquivo não muda em nada). Processa **em
    fila sequencial, não em paralelo** — decisão deliberada, já que não há limite de
    concorrência entre jobs e a GPU é compartilhada com o Ollama; rodar vários jobs
    pesados ao mesmo tempo disputaria VRAM sem coordenação. Cada arquivo da fila tem
    seu próprio painel de log/status/antes-depois/download, e um arquivo que falhar
    (ex.: tipo de arquivo inválido) não trava o resto da fila. Testado ao vivo pela
    webui em produção com 2 arquivos reais — confirmado pelos timestamps do log que o
    2º job só começou depois do 1º terminar (sequencial de verdade, não só na
    aparência).
11. **Mensagens de erro amigáveis** (achado do perfil uso profissional/iniciante) —
    `src/lib/friendlyErrors.ts` reconhece os padrões de erro mais comuns nos logs
    (Gates 1/2/3 negados, código de saída 137/-9 de OOM-kill, timeout do ComfyUI, erro
    de execução do ComfyUI) e mostra uma frase simples em português acima do log
    técnico — que continua completo e visível, nada é escondido. Erros sem padrão
    reconhecido não mostram nenhuma mensagem extra (não arrisca um palpite errado
    sobre a causa).
12. **`webui/frontend/e2e/`** (achado das perspectivas de Código e QA) — formaliza a
    verificação visual manual (Chrome headless real) que antes era um script
    descartável criado e apagado na hora. Cobre rotas estáticas (regressão de layout)
    e um fluxo real de upscale de ponta a ponta (confirma visualmente a comparação
    antes/depois). Deliberadamente fora do CI/pre-commit — ferramenta manual.
13. **`--blocks-to-swap` (avançado, opcional) no modo `video`** — experimento real de
    velocidade pedido pelo usuário, motivado por ele nunca rodar o Ollama e o
    `ap-ai-studio` ao mesmo tempo (fecha um antes de abrir o outro). **Correção de uma
    suposição anterior:** o block swap do Wan2.2 **não existe principalmente por causa
    do Ollama** — os dois experts MoE (HighNoise+LowNoise) somam ~19.3GB de peso
    sozinhos, mais que os 16GB da RTX 5060 Ti, então algum grau de offload pra CPU é
    obrigatório mesmo com a VRAM inteira livre. Medido ao vivo, comparando
    `blocks_to_swap` (padrão `20`) contra valores menores, sempre no mesmo hardware:

    | `blocks_to_swap` | Resolução | Frames | Tempo | Pico VRAM |
    |---|---|---|---|---|
    | 20 (padrão) | 320×320 | 17 | 126,4s | 7,65GB |
    | 5 | 320×320 | 17 | 84,2s (-33%) | 9,76GB |
    | 0 | 320×320 | 17 | 78,2s (-38%) | 10,66GB |
    | 5 | 480×480 | 17 | 147,4s | 9,92GB |
    | 5 | 480×480 | 81 (~5s) | 618,8s | 11,87GB |
    | 5 | 480×480 | **161 (~10s, padrão real)** | **travou o ComfyUI (OOM real, processo morreu, precisou religar via `/api/comfyui/start`)** | — |

    **Conclusão:** `blocks_to_swap=5` dá ~33-38% de ganho real de velocidade e é seguro
    até por volta de 80 quadros em 480×480, mas **não escala** pro `--num-frames`
    padrão (161) na mesma resolução — o crescimento de VRAM com mais quadros não é
    linear (a extrapolação a partir dos pontos menores previa ~14GB de pico aos 161
    quadros; na prática estourou os 16GB antes disso). Por isso o **padrão de
    `blocks_to_swap` continua `20`** (seguro, já usado em produção) — a opção mais
    rápida foi exposta como flag avançada (`--blocks-to-swap N`), não como novo
    padrão, com aviso explícito no `--help` e no `MANUAL_USO.md` sobre o risco em
    renders longos.
14. **ControlNet Depth no modo `inpaint`** (`--use-depth-controlnet`, opcional, achado
    do perfil uso profissional, autorizado explicitamente pelo usuário após ver as
    opções) — guia a edição por um mapa de profundidade (MiDaS) da própria imagem
    original, via ControlNet SDXL, além da máscara manual. Instalação real: pacote de
    nós `comfyui_controlnet_aux` (Fannovel16, repositório nomeado e autorizado pelo
    usuário antes do clone — código de terceiros que o ComfyUI carrega
    automaticamente) em `ComfyUI/custom_nodes/`, dependências extras instaladas no
    `vfx-pipeline` (scikit-image, mediapipe, fvcore, omegaconf, onnxruntime-gpu, entre
    outras — `torch`/`torchvision` não foram tocados, confirmado intacto depois:
    `2.12.1+cu130`, CUDA disponível) + modelo `controlnet-depth-sdxl-1.0.safetensors`
    (2,4GB, `diffusers/controlnet-depth-sdxl-1.0`, fp16) em
    `models_hub/models/controlnet/`. Novo `build_inpaint_workflow(use_depth_controlnet=
    True, controlnet_strength=0.6)` adiciona 3 nodes (`MiDaS-DepthMapPreprocessor` →
    `ControlNetLoader` → `ControlNetApplyAdvanced`) e realimenta o `KSampler` com o
    condicionamento resultante; sem a flag, o grafo fica byte-a-byte igual ao de antes
    (nenhum node novo, nenhuma mudança de comportamento). Também exposto na webui
    (checkbox "Avançado" em "Editar Imagem"). Testado ao vivo, três vezes:
    (1) CLI com a foto oficial de exemplo do FaceFusion, comparando com/sem a flag no
    mesmo prompt — pipeline roda sem erro nas duas (~12s sem, ~15s com, overhead real
    mas pequeno); honestamente, a máscara usada nesse teste caiu numa região de pouca
    variação de profundidade (borda do cabelo/fundo desfocado), então a diferença
    visual entre com/sem ControlNet não ficou dramaticamente clara nesse caso
    específico — o pipeline funciona, mas esse teste não foi o melhor showcase do
    valor da feature em si;
    (2) webui em produção, job real via `POST /api/jobs/inpaint` com
    `use_depth_controlnet=true`, concluído com sucesso (`status: done`,
    `returncode: 0`);
    (3) teste melhor-escolhido, usando a foto de amostra `coffee` do `scikit-image`
    (xícara sobre mesa de madeira, perspectiva real e nítida — já instalada como
    dependência do `comfyui_controlnet_aux`, sem precisar de foto do usuário nem
    download da internet), mascarando o canto de fundo (mesa recuando na perspectiva)
    e comparando o mesmo prompt com/sem a flag: diferença real e visível, porém
    modesta — o grão da madeira na região editada ficou mais alinhado com a
    perspectiva da mesa na versão com ControlNet, mas a linha de costura da máscara
    continua visível nas duas versões (ControlNet ajuda a manter a coerência
    estrutural da cena, não elimina sozinho artefato de blend na borda da máscara).
15. **Correção da costura visível na borda da máscara do `inpaint`** (achado real do
    item #14, item #3 do teste) — duas causas reais, corrigidas juntas, sempre ativas
    (não são flag opcional, é correção de qualidade):
    - `FeatherMask` suaviza a borda da máscara (parâmetro novo `feather_amount`,
      padrão `24px`) antes de virar latente — transição gradual em vez de corte duro.
    - `ImageCompositeMasked` cola o resultado gerado de volta na **imagem original**,
      não na imagem inteira redecodificada pelo VAE — a área fora da máscara deixa de
      sofrer a leve deriva de cor/textura que o round-trip encode→sample→decode do
      VAE introduzia em toda a imagem, mesmo na parte "mantida".
    Verificado com números reais, não só visualmente: comparando pixel a pixel uma
    região bem longe da máscara (foto `coffee` do `scikit-image`) antes e depois do
    resultado — **diferença média de pixel caiu pra 0.0, diferença máxima 0** (era uma
    deriva pequena mas real antes). A costura visual também ficou mais suave no mesmo
    teste. Ambos os nodes (`FeatherMask`, `ImageCompositeMasked`) já existem no
    ComfyUI core — nenhuma dependência nova.
16. **Gate 1 (jaula de memória) não era aplicado ao ComfyUI em 3 dos 4 modos que o
    usam** (achado real da auditoria final, pós-commit/push) — investigando por que
    `vfx-webui.service` mostrava 14GB de memória no `systemctl status`, descobri que o
    ComfyUI ligado pela webui (`POST /api/comfyui/start`, em `routes_status.py`) roda
    como subprocesso direto do FastAPI, **sem nenhum `systemd-run --scope`** — nasce
    dentro do próprio cgroup do `vfx-webui.service`, não num scope isolado. Isso por si
    só é esperado (essa rota nunca teve jaula, é só um "liga rápido" pra abrir a
    interface). O problema real: dos 4 modos do `run_vfx.py` que dependem do ComfyUI
    (`video`, `inpaint`, `music`, `upscale`), **só o `video`** chamava
    `ensure_comfyui_running_under_jail()` (que verifica se já está no scope certo e,
    se não estiver, mata e religa preso). Os outros 3 só chamavam
    `poll_comfyui_system_stats()` — que espera o ComfyUI responder, mas não verifica
    nem aplica jaula nenhuma. Ou seja: o Gate 1 calculava um limite de memória e até
    pedia confirmação nesses 3 modos, mas **esse limite nunca chegava a valer** pro
    processo que faz o trabalho pesado de verdade. Se o ComfyUI tivesse sido ligado
    pela webui (o caminho mais comum no dia a dia) e o usuário rodasse `inpaint`/
    `music`/`upscale` na sequência, o servidor inteiro ficava exposto a um OOM sem
    a proteção que o Gate 1 existe pra dar — exatamente o cenário de thrashing que a
    jaula foi criada pra evitar (ver Fase 3B/vfx_comfyui.py).

    **Corrigido:** as 3 chamadas de `poll_comfyui_system_stats()` viraram
    `ensure_comfyui_running_under_jail()` (que já inclui a espera de prontidão
    internamente, então nenhum comportamento externo muda). 3 testes novos confirmam
    que cada um dos 3 modos chama a jaula, não só o poll — antes desta correção,
    nenhum teste pegava essa lacuna porque os mocks nunca verificavam qual das duas
    funções cada modo realmente chamava.

    **Verificado ao vivo, no cenário exato do achado:** com o ComfyUI já rodando sem
    jaula (aninhado em `vfx-webui.service`, confirmado via `systemctl status`), rodei
    `--mode upscale` de verdade — o log mostrou `"Encerrando instancia do ComfyUI fora
    da jaula (porta 8288 ocupada) antes de reiniciar presa"` seguido de `"ComfyUI
    reiniciado sob jaula de memoria (scope=vfx-comfyui-video.scope, MemoryMax=24G...)"`.
    Confirmado depois via `systemctl status vfx-comfyui-video.scope`: processo isolado
    no scope certo, `Memory: ... (max: 24.0G ...)` aplicado de verdade pelo systemd.
    `vfx-webui.service` voltou a mostrar memória normal (o "14GB" de antes era quase
    todo `file` cache reaproveitável do próprio processo, não `anon` real - confirmado
    via `memory.stat` do cgroup, `anon: 44MB` - não era um vazamento, mas a
    investigação valeu a pena porque revelou o achado real acima).

    Limpeza cosmética junto: `vfx-comfyui-video.scope` aparecia como `failed` no
    `systemctl --user list-units --all` (resíduo de uma sessão anterior) — resolvido
    com `systemctl --user reset-failed`.
17. **Processamento em lote estendido pra "Trocar Rosto" e "Limpar Áudio"** — o
    `BatchJobQueue.tsx` (item #10 acima) só cobria Aumentar Resolução/Remover Fundo
    (1 arquivo entra, 1 sai, imagem/vídeo). Avaliei estender pros outros modos e decidi
    o escopo assim:
    - **Trocar Rosto:** viável — a foto de origem (rosto) fica fixa, só o alvo varia
      em lote. Exigiu generalizar `BatchJobQueue` (ver abaixo), já que a origem não é
      um dos arquivos do lote.
    - **Limpar Áudio:** viável, formato igual ao Upscale/RemoveBg (1 arquivo, 1 saída
      — só que áudio, não imagem/vídeo).
    - **Editar Imagem (inpaint):** avaliado e descartado por ora — cada item do lote
      precisaria de 2 arquivos pareados (foto + máscara), e a UI de seleção múltipla
      de hoje não sabe casar "foto 3" com "máscara 3". Exigiria uma UI de pares, não
      só um campo de arquivo múltiplo — fora de escopo desta rodada.
    - **Gerar Vídeo / Música:** avaliado e descartado — já são os modos mais lentos do
      pipeline (minutos por item); enfileirar vários pioraria a espera sem ganho
      prático claro.
    - **Voz (TTS) / Dublagem:** avaliado e descartado — TTS varia principalmente por
      **texto**, não por arquivo (a amostra de voz é fixa, não o que varia em lote);
      não se encaixa no formato "vários arquivos" do componente sem redesenhar a UI.
      Dublagem tem o mesmo problema de pares do inpaint (áudio + vídeo por item).
    - **Masterizar:** não se aplica — sempre um par específico (vídeo processado +
      original correspondente), não um "lote de arquivos soltos".

    **`BatchJobQueue.tsx` generalizado:** trocou os props `isVideo`/`resultLabel`/
    `jobOutputUrl` (que assumiam sempre antes/depois de imagem via
    `BeforeAfterCompare`) por uma única função `renderResult(file, job)` fornecida por
    cada página — o componente cuida só da fila/sequenciamento, cada página decide
    como mostrar seu próprio resultado (antes/depois de imagem no Upscale/RemoveBg/
    FaceSwap, player de áudio + download no Limpar Áudio). Testado ao vivo: 2 jobs
    reais de Trocar Rosto (mesma origem, alvos diferentes) via `curl`, sequenciais,
    ambos concluídos; verificação visual real com Chrome headless confirmando a fila
    de Trocar Rosto renderizando certo no navegador (2/2 concluídos, log e badges
    corretos por item). **Fechamento posterior:** o lote de Limpar Áudio também foi
    verificado visualmente (não só por teste unitário) — 2 áudios reais (tons puros
    gerados com `wave`/`struct`, sem depender de arquivo externo), processados sem
    `--dry-run` de verdade (pra ver o player de áudio renderizado, não só o "na
    fila"), confirmando "Voz isolada" + "Resto" com botão de baixar em cada item.
18. **`friendlyErrors.ts` estendido pras outras 5 funções do pipeline** — cobria só
    Gates/OOM/ComfyUI; agora também FaceFusion (troca de rosto), remoção de fundo,
    TTS, Demucs (limpar áudio), FFmpeg (masterização) e modelo/arquivo ausente
    (`FileNotFoundError` de `.safetensors`/`.pth`/`.ckpt`/`.bin`). Os 5 padrões novos
    de "ferramenta falhou" usam o formato **exato** dos logs reais — confirmado via
    `grep 'logger.error(f"' run_vfx.py` antes de escrever cada regex, não um palpite
    sobre como a mensagem provavelmente seria. Mensagens propositalmente genéricas
    (ex.: "verifique o formato do arquivo") em vez de apontar uma causa específica que
    eu não tenho como confirmar de antemão (ex.: não afirmo que foi o filtro de idade
    do FaceFusion que rejeitou um rosto, porque não tenho o texto exato desse cenário
    específico) — mantém a regra de não inventar. Verificação: 7 testes novos com o
    texto de log real de cada cenário. **Fechamento posterior — forcei um erro real
    de verdade** (não só o teste unitário com texto copiado do grep): rodei um
    `--mode faceswap` de verdade com uma foto sem rosto nenhum (cor sólida) como
    origem. O FaceFusion falhou de verdade (`"[FACEFUSION.CORE] no source face
    detected!"`, código de saída 1) e a mensagem amigável apareceu certa na tela, ao
    vivo, pela webui real (não simulação) — confirmado por captura de tela. Essa é a
    diferença entre "o regex bate com o texto que eu acho que vai aparecer" e "o
    regex bate com o texto que apareceu de verdade numa falha genuína".
19. **`MANUAL_USO.md` estava desatualizado em 6 pontos, achado ao responder "está tudo
    atualizado?"** — todos causados pela própria correção da jaula de memória (achado
    #16): a seção 1 dizia "4 ambientes Conda" (faltava o `webui-pipeline`, são 5); a
    seção 2.2 dizia que `inpaint`/`music` só esperavam o ComfyUI responder (sem ligar
    sozinhos) e nem citava `upscale`; as seções 4.6/4.11/4.13 diziam "pré-requisito:
    ComfyUI precisa estar rodando"; a seção 7 (cheat sheet) tinha a mesma anotação
    errada; a seção 9 dizia "só o modo `video` mata e religa o ComfyUI"; a seção 11
    dizia que Editar Imagem/Música "continuam exigindo" o ComfyUI ligado. Todos
    corrigidos, e a correção foi **verificada ao vivo de novo** (parei o ComfyUI,
    rodei `--mode music`, ele religou sozinho do zero — bate com o texto corrigido).
    O próprio componente `ComfyUINotice.tsx` da webui tinha o mesmo texto/comentário
    desatualizado ("este modo precisa do ComfyUI ligado") — corrigido junto.

    **Dois achados adicionais de código, corrigidos em seguida:**
    - `--mode upscale` nunca tinha ganhado um atalho de terminal (`vfx-upscale`),
      diferente de todos os outros modos — adicionado em `vfx_aliases.sh`, seguindo o
      padrão de `vfx-semfundo`. Testado ao vivo: `vfx-upscale foto.jpg saida.jpg`
      rodou de ponta a ponta, reaproveitando o scope já jailado, resultado 64×64 →
      256×256 (4x confirmado).
    - `vfx-editar`/`vfx-musica` ainda tinham uma checagem redundante
      (`_vfx_ensure_comfyui`, um prompt `[Y/n]` no bash) que ligava o ComfyUI **sem
      jaula** antes de chamar o Python — que aí detectava a falta de jaula e matava/
      religava tudo de novo, **presa**, gastando ~5-10s à toa. Removida (junto com a
      função `_vfx_ensure_comfyui`, que ficou sem nenhum outro uso) — o Python já
      resolve isso sozinho e silenciosamente, mesmo comportamento de `vfx-video`/
      `vfx-anima` (que nunca tiveram essa pergunta extra). Testado ao vivo: `vfx-editar`
      com o ComfyUI já ligado rodou direto, sem nenhuma pergunta a mais do bash (só o
      Gate 3, que é sempre obrigatório).

**Nota registrada, não uma ação (achado do perfil SO/DevOps + uso profissional):** o
teto de `MAX_VIDEO_WIDTH`/`MAX_VIDEO_HEIGHT` = 720×720 em `vfx_config.py` existe porque
é o que cabe com folga nos 16GB de VRAM da RTX 5060 Ti atual sem risco de OOM durante a
geração do zero (modo `video`) — não é um limite arbitrário de software. Se a GPU for
trocada por uma com mais VRAM no futuro, vale revisitar esse valor (e os parâmetros de
block-swap/offload associados) pra aproveitar a capacidade nova; até lá, o novo
`--mode upscale` já cobre o caso de "eu queria mais resolução" pra fotos/vídeos prontos
sem precisar mexer nesse teto.

**Limpeza de disco (2026-07-03, a pedido do usuário):** ver a entrada correspondente na
tabela de referência rápida abaixo (`Disco`) — removidos `Battle.net`/`World of
Warcraft` (123GB) e dados de usuário do Lutris (3GB) do mesmo NVMe compartilhado com o
SO, liberando 126GB (de 105GB pra 230GB livres). Nada do `ap-ai-studio` foi tocado.

---

**Referência rápida (consolidada Fases 0-11, verificada ao vivo em 2026-07-03, pós-auditoria multi-perspectiva + `--mode upscale`):**
Esta seção não substitui o histórico acima — é só um resumo de "onde as coisas estão"
pra não precisar garimpar os achados de cada fase toda vez.

*Ambientes Conda (5, isolados por conflito real de dependência, não por preferência):*
| Ambiente | Usado por | Motivo do isolamento |
|---|---|---|
| `vfx-pipeline` | ComfyUI (T2V/I2V, inpaint, remoção de fundo via node, música) | Base — torch 2.12.1+cu130 |
| `facefusion-pipeline` | FaceFusion (`faceswap`, `removebg`, `lip_syncer`/dublagem) | `numpy==2.2.1` fixo, colide com ComfyUI |
| `tts-pipeline` | `tts_synthesize.py` (XTTS-v2) | exige `transformers==4.57.6` exato |
| `noise-pipeline` | `demucs_separate.py` (Demucs) | precisa torch 2.12.1+cu130 + `torchcodec` |
| `webui-pipeline` | `webui/backend/` (FastAPI/uvicorn) | Só `fastapi`/`uvicorn`/`aiohttp` — não precisa do torch pesado do `vfx-pipeline` |

*Modos do `run_vfx.py` (`--mode`, ver `build_parser()` em `run_vfx.py:386`):*
| `--mode` | O que faz | Flags relevantes |
|---|---|---|
| `faceswap` | Troca de rosto (FaceFusion, modo referência); com `--chunk-seconds`, processa vídeo longo em pedaços | `--source --target --output [--chunk-seconds N]` |
| `video` | Geração T2V ou I2V (Wan2.2, GGUF Q4_K_M) — qualidade "rascunho", 720×720 no máximo | `--prompt [--source-image] [--width --height --num-frames]` |
| `master` | Costura final CFR + bt709, remapeia áudio/legendas do original pro vídeo processado | `--original --processed-video --output [--fps]` |
| `inpaint` | Edição de imagem com máscara manual (SDXL inpainting) | `--source-image --mask-image --output [--prompt]` (sem `--prompt`: aviso, não erro) |
| `removebg` | Remoção de fundo (FaceFusion `background_remover`) | `--target --output` |
| `tts` | Síntese de fala / clonagem de voz (XTTS-v2) | `--text --output (--speaker \| --speaker-wav obrigatório) [--language]` |
| `denoise` | Isola voz / separa de ruído-fundo (Demucs) | `--target --output [--output-instrumental]` |
| `music` | Geração de música (MusicGen) | `--prompt --output [--music-duration]` |
| `upscale` | Aumenta resolução 4x de foto/vídeo pronto (Real-ESRGAN, standalone) | `--target --output [--fps]` (fps só usado se `--target` for vídeo) |

*Modelos baixados (`/home/ap/ai_pipeline/models_hub/models/`, ~42.6GB total confirmado por `du -h` em 2026-07-02):*
- `diffusion_models/`: Wan2.2 T2V-A14B e I2V-A14B, GGUF Q4_K_M, HighNoise+LowNoise cada (4 arquivos, ~9GB cada, ~36GB)
- `text_encoders/umt5-xxl-enc-fp8_e4m3fn.safetensors` (6.3GB, compartilhado T2V/I2V)
- `vae/Wan2.1_VAE.safetensors` (243MB)
- `frame_interpolation/rife_v4.25.safetensors` (22MB)
- `upscale_models/RealESRGAN_x4plus.pth` (64MB)
- `checkpoints/sd_xl_base_1.0_inpainting_0.1.safetensors` (6.5GB)
- `controlnet/controlnet-depth-sdxl-1.0.safetensors` (2,4GB, novo em 2026-07-03 — ver
  achado #14 acima). Pesos do pré-processador MiDaS baixados automaticamente pelo
  `comfyui_controlnet_aux` no primeiro uso (não contabilizados aqui ainda).
- Disco (`/`, NVMe compartilhado com o SO): ~224,9GB livres de 468GB em 2026-07-03 (após
  o ControlNet) — subiu de 105GB pra 230GB depois que o usuário pediu a remoção do
  Battle.net/World of Warcraft (`/home/ap/Games/battlenet`, 123GB) e do Lutris (dados de
  usuário, 3GB) do mesmo disco, e caiu ~5GB de volta com o download do ControlNet + libs.
  Nada relacionado ao ap-ai-studio foi tocado na limpeza de disco. O pacote flatpak do
  Lutris em si (não os dados de usuário) continua instalado a nível de sistema — remover
  exige `sudo`, que este agente não tem configurado sem senha; comando pra o usuário
  rodar se quiser completar: `sudo flatpak uninstall net.lutris.Lutris`.

*Testes (175 no total, todos passando, verificado ao vivo em 2026-07-03 pós mensagens de erro amigáveis estendidas):*
| Suite | Testes | O que cobre |
|---|---|---|
| `test_run_vfx.py` | 77 | Gates, builders de comando/workflow, orquestração — mix de unitários e funcionais reais (ffmpeg de verdade cortando vídeo, OOM-kill real via `systemd-run`). Roda contra os 7 módulos `vfx_*.py` via `run_vfx.py` (reexport). Inclui 6 testes do `--mode upscale`, 2 do `--blocks-to-swap`, 3 do ControlNet Depth no inpaint, 1 do feathering/composição da máscara e 3 confirmando que `inpaint`/`music`/`upscale` usam a jaula de memória do ComfyUI (não só o poll). |
| `test_standalone_scripts.py` | 6 | `tts_synthesize.py`/`demucs_separate.py` via subprocesso real (validação de argumentos, sem precisar da GPU/modelos) |
| `webui/backend/test_backend.py` | 44 | Contrato de API, jobs reais com `--dry-run` via subprocesso real, middleware de limite de upload/disco, limpeza automática, path traversal na SPA, validação de filename, limite de upload via streaming, validação de assinatura real do arquivo, job "fantasma" em upload multi-arquivo, rota `/jobs/upscale`, rota `/jobs/inpaint` com ControlNet |
| `webui/frontend/src/**/*.test.tsx` | 48 | Vitest + React Testing Library — painel de log/status de job, validação de formulário, `BeforeAfterCompare.tsx` isolado (4 testes), estado "job concluído" nas 4 páginas com antes/depois (14 testes), `friendlyErrors.ts` (14 testes, 7 originais + 7 novos de FaceFusion/removebg/TTS/Demucs/FFmpeg/modelo ausente) + mensagem amigável no `JobLogPanel` (2 testes), `BatchJobQueue.tsx` isolado (4 testes, incluindo a nova API `renderResult`) + modo lote em `UpscalePage`/`RemoveBgPage`/`FaceSwapPage` (3 testes) + `DenoisePage.tsx` novo (3 testes, incluindo lote), checkbox de ControlNet no `InpaintPage` (1 teste) |

Verificação visual manual formalizada em `webui/frontend/e2e/` (Chrome headless real,
fora do CI/pre-commit) — substitui o script descartável usado na primeira verificação
visual desta sessão.

Checagem de tipo leve (`mypy --ignore-missing-imports`, hook `pre-commit` não-bloqueante,
achado de auditoria) cobre todo o Python do projeto (`run_vfx.py` + 7 módulos `vfx_*.py`
+ `webui/backend/*.py` + os dois arquivos de teste do orquestrador) e está limpa —
achou e corrigiu 4 pontos de `Optional` não comprovado em tempo de execução
(`vfx_ffmpeg.py`, `webui/backend/jobs.py`, `webui/backend/routes_jobs.py`).

*Estado do repositório:* commitado e enviado (`origin/main`) em 3 commits desta sessão
(`0ccf2b0`, `e4aa067`, e o próximo com os achados #19 acima) — sempre com autorização
explícita do usuário antes de cada `git push`, nunca por conta própria.

[FIM DO PROMPT - ARQUITETURA FAIL-SAFE]
