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
| 3 | Corrigir Gate 3 (disco/composefs) e caminhos hardcoded | em andamento |
| 4 | Migrar código NVIDIA → AMD | pendente |
| 5 | Atualizar documentação (remover Ubuntu/NVIDIA) | pendente |
| 6 | Construir ambiente (distrobox + ROCm + modelos) | pendente |

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
