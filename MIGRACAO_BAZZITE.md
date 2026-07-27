# Migração AP AI Studio — Ubuntu/RTX → Bazzite/RX

Documento de trabalho da reconstrução iniciada em 2026-07-26. Registra a análise de
impacto, as decisões tomadas, as que ficaram para o usuário e o estado de cada etapa.

---

## 1. Análise de impacto (feita ANTES de qualquer alteração de estado)

Exigida pela regra crítica do `CLAUDE.md`: nada é instalado ou reconfigurado sem antes
verificar o que pode quebrar nos projetos protegidos (`security-audit`, `ap-ai-studio`,
`ap-tech-team`).

### 1.1 Restrição decisiva: não há acesso root

`sudo` exige senha nesta máquina e a sessão é não-interativa. Consequência prática:
**nenhuma alteração no sistema base é possível** — nem `rpm-ostree`, nem firewalld, nem
unidades systemd de sistema, nem módulos de kernel.

Isto é tratado como **proteção, não obstáculo**: força a arquitetura para userspace, que
já era a recomendação. Todo o stack de IA vive em contêiner e ambientes de usuário.

### 1.2 O que o `security-audit` documenta e como a reconstrução se relaciona

| Configuração do hardening | Risco da reconstrução | Mitigação adotada |
|---|---|---|
| `harden_B2_firewalld_lockdown.sh` remove `1025-65535/tcp` da zona padrão | A webui usa a porta **8299**, dentro do range removido. Depois do hardening, ficaria inacessível pela LAN | A webui escuta **apenas no IP Tailscale**, não em `0.0.0.0`. Não depende do range da zona padrão |
| `tailscale0` está hoje **sem zona** (`no zone`); o script prevê movê-la para `trusted` | Se a webui só escuta no IP Tailscale e a interface não estiver em zona permissiva, o acesso quebra | Anotado como **dependência**: ao aplicar o item 10 do hardening, `tailscale0` precisa ir para `trusted`. Não faço isso agora (exige root) |
| SSH só-chave restrito a 2 IPs Tailscale | Nenhum — a reconstrução não toca em SSH | — |
| `harden_A2_sysctl.sh` (já aplicado) | Nenhum — não alteramos sysctl | — |
| ClamAV + timer systemd | Concorrência de I/O durante varredura vs. render de vídeo | Aceitável; nenhuma ação |
| `bootc upgrade` / atualização de imagem | Atualizar a imagem base **não** derruba o contêiner nem os ambientes de usuário | Escolha do contêiner isola o stack de atualizações do sistema |
| `loginctl enable-linger` | Já ativo (`Linger=yes`) — necessário para a webui sob `systemd --user` e para jobs longos | Nenhuma mudança necessária |

### 1.3 Outros riscos verificados

- **v4l2loopback**: já carregado e em uso pelo OBS (`/dev/video0` = "OBS Virtual Camera").
  A reconstrução **não toca** nesse módulo. Registrado porque outro projeto
  (`virtual-cropped-cam`) queria reconfigurá-lo e isso quebraria o OBS.
- **GPU compartilhada**: a RX 9070 XT serve simultaneamente o desktop KDE, o Steam e o
  pipeline de IA. Instalar ROCm **no sistema base** arriscaria a sessão gráfica inteira.
  Dentro do contêiner, o ROCm usa o driver `amdgpu` do kernel via `/dev/dri` sem
  substituir nada do host. **Este é o principal motivo da escolha por contêiner.**
- **Ollama não está instalado** — o Gate 2 previa descarregar o Qwen para liberar VRAM.
  Vira no-op silencioso (comportamento já tolerado no código).

---

## 2. Decisões técnicas tomadas (com justificativa)

### 2.1 PyTorch/ROCm — GPU viável, sem repetir o drama da Blackwell

