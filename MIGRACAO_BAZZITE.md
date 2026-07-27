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
| 6c | Download dos modelos | 🔄 em andamento (~7,5 MB/s, 4 conexões) |
| 7 | Regerar `requirements/` a partir dos ambientes reais | pendente |
| 8 | Configurar e subir a webui (`systemd --user`) | pendente |

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
