# Auditoria Multi-Perspectiva — AP AI Studio (rodada final, pós-correções)

**Data:** 2026-07-03 · **Auditor:** Claude (Sonnet 5)
**Método:** os mesmos quatro papéis sênior independentes da auditoria anterior
([`AUDITORIA_2026-07-03_4PERSPECTIVAS.md`](AUDITORIA_2026-07-03_4PERSPECTIVAS.md)),
reavaliados depois de aplicar todas as correções autorizadas naquela rodada. Verificação
ao vivo contra o servidor real (suíte de testes completa, `pre-commit`, `bandit`,
`npm audit`, systemd, disco, VRAM) — não é releitura de código sozinha. Onde algo não foi
verificado ao vivo, isso está dito explicitamente.

---

## Resumo do que mudou desde a auditoria anterior

| # | Item | Perspectiva de origem | Status |
|---|---|---|---|
| 1 | `LICENSE` (uso privado) | Código | ✅ Feito |
| 2 | `requirements/` (5 ambientes Conda + webui) | Código | ✅ Feito |
| 3 | `CHANGELOG.md` | Código | ✅ Feito |
| 4 | CI (GitHub Actions) + `pre-commit` | Código | ✅ Feito |
| 5 | `run_vfx.py` dividido em módulos | Código | ✅ Feito (7 módulos, 429→ linhas no orquestrador) |
| 6 | Validação de assinatura real do arquivo no upload | QA/Cybersecurity | ✅ Feito |
| 7 | `--mode upscale` standalone (Real-ESRGAN) | Uso profissional | ✅ Feito |
| 8 | Comparação antes/depois na webui | Uso profissional | ✅ Feito |
| 9 | Mensagem "rascunho vs. produção" (docs + UI) | Uso profissional | ✅ Feito |
| 10 | Nota sobre revisitar teto de resolução se trocar GPU | Uso profissional | ✅ Feito (documentação) |

**Verificado ao vivo nesta rodada, antes de escrever esta auditoria:**
- **124 testes passando** (68 `test_run_vfx.py` + 6 `test_standalone_scripts.py` + 43
  `webui/backend/test_backend.py` + 7 `webui/frontend` Vitest) — suíte completa rodada
  agora, não reaproveitada de memória.
- `pre-commit run --all-files`: `ruff` (pyflakes) e `eslint` passando limpo.
- `bandit -r .` (SAST): 0 issues de severidade média/alta em código de produção — os 3
  achados de severidade média que aparecem são falsos-positivos em `test_standalone_scripts.py`
  (string `/tmp/...` passada como argumento de CLI pro subprocesso de teste, não escrita
  de arquivo real).
- `npm audit --omit=dev`: 0 vulnerabilidades.
- `systemctl --user status vfx-webui.service`: `active (running)`, escutando só em
  `100.122.206.41:8299` (confirmado no próprio comando da unit) — nenhum bind em
  `0.0.0.0`.
- Disco: `105GB` livres de `468GB` (77% usado) — igual à auditoria anterior, sem
  degradação.
- VRAM livre: `15GB` de `16.3GB` (ComfyUI ocioso) — normal.
- `--mode upscale` testado ponta a ponta duas vezes: CLI direto (`1024×1024 →
  4096×4096`) e pela própria webui em produção, sem `--dry-run` (`256×256 → 1024×1024`,
  confirmado pelo tamanho real do arquivo baixado).

---

## 1. Auditoria de Código — Engenheiro de Software / Full Stack

### Nota: 9,0 / 10 (antes: 7,5)

**Por quê:** todas as 5 lacunas de higiene de projeto identificadas na rodada anterior
foram fechadas com evidência real (não só declaração) — dependências reprodutíveis,
histórico estruturado, CI, lint automatizado e um monólito de ~1500 linhas quebrado em
módulos coesos. O que falta agora é polimento incremental, não fundação.

**Prós:**
- `requirements/` com `pip freeze` real dos 5 ambientes Conda + `webui/backend/requirements.txt`,
  documentado em `requirements/README.md` — recriar qualquer ambiente do zero agora é
  um comando, não garimpagem de prosa.
