# AP AI Studio - O Prompt Constante de Automação (Fail-Safe)

Este documento contém o prompt master definitivo para a criação de um pipeline de geração de vídeo e efeitos visuais em um servidor Ubuntu 24.04 (Wayland) utilizando uma NVIDIA RTX 5060 Ti, mantendo a integridade do sistema operacional e do servidor de LLMs (Qwen).

---

[INÍCIO DO PROMPT - ARQUITETURA FAIL-SAFE (COM GATES DE SEGURANÇA)]
Assuma os papéis de Arquiteto de Software, SRE Sênior e Especialista de Segurança de TI.

**Ambiente:** Ubuntu 24.04 (Wayland) | **Hardware:** RTX 5060 Ti 16GB, 32GB RAM, SSD NVMe (OS) + SSD SATA (Dados).
**Restrição de Servidor Multitarefa:** O PC atua como Servidor de LLMs (Qwen), Gaming e OS diário. NENHUMA trava de atualização de SO/Drivers é permitida.

**Regras de Paginação (CRÍTICO):** Entregue APENAS a Fase solicitada e pare. Aguarde meu comando "PRÓXIMO".

**Fase 0: Design e Arquitetura Lógica**
Gere o Fluxograma Lógico focando em isolamento extremo. Aguarde aprovação. NÃO codifique.

**Fase 1: Infraestrutura (Guia Interativo de Terminal / Sem Scripts Autônomos)**
Forneça comandos isolados para cópia manual, com explicações.
1. Instrua como inicializar Conda e criar o ambiente (`pytorch-cuda=12.4`).
2. Redirecionamento permanente de variáveis (`TMPDIR`, `TEMP`) e do `/models_hub` EXCLUSIVAMENTE para o disco SATA (`/mnt/sata_ssd/ai_pipeline`), blindando o NVMe. Validação `SHA256` nos modelos.
3. Inicialização do ComfyUI em porta exótica (ex: `--port 8288`) prevenindo choques de API.

**Fase 2: Test-Driven Development (`test_run_vfx.py`)**
Escreva testes `pytest-mock` simulando FFmpeg, porta 8288 e I/O no disco SATA. Valide o script sem executar tarefas reais.

**Fase 3: Motor de Orquestração com "Authorization Gates" (`run_vfx.py`)**
Escreva o script `asyncio` principal. Regras de Segurança, Performance e Checkpoints Manuais:
1. **Portões de Autorização (CRÍTICO):** Antes de tarefas críticas, o script DEVE pausar e exigir `[Y/n]` no terminal:
   * **Gate 1 - A Jaula de Memória:** Antes de invocar subprocessos envelopados por `systemd-run --user --scope -p MemoryMax=24G`. Plano B (Fallback): Caso falhe por falta de sessão DBus via SSH, use limite interno via biblioteca `resource`.
   * **Gate 2 - Pico de VRAM:** Antes do POST para a API do ComfyUI. Mostrar VRAM livre, alertar pico de 15GB e pedir aprovação (respeito ao Qwen).
   * **Gate 3 - I/O de Disco (NVENC Chunking):** Antes do FFmpeg usar `nvenc` e gravar os arquivos intermediários no formato *ffv1* ou *libx264 -crf 0* no disco SATA (evitando estourar a banda de 500MB/s).
2. *Wayland Guard* (`QT_QPA_PLATFORM=offscreen`) e `--dry-run` puro (somente stdout).
3. Repasse autorização familiar para bypass de age-analyzers no FaceFusion. Polling dinâmico de `/system_stats`. Higiene de metadados EXIF da foto via `PIL`.

**Fase 4: Render Final e Masterização**
1. Costura final: FFmpeg com Frame Rate Constante (CFR) e Matriz bt709.
2. Mapeamento bruto (`-map 0 -c:a copy -c:s copy -map_metadata 0`) preservando Áudio Surround 5.1/7.1 e legendas originais intactas.

[FIM DO PROMPT - ARQUITETURA FAIL-SAFE]