A gfx1201 (RDNA4) tem **suporte oficial** desde o ROCm 7.2, e há wheels PyTorch
publicadas pela AMD em `https://repo.amd.com/rocm/whl/gfx120X-all/`.

Vale contrastar com o histórico do projeto: na RTX 5060 Ti (Blackwell/sm_120), o
`onnxruntime-gpu` não tinha kernels para a arquitetura e o `lip_syncer` foi para CPU em
definitivo (ver `vfx_facefusion.py`). Aqui a situação do **PyTorch** é melhor — ComfyUI,
Demucs e XTTS devem rodar em GPU.

### 2.2 FaceFusion / onnxruntime — CPU por padrão

Não há wheel oficial de `onnxruntime-rocm` com kernels gfx1201 prontos; construir da
fonte exige `CMAKE_HIP_ARCHITECTURES` e há relatos de lacunas específicas de gfx1201 na
tabela de arquiteturas (fallback silencioso).

**Decisão:** manter `cpu` como padrão para FaceFusion, exatamente como já era na versão
Ubuntu/RTX para o `lip_syncer`. O parâmetro `execution_providers` continua exposto para
reavaliar sem mudança de código. Ou seja: **nenhuma regressão** — o comportamento é o
mesmo de antes para o lip_syncer, e o face_swapper (que usava `cuda`) passa a CPU.

Impacto de desempenho no face_swapper: real e esperado. Registrado como decisão do
usuário em aberto (§4).

### 2.3 Encoding de vídeo — VAAPI, não AMF

`h264_nvenc` não existe em AMD. Duas opções:

- **AMF**: equivalente mais próximo do NVENC em qualidade, mas a AMD **descontinuou o AMF
  nos drivers Linux recentes** e orienta migrar para VA-API.
- **VAAPI**: padrão aberto, via Mesa, já funcional nesta máquina.

**Decisão: VAAPI.** Testado de verdade nesta GPU antes de adotar — encode H.264 1280x720,
90 frames, arquivo válido. Perfis disponíveis: H.264 (Baseline/Main/High), HEVC
(Main/Main10) e AV1, todos com `VAEntrypointEncSlice`.

Detalhe: não é troca de nome. VAAPI exige `-vaapi_device /dev/dri/renderD128` e o filtro
`format=nv12,hwupload` antes do encoder.

### 2.4 Isolamento — distrobox

O stack de IA vive num contêiner distrobox com acesso a `/dev/dri`. Motivos: o sistema é
imutável (`rpm-ostree` exigiria layering + reboot e não temos root); o ROCm não pode
contaminar a GPU do desktop; e atualizações do Bazzite não quebram o ambiente.

---

## 3. Etapas

| # | Etapa | Estado |
|---|---|---|
| 1 | Análise de impacto vs `security-audit` | ✅ concluída (§1) |
| 2 | Pesquisa da stack AMD (ROCm, onnxruntime, VAAPI) | ✅ concluída (§2) |
| 3 | Corrigir Gate 3 (disco/composefs) e caminhos hardcoded | ✅ concluída (commit `fef3186`) |
| 4 | Migrar código NVIDIA → AMD | ✅ concluída (commit `fef3186`) |
| 5 | Atualizar documentação (remover Ubuntu/NVIDIA) | ✅ concluída (commit `b14247b`) |
| 6a | Contêiner distrobox + PyTorch ROCm | ✅ **GPU validada** (ver §3.1) |
| 6b | ComfyUI, custom nodes, FaceFusion, demais ambientes | ✅ concluída, sem falhas |
| 6c | Modelos | ✅ recuperados do backup (52G, 286 MB/s) |
| 6d | ComfyUI validado ponta a ponta na GPU | ✅ ver §7 |
| 7 | Regerar `requirements/` a partir dos ambientes reais | pendente |
| 8 | Configurar e subir a webui (`systemd --user`) | ✅ no ar (ver §11) |

### 3.1 Validação da GPU (2026-07-26 20:38) — a premissa se confirmou