- `CHANGELOG.md` reconstruído do `git log` real (não inventado), formato Keep a
  Changelog, com seção `[Não lançado]` cobrindo honestamente o que ainda não foi
  commitado.
- `run_vfx.py` caiu de ~1500 para 429 linhas, virou só o orquestrador
  (`orchestrate()`/`build_parser()`/`main()`); a lógica foi distribuída em 7 módulos por
  responsabilidade (`vfx_config.py` 64L, `vfx_core.py` 100L, `vfx_gates.py` 245L,
  `vfx_comfyui.py` 228L, `vfx_workflows.py` 462L, `vfx_facefusion.py` 145L,
  `vfx_ffmpeg.py` 180L) — todos reexportados por `run_vfx.py`, então nada que já
  consumia `from run_vfx import X` (atalhos `vfx-*`, webui, testes) precisou mudar.
  Verificado com a suíte inteira passando sem alteração de comportamento.
- `.github/workflows/test.yml` + `.pre-commit-config.yaml` ativos e confirmados
  funcionando agora mesmo (não só na hora em que foram criados) — `ruff`/`eslint`
  rodando limpo, sem reformatar o TAB-indent do projeto.
- `LICENSE` presente, coerente com a decisão de uso estritamente privado.
- `--mode upscale` reaproveita infraestrutura existente (mesmo modelo, mesmos nodes do
  ComfyUI) em vez de introduzir dependência nova — decisão de engenharia econômica.

**Contras:**
- **Componente novo sem teste dedicado:** `BeforeAfterCompare.tsx` (usado em 4 páginas)
  não tem `*.test.tsx` próprio — é exercitado só indiretamente, e nenhum teste de
  frontend hoje cobre o estado "job concluído com resultado pronto" (`output_ready:
  true`) em nenhuma página, então o caminho de renderização do antes/depois nunca roda
  sob teste automatizado. Gap pré-existente (nenhuma página tinha esse teste antes
  também), não uma regressão desta rodada, mas vale fechar.
- **CI ainda depende de "melhor esforço" pra `test_run_vfx.py`:** o job
  `orquestrador-melhor-esforco` roda com `continue-on-error: true` porque depende de
  GPU/ambientes Conda/`systemd --user` que um runner genérico do GitHub Actions não
  tem — documentado com transparência no próprio workflow, mas significa que uma
  regressão nos 68 testes de `run_vfx.py` não bloqueia o CI sozinha (só o frontend e os
  scripts standalone bloqueiam de verdade).
- **42 arquivos com mudanças não commitadas** no momento desta auditoria (10 novos
  módulos/arquivos, 24 modificados, incluindo toda a divisão do `run_vfx.py`, o `--mode
  upscale` e a comparação antes/depois) — nada disso está em risco de se perder (é
  trabalho local, não voláteis), mas é uma janela grande sem checkpoint no histórico do
  git. Commit fica pendente de autorização explícita, como combinado.

### O que precisa ser feito para melhorar
1. Adicionar `BeforeAfterCompare.test.tsx` e pelo menos um teste por página cobrindo o
   estado "job concluído" (`output_ready: true`), não só os estados vazio/erro/rodando
   já cobertos.
2. Quando o servidor ganhar um runner de CI próprio (self-hosted, com GPU) — fora de
   escopo agora, só registrando a opção — trocar `continue-on-error: true` por
   obrigatório.
3. Commitar em lotes coerentes (ex.: um commit por item da tabela acima) quando
   autorizado, em vez de um commit monolítico — facilita `git bisect` futuro se algo
   quebrar.

### Sugestão nova
- `mypy`/`pyright` em modo leve (só checagem, sem bloquear CI de início) daria o mesmo
  tipo de rede de segurança que o `eslint` já dá no frontend, agora que o backend Python
  está modularizado o suficiente pra isso valer a pena.

---

## 2. Auditoria de SO — DevOps / SysAdmin Ubuntu

