# Auditoria Multi-Perspectiva — AP AI Studio (3ª rodada, pós-correções da 2ª revisão)

**Data:** 2026-07-03 · **Auditor:** Claude (Sonnet 5)
**Método:** mesmo esquema das rodadas anteriores — quatro papéis sênior independentes,
nota própria por perspectiva, verificação ao vivo contra o servidor real. Diferente da
2ª revisão (que só reconfirmou o estado, sem mudança de código), **esta rodada aplicou
correções reais** sobre os itens acionáveis que a 2ª revisão deixou pendentes.

---

## O que foi corrigido nesta rodada

| Contra da rodada anterior | Ação tomada |
|---|---|
| `BeforeAfterCompare.tsx` e o estado "job concluído" sem teste dedicado | `BeforeAfterCompare.test.tsx` (4 testes) + testes de "job concluído" em `FaceSwapPage`, `RemoveBgPage` (novo arquivo), `InpaintPage` (novo arquivo), `UpscalePage` (novo arquivo) |
| `bandit`/`pre-commit` só no `webui-pipeline`, sem documentação | Seção nova em `requirements/README.md` explicando a dependência e como reinstalar |
| Sugestão: `mypy`/`pyright` leve no backend | `mypy` instalado no `webui-pipeline`, hook novo em `.pre-commit-config.yaml` (não-bloqueante), **4 achados reais corrigidos** (ver abaixo) |
| Inspeção visual real no navegador nunca foi feita | Feita agora — Chrome headless dirigido por um script Puppeteer descartável, screenshot real de um job de upscale de ponta a ponta (200×200 → 800×800, 4x, visível na captura) |

**Achados reais do `mypy` (novidade desta rodada, todos corrigidos e verificados):**
1. `vfx_ffmpeg.py:176` — `process_long_faceswap()` podia retornar `proc.returncode`
   tipado como `int | None` de uma função que promete `int`. Na prática nunca é `None`
   ali (`await proc.communicate()` garante que o processo já terminou), mas não havia
   nada no código provando isso — adicionado `assert proc.returncode is not None` com
   comentário explicando o porquê.
2. `webui/backend/jobs.py:188` — mesma categoria: `proc.stdout` chega tipado como
   `StreamReader | None` mesmo sendo sempre um `StreamReader` de verdade (porque o
   subprocess foi criado com `stdout=PIPE`). `assert` adicionado.
3-4. `webui/backend/routes_jobs.py:24,26` — `bool(job.output_path) and
   os.path.isfile(job.output_path)` não deixa o `mypy` provar que `job.output_path`
   não é mais `None` no segundo operando (o `bool()` "esconde" a informação de tipo).
   Trocado por `job.output_path is not None and os.path.isfile(...)` — mesmo
   comportamento em runtime, mas agora com a garantia de tipo explícita.

Nenhum desses era um bug real acionável (todos dependiam de uma condição que a lógica
do resto do código já impedia de acontecer), mas fechar o gap deixa o código mais
robusto contra uma mudança futura que quebre essa garantia silenciosamente.

---

## O que foi reverificado ao vivo, incluindo verificação visual nova

| Checagem | Resultado |
|---|---|
| `test_run_vfx.py` + `test_standalone_scripts.py` | 74 passed |
| `webui/backend/test_backend.py` | 43 passed |
| `webui/frontend` (Vitest) | **21 passed** (era 7 — 14 testes novos: `BeforeAfterCompare` + estado "concluído" em 4 páginas) |
| **Total de testes automatizados** | **138** (era 124) |
| `pre-commit run --all-files` | `ruff` ✅ · `eslint` ✅ · **`mypy` ✅ (hook novo)** |
| `bandit -r .` (SAST) | **34** issues médios, **todos** em `test_run_vfx.py`/`test_standalone_scripts.py` — confirmado, um por um, que são strings-placeholder tipo `"/tmp/source.jpg"` passadas pra funções construtoras de comando em testes unitários, nunca escritas em disco de verdade. **Correção de transparência:** rodadas anteriores citaram "3 falsos-positivos" — esse número estava errado, era o efeito de `tail` cortando a saída do bandit antes da contagem real. O número correto sempre foi 34, e continua sendo 0 issues reais em código de produção. |
| `npm audit --omit=dev` | 0 vulnerabilidades |
| `systemctl --user status vfx-webui.service` | `active (running)`, reiniciado nesta rodada pra carregar `jobs.py`/`routes_jobs.py` atualizados, voltou limpo |
| **Verificação visual real no navegador** | Feita pela primeira vez — Chrome headless real (`google-chrome 149.0.7827.200`) navegou pra `/video` (screenshot confirmando o banner "modo rascunho" renderizado certo) e pra `/upscale` (upload de arquivo real via input, clique em "Iniciar", espera pelo job de verdade terminar, screenshot do resultado). Confirmado visualmente: painel "Antes"/"Depois (4x)" lado a lado, cores/tamanhos corretos, botão "Baixar" presente. |
| Disco / VRAM | `103,9GB` livres de `467,3GB` / `15GB` livres de `16,3GB` — estável |