```
torch                : 2.11.0+rocm7.13.0
compilado p/ HIP/ROCm: 7.13.99004
GPU disponivel       : True
nome                 : AMD Radeon RX 9070 XT
arquitetura          : gfx1201
VRAM total           : 15.9 GiB
Multiplicacao 4096x4096 na GPU: OK (resultado finito, sem NaN/Inf)
```

O teste **não** se contentou com `torch.cuda.is_available()`. Rodou uma multiplicação de
matrizes real e verificou que o resultado é finito, de propósito: na RTX 5060 Ti o
`is_available()` retornava `True` enquanto os kernels da arquitetura não existiam, e a
falha só aparecia no meio de um render. Aqui a computação de fato aconteceu.

### 3.2 Como acompanhar o build

Os estágios rodam como unidades `systemd --user` e **sobrevivem à desconexão do SSH**
(o `linger` já está ativo para o usuário):

```bash
systemctl --user status ai-studio-stage2          # estado atual
journalctl --user -u ai-studio-stage2 -f          # log ao vivo
journalctl --user -u ai-studio-stage1 --no-pager  # log do estágio já concluído
```

Os scripts (`build/stage1_base.sh`, `build/stage2_apps.sh`) são **idempotentes**: podem
ser reexecutados sem estragar o que já foi feito.

---

## 4. Decisões que são do usuário (não tomadas por mim)

Registradas aqui em vez de travar o trabalho. Nenhuma bloqueia as etapas 3–5.

1. **Desempenho do face swap em CPU.** O `face_swapper` usava `cuda`; agora vai a CPU.
   Alternativas: (a) aceitar CPU; (b) tentar compilar `onnxruntime-rocm` para gfx1201 —
   esforço alto, resultado incerto; (c) reavaliar quando houver wheel oficial.
   **Recomendação: (a) agora, (c) depois.**

2. **Qualidade do encoding.** VAAPI historicamente entrega qualidade um pouco inferior ao
   NVENC a mesmo bitrate. Se a qualidade final incomodar, a saída é usar `libx264` em CPU
   nos render finais (mais lento, melhor qualidade). **Recomendação: VAAPI por padrão,
   com `libx264` disponível por flag.**

3. **`tailscale0` na zona `trusted`.** Exige root. Precisa ser feito por você ao aplicar
   o item 10 do hardening, senão a webui fica inacessível depois do lockdown.


---

## 5. Achados durante o build (2026-07-26, noite)

### 5.1 O ComfyUI nunca foi clonado — e o build não percebeu

O diretório `ai_pipeline/ComfyUI` já existia, criado como **efeito colateral da suíte de
testes** (`test_process_long_upscale...` faz `os.makedirs` em `PIPELINE_PATH`). O
`git clone` recusa destino não-vazio, falhou, e o build seguiu: os cinco custom nodes
foram instalados dentro de um ComfyUI que não existia. Só apareceu na revisão do log,
porque o script registra falhas em vez de abortar.

Correção dupla: a função `clonar()` agora trata destino não-vazio (clona num temporário e
preenche lacunas sem sobrescrever), e o ComfyUI foi restaurado sem perturbar o download
que já estava em curso no mesmo diretório.

**Lição:** "seguir em caso de falha" precisa vir com verificação de resultado no fim, não
só com o registro da falha. Um `main.py` ausente é detectável em uma linha.

### 5.2 Runtime separado do código

O `.gitignore` mostra que a arquitetura pretendida é **repositório == raiz do estúdio**
(`/ai_pipeline` e `/miniconda3` ignorados dentro dele). O build criou o runtime noutro
caminho, e `vfx_aliases.sh` procuraria o `run_vfx.py` no lugar errado.