### Nota: 8,5 / 10 (antes: 8,0)

**Por quê:** nada de novo quebrou nem arriscou os invariantes do servidor (Tailscale,
SSH, UFW, ClamAV, Ollama) nesta rodada — a divisão de módulos e o novo modo `upscale`
são mudanças de aplicação, não de sistema. O ganho de nota vem de duas correções reais
de robustez operacional que sobreviveram à reavaliação: caminho absoluto do
`nvidia-smi` e a supervisão systemd continuando saudável sob a carga adicional de um
9º endpoint (`/api/jobs/upscale`).

**Prós:**
- `vfx-webui.service` confirmado `active (running)` agora, escutando exclusivamente em
  `100.122.206.41:8299` — reiniciado 3 vezes nesta sessão (build do frontend, teste do
  upscale, teste do antes/depois) e voltou limpo todas as vezes, sem journal de erro.
- `nvidia-smi` chamado por caminho absoluto (`/usr/bin/nvidia-smi`) em vez de depender
  do `$PATH` — fecha um achado real do `bandit` (B607) da rodada anterior, reduz
  superfície de PATH-hijacking.
- Nenhuma mudança nesta rodada tocou `sysctl`, `sshd_config`, UFW, `fail2ban` ou
  Tailscale — os 8 invariantes do baseline de segurança do servidor continuam intactos
  (não reauditados a fundo aqui de novo, porque nada nesta rodada de trabalho os
  tocou).
- Disco estável: `105GB` livres, mesma margem da auditoria anterior — o novo modo
  `upscale` não introduziu consumo de disco extra relevante (reaproveita modelo já
  baixado, 64MB).
- ClamAV/`--exclude-dir` do pipeline não foi alterado nem precisava ser — nenhum
  diretório novo fora de `/home/ap/ai_pipeline` foi criado.

**Contras:**
- **Ainda sem runner de CI dedicado a este hardware** (mesmo ponto da auditoria
  anterior) — os 68 testes de `test_run_vfx.py` que dependem de GPU/`systemd --user`
  só rodam quando alguém lembra de rodar na mão neste servidor específico.
- **`webui-pipeline` é o único ambiente Conda com `bandit`/`pre-commit` instalados** —
  se esse ambiente for removido/recriado sem cuidado, o lint local para de funcionar
  silenciosamente (o hook `ruff` já foi migrado pro repo hospedado `astral-sh/ruff-pre-commit`,
  que não depende disso, mas o `eslint` local e o próprio `pre-commit` em si ainda
  dependem do `webui-pipeline` estar íntegro).

### O que precisa ser feito para melhorar
1. Documentar em `requirements/README.md` (ou `PROMPT_MASTER.md`) que `bandit` e
   `pre-commit` vivem especificamente no `webui-pipeline`, não em todos os ambientes —
   pra não haver confusão numa reinstalação futura.
2. Sem ação nova de sistema recomendada além disso — o servidor está estável e nenhuma
   invariante foi tocada.

### Sugestão nova
Nenhuma nova nesta rodada (a única sugestão pendente da rodada anterior — revisitar o
teto de resolução se a GPU for trocada — já foi documentada em `PROMPT_MASTER.md`, ver
perspectiva 4).

---

## 3. Auditoria de Testes — QA + Cybersecurity

### Nota: 9,5 / 10 (antes: 8,5)

**Por quê:** o único achado de segurança pendente da rodada anterior (validação de tipo
de arquivo no upload) foi corrigido e verificado — `bandit` e `npm audit` seguem limpos
em código de produção, e a suíte de testes cresceu de 115 para 124 mantendo 100% de
aprovação. Os dois itens que a rodada anterior listou como "aceitos, não corrigidos"
(limite de concorrência e revisão de uma pessoa só) **não são recontados aqui como
pendência** — o usuário determinou explicitamente que são fora de escopo pra um projeto
pessoal e não-público, e essa decisão continua válida.