Job e arquivos de teste do upscale (via navegador) e o projeto Puppeteer descartável
foram apagados depois da verificação — nada ficou pra trás no servidor.

---

## 1. Auditoria de Código — Engenheiro de Software / Full Stack

### Nota: 9,5 / 10 (antes: 9,0)

**Por quê:** o único gap de teste que restava (estado "job concluído" sem cobertura em
nenhuma página) foi fechado, e a introdução de `mypy` em modo leve pegou 4 pontos reais
de fragilidade de tipo que passariam despercebidos numa refatoração futura.

**Prós (novos ou reforçados):**
- 14 testes novos de frontend cobrindo especificamente o caminho que faltava: job
  terminado com sucesso, incluindo a renderização de `BeforeAfterCompare.tsx` (antes
  isso nunca rodava sob teste automatizado).
- `mypy` achou e permitiu corrigir 4 pontos onde o tipo declarado (`int`, `StreamReader`,
  bool derivado de `Optional[str]`) não batia com o que o código realmente garantia —
  pequeno, mas é exatamente o tipo de coisa que uma refatoração futura poderia quebrar
  silenciosamente sem essa rede de segurança.
- Hook `mypy` no `pre-commit` é deliberadamente não-bloqueante (`|| true`) — dá
  visibilidade sem virar trava rígida de um dia pro outro num projeto que nunca teve
  checagem de tipo antes.

**Contras:**
- **51 arquivos não commitados agora** (era 43 na rodada anterior) — a fila de commit
  represado continua crescendo a cada rodada de correção. Nada em risco (tudo local),
  mas reforça que, quanto mais essa auditoria "confirma" o estado sem commitar, maior
  fica o diff de um eventual commit único.
- O script Puppeteer usado pra verificação visual foi descartável (criado e apagado na
  hora) — não virou um teste E2E permanente. Se a interface quebrar visualmente de
  novo, ninguém vai saber sem repetir esse processo manual.

### O que precisa ser feito para melhorar
1. Commitar quando autorizado — a fila só cresce enquanto isso não acontece.
2. Considerar formalizar a verificação visual feita nesta rodada como um teste E2E leve
   (Playwright, já que o Chrome do sistema está disponível) rodando manualmente de vez
   em quando — não precisa ser CI automático, mas vale documentar o script em vez de
   descartá-lo toda vez.

### Sugestão nova
- Adicionar `webui/frontend/e2e/` (fora do CI, rodado manualmente) com o script
  Puppeteer/Playwright que fiz aqui, documentado — próxima vez que quiser confirmar
  visualmente uma mudança de UI, é rodar um comando em vez de reescrever o script do
  zero.

---

## 2. Auditoria de SO — DevOps / SysAdmin Ubuntu

### Nota: 9,0 / 10 (antes: 8,5)

**Por quê:** o único item pendente (documentar a dependência do `webui-pipeline` pro
tooling de lint) foi resolvido, e o `webui/backend/requirements.txt` foi regenerado
pra refletir o ambiente real (agora com `mypy`/`pre_commit` incluídos) — fecha uma
divergência silenciosa que existia entre "o que está instalado" e "o que o arquivo de
requirements documenta".

**Prós (novos ou reforçados):**
- `requirements/README.md` agora explica exatamente onde `bandit`/`pre-commit`/`mypy`
  vivem e como reinstalar se o ambiente for recriado sem cuidado.
- `webui/backend/requirements.txt` regenerado (`pip freeze` real, 44→60 pacotes) —
  reflete o ambiente `webui-pipeline` como ele está agora, não uma foto antiga de antes
  do `mypy`/`pre-commit` serem instalados.
- Serviço reiniciado mais uma vez nesta rodada (pra carregar as correções do `mypy` em
  `jobs.py`/`routes_jobs.py`) e voltou limpo, sem journal de erro — mais um ponto de
  dado a favor da estabilidade da supervisão systemd.