Miniconda **não é relocável** (shebangs com caminho absoluto), então mover estava fora de
questão. Solução: a raiz passou a ser o repositório, com symlinks para os dados pesados.
Aproveitando, o default de `STUDIO_HOME` virou **auto-localizável** (o diretório do
próprio `vfx_config.py`) — o último caminho fixo do projeto deixou de existir.

### 5.3 Download lento: limite por conexão, não de banda

O `wget` de conexão única ficou em **3,0 MB/s** contra o CDN da HuggingFace, enquanto o
`pip` alcançou ~40 MB/s no mesmo link. Testado `hf_transfer` (5,9 MB/s) e o modo Xet
(inconclusivo). A solução que valeu foi trivial: **4 downloads em paralelo**, subindo a
vazão agregada para **7,5 MB/s** sem trocar a ferramenta que já funcionava e retoma
downloads parciais.

### 5.4 O torch ROCm sobreviveu a todos os requirements

Confirmado após instalar ComfyUI, 5 custom nodes, coqui-tts e demucs:

| Ambiente | torch | HIP | GPU |
|---|---|---|---|
| `vfx-pipeline` | 2.11.0+rocm7.13.0 | 7.13.99004 | ✅ |
| `tts-pipeline` | 2.11.0+rocm7.13.0 | 7.13.99004 | ✅ |
| `noise-pipeline` | 2.11.0+rocm7.13.0 | 7.13.99004 | ✅ |

FaceFusion com `onnxruntime 1.26.0` expondo apenas `CPUExecutionProvider` — como
decidido. A reafirmação do torch depois de cada bloco de requirements (§2.1) provou-se
necessária: era exatamente o que quebrava na era NVIDIA.


---

## 6. Restrição de uso declarada pelo usuário (2026-07-26)

**Os três consumidores de GPU nunca rodam ao mesmo tempo.** É um de cada vez:
AP AI Studio, `ap-tech-team` (LLMs via Ollama) **ou** jogos.

Isso muda o dimensionamento: não é preciso reservar VRAM para coexistência, e cada um
pode usar a placa inteira. Dois resíduos permanecem, ambos pequenos:

1. **Residência do Ollama.** Ele mantém o modelo em VRAM por um tempo após o último uso
   (`keep_alive`, padrão 5 min). Trocar de projeto rápido demais encontra a VRAM ainda
   ocupada. O Gate 2 já cobre isso via `unload_ollama_model` (`vfx_gates.py`), herdado da
   era do Qwen — hoje é no-op porque o Ollama não está instalado. Ao instalar, **conferir
   o nome do modelo padrão**, que ainda é `"qwen"`.
2. **`VRAM_PEAK_ALERT_GB = 15`** com o desktop KDE consumindo ~2,5 GB em repouso: o alerta
   dispara quase sempre. Recalibrar para ~13 GB **com número medido** durante o teste
   ponta a ponta, não por estimativa.

### Modelos LLM do `ap-tech-team` (levantados do código no backup)

Os pesos **não estão no backup** do SSD Netac — nem em `ap-tech-team/` (825 MB, só código)
nem em qualquer outro lugar do disco; não há armazenamento do Ollama (`blobs`/`manifests`).
Terão que ser rebaixados. A lista real, extraída do código:

| Modelo | Menções |
|---|---|
| `ornith:9b` | 63 |
| `gemma4:12b-it-qat` | 44 |
| `ornith:35b` | 38 |
| `gemma4:26b` | 35 |
| `qwen3.6:35b-a3b-q4_K_M` | 24 |
| `qwen3-coder:30b` | 12 |

Espaço livre após copiar os modelos do estúdio: **118 GB**. O conjunto acima deve passar de
90 GB — cabe, mas apertado.

### Modelos do estúdio: recuperados do backup, não baixados

Os 52 GB de `models_hub` estavam íntegros no backup pré-formatação e foram copiados
localmente a 286 MB/s (1min27s), contra ~1h30 que faltavam pela rede. Vale como
lembrete de procedimento: **conferir o que já existe em disco antes de baixar da internet.**