**Prós:**
- Validação de assinatura real do arquivo (`filetype`, 1.2.0) rejeitando qualquer
  upload cujo conteúdo real não seja imagem/vídeo/áudio, antes de chegar no
  FFmpeg/FaceFusion com um erro técnico cru — verificação pelos bytes reais, não pelo
  nome/`Content-Type` declarado. Implementada de forma permissiva por pedido explícito
  ("não exagerar na blindagem"): qualquer MIME que comece com `image/`, `video/` ou
  `audio/` passa, sem lista branca restritiva de formatos específicos.
- `bandit -r .`: 0 issues reais em código de produção (os 3 apontamentos que aparecem
  são falsos-positivos em fixtures de teste, confirmados por leitura manual).
- `npm audit --omit=dev`: 0 vulnerabilidades nas dependências que realmente vão pra
  produção (as 4 vulnerabilidades dev-only do Vite/esbuild continuam deliberadamente
  não corrigidas — corrigi-las quebraria a compatibilidade já documentada com o Node
  18.19.1 instalado no servidor).
- As 3 falhas críticas/médias de rodadas anteriores (path traversal na SPA, limite de
  upload contornável via `Transfer-Encoding: chunked`, crash com filename `".."`)
  seguem corrigidas e cobertas por teste de regressão — não foram tocadas nem
  reintroduzidas nesta rodada.
- Bug de "job fantasma" (upload parcial deixando job/arquivo órfão) segue corrigido e
  testado — nenhuma das 3 novas rotas/páginas desta rodada (`upscale`) reintroduziu o
  padrão antigo, porque todas usam o `save_uploads()` já corrigido.

**Contras:**
- **Cobertura de teste do fluxo "resultado pronto" na UI é zero** (mesmo ponto da
  perspectiva de Código, repetido aqui porque também é um achado de QA): nenhuma
  página tem teste do estado `output_ready: true`, incluindo a nova comparação
  antes/depois. Isso significa que um bug visual/lógico em `BeforeAfterCompare.tsx`
  (ex.: vazamento de `URL.createObjectURL()` sem revogar, ou renderizar `<img>` pra um
  arquivo que na verdade é vídeo) não seria pego automaticamente — só numa inspeção
  manual no navegador, que não foi feita nesta sessão (ver nota de transparência
  abaixo).
- **Nota de transparência:** a verificação do antes/depois e do banner "modo rascunho"
  foi feita por lint (`eslint --max-warnings=0`), build (`tsc -b && vite build`) e
  smoke-test via `curl` contra a API real — **não houve inspeção visual num navegador
  de verdade** nesta sessão (não há ferramenta de captura de tela/browser disponível
  neste ambiente de trabalho). O código compila e os testes automatizados passam, mas
  "parece certo no código" não é o mesmo que "confirmado visualmente correto".

### O que precisa ser feito para melhorar
1. Fechar o gap de teste do item acima (mesma ação já listada na perspectiva de
   Código).
2. Quando o usuário acessar a interface pelo navegador (celular/notebook via
   Tailscale), vale um olhar rápido nas 4 páginas com antes/depois pra confirmar
   visualmente que o layout lado-a-lado está bom em telas menores (o componente usa
   `Col md={6}` do react-bootstrap, que empilha em telas `<768px` — comportamento
   esperado, mas não visto ao vivo).

### Sugestão nova
Nenhuma nova nesta rodada — a validação de arquivo já cobre o gap de segurança que
restava, e os itens explicitamente fora de escopo (concorrência, revisão) continuam
fora de escopo por decisão do usuário.

---

## 4. Auditoria de Uso Profissional — Perfil de Edição com IA (do iniciante ao avançado)

### Nota: 8,5 / 10 (antes: 7,0)

**Por quê:** as três sugestões desta perspectiva na rodada anterior foram todas
implementadas e verificadas ao vivo — `--mode upscale`, comparação antes/depois, e a
mensagem clara de "rascunho vs. produção" (em três lugares: `MANUAL_USO.md`,
`PROMPT_MASTER.md` e agora também um banner direto na página "Gerar Vídeo" da webui).
O maior ganho de usabilidade real pro objetivo do projeto (restaurar fotos antigas de
família) é o upscale — testado de ponta a ponta com um resultado 4x real, não simulado.