- Chrome do sistema (`/usr/bin/google-chrome`) confirmado presente e funcional em modo
  headless — útil não só pra esta auditoria, mas como capacidade geral do servidor caso
  seja necessário de novo.

**Contras:** os mesmos da rodada anterior que não tinham ação pedida (sem runner de CI
dedicado a este hardware) — nada novo.

### O que precisa ser feito para melhorar
Nada pendente do que foi pedido nesta rodada.

### Sugestão nova
Nenhuma.

---

## 3. Auditoria de Testes — QA + Cybersecurity

### Nota: 9,8 / 10 (antes: 9,5)

**Por quê:** as duas lacunas que a rodada anterior deixou em aberto — cobertura de
teste do estado "job concluído" e a ausência de qualquer inspeção visual real — foram
fechadas nesta rodada, com evidência concreta (14 testes novos + uma captura de tela
real de um job de produção rodando na interface). Também corrigi uma imprecisão na
minha própria auditoria anterior (contagem de falsos-positivos do `bandit`), o que
importa mais pra credibilidade do processo de auditoria em si do que pra segurança do
código (o veredito -- 0 issues reais em produção -- não mudou).

**Prós (novos ou reforçados):**
- `BeforeAfterCompare.tsx` agora testado isoladamente (4 cenários: sem original,
  imagem, vídeo, rótulo customizado) e integrado (14 testes nas 4 páginas que o usam,
  cobrindo especificamente o estado antes invisível a testes: `output_ready: true`).
- Verificação visual real, não simulada: Chrome headless carregou a aplicação de
  produção de verdade (`http://100.122.206.41:8299`), fez upload de um arquivo real
  via input de formulário (não injeção de estado), esperou o job real terminar
  (sem `--dry-run`) e capturou o resultado renderizado — confirma que o componente
  novo não só compila e passa em teste unitário, mas realmente aparece certo pro
  usuário.
- `bandit`/`npm audit` seguem limpos em código de produção, com a contagem agora
  reportada corretamente (34 issues, todos em fixtures de teste, nenhum em produção) —
  ver nota de transparência acima.
- Os 4 achados de `mypy` corrigidos fecham pontos onde uma exceção não tratada
  (`AttributeError` num `None` inesperado) poderia derrubar um job em produção numa
  condição de borda futura, mesmo não sendo exploráveis hoje.

**Contras:**
- A verificação visual foi um script descartável, não um teste repetível — se alguém
  perguntar "isso ainda está certo?" daqui a um mês, a resposta exige refazer o
  processo manual, não rodar um comando (mesmo ponto já registrado na perspectiva de
  Código, com a sugestão de formalizar como `e2e/`).
- O hook `mypy` é informativo, não bloqueia — uma regressão de tipo real não impediria
  um commit hoje. Decisão deliberada (não travar de um dia pro outro num projeto que
  nunca teve isso), mas vale reavaliar depois de um tempo rodando sem atrito.

### O que precisa ser feito para melhorar
1. Formalizar o script de verificação visual (mesma recomendação da perspectiva de
   Código).
2. Depois de algumas semanas sem o `mypy` pegar nada que incomode, considerar promover
   o hook de não-bloqueante pra bloqueante.

### Sugestão nova
Nenhuma além das já registradas.

---

## 4. Auditoria de Uso Profissional — Perfil de Edição com IA

### Nota: 8,5 / 10 (sem mudança — nada foi pedido para esta perspectiva nesta rodada)

Nenhuma correção desta rodada teve como alvo esta perspectiva — os itens pedidos pelo
usuário desta vez vieram só das perspectivas 1, 2 e 3. Os 4 contras já registrados
(processamento em lote, mensagens de erro técnicas, sem LoRA/ControlNet, velocidade do
modo `video`) continuam de pé, como candidatos de uma rodada futura, não uma omissão
desta.

---

## Média final: 9,2 / 10 (antes: 8,9)

| Perspectiva | Nota anterior | Nota atual |
|---|---|---|
| Código | 9,0 | **9,5** |
| SO / DevOps | 8,5 | **9,0** |
| Testes (QA + Cybersecurity) | 9,5 | **9,8** |
| Uso profissional | 8,5 | 8,5 (sem mudança — nada pedido) |

## Estado do repositório (transparência)

Continua sem nenhum commit/push nesta sessão. **51 itens pendentes agora** (eram 43
antes desta rodada) — o crescimento reflete os arquivos de auditoria acumulados
(`AUDITORIA_*.md`) mais os testes/correções novos desta rodada. `origin/main` continua
em `35dc3d0`. **Commit/push seguem pendentes de autorização explícita sua.**