---

## 7. ComfyUI validado na GPU AMD (2026-07-26 22:0x)

Subida real do ComfyUI, não teste sintético:

```
Total VRAM 16304 MB, total RAM 31892 MB
pytorch version: 2.11.0+rocm7.13.0
ROCm version: (7, 13)
Device: cuda:0 AMD Radeon RX 9070 XT : native
Starting server
```

`cuda:0` é só o nome que o PyTorch dá ao dispositivo no ROCm (a API HIP mantém a
nomenclatura CUDA por compatibilidade) — o backend é ROCm, como as duas linhas acima
mostram.

**Os 6 custom nodes carregaram sem nenhuma falha de import**, incluindo o
WanVideoWrapper e o comfyui_controlnet_aux, que eram os candidatos a quebrar por
dependerem de otimizações CUDA-específicas.

**Os 4 modelos Wan2.2 aparecem no `UnetLoaderGGUF`**, consultado pela API
(`/object_info/UnetLoaderGGUF`).

Detalhe que confundiu no meio do caminho: `folder_paths.get_filename_list("diffusion_models")`
devolve **0** para os GGUF, e isso é correto — `.gguf` não é extensão aceita ali. O node
ComfyUI-GGUF registra a chave própria `unet_gguf` reaproveitando os mesmos caminhos com
`{".gguf"}`. Procurar no lugar errado dava a falsa impressão de que a configuração estava
quebrada.

O `extra_model_paths.yaml` em uso está versionado como
[`build/extra_model_paths.yaml.exemplo`](build/extra_model_paths.yaml.exemplo) — o real
fica fora do git porque carrega caminho absoluto da máquina.


---

## 8. Auditoria linha a linha (2026-07-26, noite)

Leitura integral de `security-audit` (18 arquivos, 1.684 linhas) e de todo o código,
configuração e documentação do `ap-ai-studio` — excluídos apenas artefatos gerados
(`__pycache__`, `.pytest_cache`, `package-lock.json`, `node_modules`), que não são fonte.

### 8.1 Bugs introduzidos por mim na migração — os mais graves

| Onde | O quê | Impacto |
|---|---|---|
| `webui/backend/main.py` | usava `VFX_DIR` sem importar | `NameError` em toda requisição POST — **36 dos 44 testes do backend falhavam** |
| `vfx_aliases.sh:27` | IP Tailscale do servidor antigo ainda hardcoded | `vfx-web` tentaria bind num IP inexistente |
| `webui/backend/config.py:43` | idem | webui não subiria |
| `vfx_aliases.sh` (`vfx-ajuda`) | `$VFX_DIR` dentro de heredoc `<<'EOF'` (aspas não expandem) | imprimia o literal |

**Por que passaram:** eu rodei apenas `test_run_vfx.py` e afirmei "87/87 testes passando".
Existem **três** suítes — faltavam `test_backend.py` (44) e `test_standalone_scripts.py` (6).
Declarar cobertura por uma suíte quando há três é o tipo de erro que a própria auditoria
existe para pegar.

### 8.2 Lacunas que a migração não cobriu

- **4 custom nodes do ComfyUI ausentes**, descobertos ao ler `vfx_workflows.py`:
  `VHS_VideoCombine`/`VHS_LoadVideo` (VideoHelperSuite) e `HuggingFaceMusicGen`/
  `MusicGenAudioToFile`. Sem eles os modos `video`, `music` e `upscale --realesrgan`
  falhariam em execução, não na importação. VideoHelperSuite instalado e verificado via
  `/object_info`. **MusicGen virou decisão do usuário** (§9).
- **`.pre-commit-config.yaml`** apontava para `/home/ap/...` no hook do mypy — quebrado, e
  mascarado pelo `|| true` do próprio hook.