**Prós:**
- `--mode upscale` cobre exatamente o caso de uso que faltava: melhorar a resolução de
  uma foto/vídeo que já existe (ex.: foto antiga de família) sem o custo/risco de
  recriar a cena do zero pela geração de vídeo (que é modo rascunho). Reaproveita
  modelo já instalado — zero custo de disco/dependência nova.
- Comparação antes/depois lado a lado nas 4 páginas onde faz sentido (Trocar Rosto,
  Remover Fundo, Editar Imagem, Aumentar Resolução) — usa o arquivo que já está no
  navegador (`URL.createObjectURL`), sem precisar reenviar nada pro servidor só pra
  comparar.
- Expectativa calibrada em 3 camadas agora: `MANUAL_USO.md` seção 0 (visão geral),
  seção 4.4 (aviso específico antes do comando), e um `Alert` visível na própria página
  "Gerar Vídeo" da webui — cobre tanto quem lê o manual quanto quem só usa a interface
  direto.
- Achado colateral corrigido no processo: `RemoveBgPage.tsx` sempre mostrava o
  resultado como imagem mesmo quando o alvo enviado era vídeo — bug real de usabilidade
  (um resultado em vídeo simplesmente não aparecia certo), fechado como consequência
  direta de implementar o antes/depois corretamente.

**Contras (nenhum destes foi pedido nesta rodada — registrados por transparência, não
como pendência aceita):**
- Ainda não existe processamento em lote (múltiplas fotos/vídeos numa fila só) — cada
  job é disparado e acompanhado individualmente.
- Mensagens de erro na interface ainda repassam o texto técnico do `run_vfx.log` — um
  iniciante vendo "GateDenied: VRAM insuficiente" não necessariamente entende que
  significa "feche o Ollama ou espere ele liberar memória".
- Sem LoRA/ControlNet/geração guiada por segmentação — a geração de vídeo continua
  limitada ao que o Wan2.2 T2V/I2V faz nativamente.
- O modo `video` continua 3-10x mais lento do que caberia na VRAM disponível — decisão
  de arquitetura aceita em rodada anterior (block-swap prioriza não travar o Ollama),
  não um bug, mas ainda vale lembrar quem espera velocidade de uma GPU dedicada full.

### O que precisa ser feito para melhorar
Nenhuma ação pendente dos itens que o usuário pediu nesta rodada — todos concluídos e
verificados ao vivo. Os 4 contras acima são candidatos pra uma futura rodada, não uma
lacuna desta.

### Sugestão nova
- Um "modo simples" opcional nas mensagens de erro da webui (ex.: mapear
  `GateDenied`/`OOM`/timeouts conhecidos pra uma frase em português simples, mantendo o
  log técnico completo disponível num "ver detalhes") atacaria o contra de mensagens
  técnicas sem precisar reescrever a lógica de Gates em si.

---

## Média final: 8,9 / 10 (antes: 7,75)

| Perspectiva | Nota anterior | Nota atual |
|---|---|---|
| Código | 7,5 | **9,0** |
| SO / DevOps | 8,0 | **8,5** |
| Testes (QA + Cybersecurity) | 8,5 | **9,5** |
| Uso profissional | 7,0 | **8,5** |

## Estado do repositório (transparência)

Nada foi commitado nem enviado ao remoto durante esta sessão de correções — 42 arquivos
com mudanças pendentes (10 novos, 24 modificados, mais os módulos `vfx_*.py` e a pasta
`requirements/`), incluindo toda a divisão do `run_vfx.py`, o `--mode upscale`, a
comparação antes/depois e as atualizações de documentação. `origin/main` continua no
commit `35dc3d0`. **Commit/push seguem pendentes de autorização explícita**, como
combinado — nenhuma ação de git além de leitura (`status`/`diff`) foi executada nesta
sessão.