- **`.github/workflows/test.yml`** descrevia "torch/CUDA, GPU NVIDIA real".
- **`StatusPage.tsx`** exibia "nvidia-smi indisponivel" ao usuário, e o card de disco dizia
  "Disco (/)" quando a medição passou a ser do diretório do pipeline.
- **`vfx_ffmpeg.py`** instruía `sudo apt install` — comando inexistente no host imutável.

### 8.3 Duplicidade de diretório: explicada, não é erro

`~/ap-ai-studio/` (78 G) contém **só dados** — `miniconda3` (26 G) e `ai_pipeline` (52 G).
`Projetos/ap-ai-studio/` (228 M) contém **só código**, com dois symlinks para os dados.
**Apagar o primeiro destrói os 78 GB.**

Origem: o build criou o runtime ali antes de eu descobrir, lendo o `.gitignore`, que a
arquitetura pretendida era repo == raiz. Miniconda grava caminhos absolutos nos shebangs e
não é relocável, então a solução foi symlink em vez de mover.

Os scripts de `build/` estavam de fato duplicados (editei um e copiei à mão para o outro —
risco real de divergência). Resolvido: os do home viraram symlinks para os do repositório,
fonte única.

### 8.4 Estado dos testes após as correções

| Suíte | Resultado |
|---|---|
| `test_run_vfx.py` | **87/87** |
| `test_standalone_scripts.py` | **6/6** |
| `webui/backend/test_backend.py` | **41/44** — as 3 restantes exigem `static/`, que só existe após o build do frontend |

---

## 9. Decisão pendente do usuário: node do MusicGen

O `--mode music` depende de `HuggingFaceMusicGen`/`MusicGenAudioToFile`. O upstream
`crashy/ComfyUI-MusicGen-HF` **foi removido do GitHub** (404); resta um fork com 10
estrelas (`ebrinz/ComfyUI-MusicGen-HF`), cujo `node_list.json` confirma registrar
exatamente essas classes.

Não instalei por conta própria porque o projeto já estabeleceu esse critério: o
`vfx_facefusion.py` registra ter recusado um build não-oficial do onnxruntime por
"0 estrelas, sem manutenção, risco de segurança real". Aplicar o critério em um caso e
ignorá-lo em outro seria incoerente.

Opções: (a) instalar o fork mesmo assim; (b) deixar o `--mode music` indisponível;
(c) procurar alternativa mantida. Sem decisão, todos os outros 8 modos funcionam.


---

## 10. Consolidação: tudo dentro do repositório (2026-07-26, madrugada)

A decisão do usuário: nenhum resíduo no home, nenhum projeto dividido. `~/ap-ai-studio`
deixou de existir.

### Como foi feito

1. **`ai_pipeline` (52 GB) movido**, não copiado — mesmo btrfs, `mv` levou **9 ms**.
2. **Miniconda reinstalado** no caminho novo. Não foi movido de propósito: instalações
   conda gravam caminhos absolutos em shebangs, `conda-meta` e bibliotecas — mover
   quebraria de forma silenciosa, que é o pior tipo de quebra.
3. **`~/ap-ai-studio` apagado** (26 GB do Miniconda antigo).

### Verificação antes de apagar — e o que ela pegou

Antes do `rm -rf`, varredura por referências ao caminho antigo. **Encontrou seis**, uma
delas crítica:

- **`extra_model_paths.yaml` ainda apontava para `~/ap-ai-studio/ai_pipeline/models_hub/`.**
  Apagar sem corrigir teria feito o ComfyUI perder os 52 GB de modelos — com a pasta
  ainda em disco, mas invisível para ele.
- `build/chain_stage3.sh`, `stage1/stage3/stage3b` e `vfx-webui.env.example` também
  tinham o caminho antigo como default.

Os scripts de build passaram a derivar a raiz da própria localização (`<raiz>/build/`),
sem caminho fixo — mesma abordagem já aplicada ao `vfx_config.py` e ao `vfx_aliases.sh`.

### Três defeitos nos `requirements/` que eu havia regenerado

Descobertos porque a reinstalação no caminho novo **falhou de verdade** — não teriam
aparecido sem reexecutar:

1. **`packaging @ file:///home/conda/feedstock_root/...`** em todos os 5 arquivos. O
   `pip freeze` num ambiente conda grava o caminho de compilação da máquina que gerou o
   pacote. Esse caminho não existe em lugar nenhum: a reinstalação morria com `OSError`.
2. **`filetype` ausente** do requirements da webui, embora `jobs.py` o importe. Causa: eu
   congelei um ambiente que **já estava incompleto** (o estágio 2 tinha caído no fallback
   de dependências básicas) e registrei aquilo como verdade.
3. Faltavam também `httpx` e `pytest`, necessários para a suíte do backend rodar.

**Lição:** `pip freeze` documenta o ambiente que existe, não o que o código precisa. Se o
ambiente estiver errado, o arquivo gerado registra o erro com aparência de autoridade. A
fonte da verdade é o que o código importa — conferido com `grep` nos `import` do backend.

### Estado final verificado

```
Projetos/ap-ai-studio/
├── ai_pipeline/     52 GB  (ComfyUI, facefusion, models_hub)
├── miniconda3/      26 GB  (5 ambientes)
├── build/                  (scripts, auto-localizáveis)
├── webui/, run_vfx.py, vfx_*.py, docs...
```

| Verificação | Resultado |
|---|---|
| torch nos 3 ambientes | `2.11.0+rocm7.13.0`, GPU=True |
| ComfyUI subindo do caminho novo | `Device: cuda:0 AMD Radeon RX 9070 XT : native` |
| Modelos visíveis no `UnetLoaderGGUF` | 4/4 |
| `test_run_vfx` / `standalone` / `backend` | 87/87 · 6/6 · 41/44 |

`~/ap-ai-studio` não existe mais. O home tem apenas os diretórios do usuário.


---

## 11. Interface web no ar (2026-07-27)

Frontend reconstruído do zero (o `node_modules` da tentativa interrompida foi descartado,
não reaproveitado): **lint sem avisos, 48/48 testes, build gerado** em
`webui/backend/static/`.

Com o build presente, as 3 falhas restantes do backend caíram: **44/44**.

### Suítes completas

| Suíte | Resultado |
|---|---|
| `test_run_vfx.py` | 87/87 |
| `test_standalone_scripts.py` | 6/6 |
| `webui/backend/test_backend.py` | **44/44** |
| frontend (Vitest) | 48/48 |
| **Total** | **185 testes** |

### Serviço

`~/.config/systemd/user/vfx-webui.service`, habilitado (`enabled`) e com `Linger=yes` —
sobe no boot e sobrevive a logout.

O `.service` teve os caminhos corrigidos para a raiz consolidada. Detalhe que vale
registrar: `WorkingDirectory` **não aceita variável vinda do `EnvironmentFile`** (o
systemd resolve esse campo antes de ler o arquivo), então ele usa `%h/Projetos/...`
literal, enquanto host e porta continuam vindo do env — que é o que não pode ir pro git.

### Verificado ao vivo

```
GET /              -> 200
GET /rosto         -> 200   (sub-rota do React Router, sem 404)
GET /api/status    -> {"vram":{"free_mb":13729,"total_mb":16304},
                       "disk_free_gb":128.5,"disk_total_gb":474.4}
```

O `/api/status` é a prova visível das duas correções da migração: a VRAM vem do sysfs do
`amdgpu` (não de `nvidia-smi`) e o disco reporta **128,5 GB livres** — antes, medindo `/`,
teria reportado zero e o Gate 3 recusaria qualquer job.

**Resiliência testada, não presumida:** `kill -9` no processo principal; o systemd
reergueu em 14 s com PID novo e a interface voltou a responder 200.
