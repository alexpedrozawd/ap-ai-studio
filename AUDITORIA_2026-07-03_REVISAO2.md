# Auditoria Multi-Perspectiva — AP AI Studio (2ª revisão, confirmação)

**Data:** 2026-07-03 · **Auditor:** Claude (Sonnet 5)
**Método:** mesmo esquema das duas auditorias anteriores — quatro papéis sênior
independentes, nota própria por perspectiva, verificação ao vivo contra o servidor
real (não releitura de código sozinha).

**Nota de transparência importante, antes de tudo:** entre a auditoria anterior
([`AUDITORIA_2026-07-03_FINAL.md`](AUDITORIA_2026-07-03_FINAL.md)) e esta, **nenhuma
linha de código foi alterada** — não houve novo pedido de correção nem nova
implementação no intervalo. Por isso esta rodada é uma **reverificação/confirmação ao
vivo**, não uma nova rodada de mudanças: refiz as checagens do zero (suíte de testes
completa, lint, SAST, auditoria de dependências, estado do serviço/disco/VRAM) pra
confirmar que nada regrediu sozinho (ex.: um serviço que caiu, um teste que ficou
instável) — não pra inventar achados novos onde não há mudança real que os justifique.
As notas abaixo, portanto, coincidem com a rodada anterior onde a evidência confirma o
mesmo estado, e isso é o resultado esperado, não um erro de auditoria.

---

## O que foi reverificado ao vivo agora (não reaproveitado de memória)

| Checagem | Resultado |
|---|---|
| `test_run_vfx.py` | 68 passed |
| `test_standalone_scripts.py` | 6 passed |
| `webui/backend/test_backend.py` | 43 passed |
| `webui/frontend` (Vitest) | 7 passed |
| **Total** | **124/124 passando** |
| `pre-commit run --all-files` | `ruff` (pyflakes) ✅ · `eslint` ✅ |
| `bandit -r .` (SAST) | 0 issues médio/alto em código de produção (3 falsos-positivos em fixtures de teste, mesmos de sempre) |
| `npm audit --omit=dev` (`webui/frontend`) | 0 vulnerabilidades |
| `systemctl --user status vfx-webui.service` | `active (running)` há 35min, sem reinício, sem erro no journal |
| Bind de rede da webui | só `100.122.206.41:8299` — sem `0.0.0.0` |
| Disco (`/`) | `105GB` livres de `468GB` (77%) — igual às duas rodadas anteriores |
| VRAM livre | `15GB` de `16.3GB` (ComfyUI ocioso) — normal |
| `git status` | 43 itens pendentes (os mesmos 42 da rodada anterior + este próprio arquivo novo) — nada commitado, `origin/main` continua em `35dc3d0` |

Nenhuma divergência encontrada em relação à rodada anterior — o sistema está estável.

---

## 1. Auditoria de Código — Engenheiro de Software / Full Stack

### Nota: 9,0 / 10 (confirmada, sem mudança)

**Prós (reconfirmados):** `requirements/` reprodutível, `CHANGELOG.md` real,
`run_vfx.py` modularizado em 7 arquivos (429 linhas no orquestrador), CI +
`pre-commit` ativos e passando agora mesmo, `LICENSE` presente.

**Contras (os mesmos da rodada anterior, ainda não fechados — não foi pedido nesta
rodada):**
- `BeforeAfterCompare.tsx` e o estado "job concluído" (`output_ready: true`) de
  qualquer página continuam sem teste automatizado dedicado.
- O job de CI `orquestrador-melhor-esforco` continua com `continue-on-error: true`
  (depende de GPU/Conda/`systemd --user` que um runner genérico não tem).
- Agora **43 arquivos** com mudanças não commitadas (era 42 antes desta própria
  auditoria ser escrita) — o próprio ato de gerar este documento aumenta a fila em 1.
  Continua sem risco de perda (tudo local), só reforça que o commit está represado.

### O que precisa ser feito para melhorar
Os mesmos 3 itens já listados na auditoria anterior (teste do `BeforeAfterCompare.tsx`
+ estado "concluído", runner de CI dedicado quando existir, commit em lotes quando
autorizado) — nada novo a acrescentar porque nada novo mudou.

### Sugestão nova
Nenhuma além da já registrada (`mypy`/`pyright` leve no backend).

---

## 2. Auditoria de SO — DevOps / SysAdmin Ubuntu

### Nota: 8,5 / 10 (confirmada, sem mudança)

**Prós (reconfirmados):** serviço `vfx-webui.service` seguiu rodando os 35 minutos
inteiros entre as duas auditorias sem cair nem precisar de intervenção — é o teste de
estabilidade mais forte que existe (tempo real em produção, não um restart forçado
pra "provar" que funciona). `nvidia-smi` continua chamado por caminho absoluto. Nenhum
invariante do baseline de segurança (Tailscale, SSH, UFW, ClamAV) foi tocado.

**Contras (os mesmos):** ainda sem runner de CI dedicado a este hardware; `bandit`/
`pre-commit` ainda vivem só no `webui-pipeline`.

### O que precisa ser feito para melhorar
Mesma recomendação da rodada anterior (documentar a dependência do `webui-pipeline`
pro tooling de lint). Nenhuma ação de sistema nova necessária.

### Sugestão nova
Nenhuma.

---

## 3. Auditoria de Testes — QA + Cybersecurity

### Nota: 9,5 / 10 (confirmada, sem mudança)

**Prós (reconfirmados):** validação de assinatura de arquivo, `bandit` e `npm audit`
limpos, as 3 falhas de segurança de rodadas anteriores (path traversal, limite de
upload contornável, crash com filename `".."`) seguem corrigidas e sem sinal de
regressão, bug de "job fantasma" segue fechado nas 9 rotas de upload (incluindo
`upscale`).

**Contras (os mesmos):** cobertura zero do estado "resultado pronto" na UI (mesmo
ponto da perspectiva de Código); inspeção visual real no navegador ainda não foi feita
nesta sessão — continua sendo uma checagem pendente pro usuário fazer quando acessar a
interface, não algo que este ambiente de trabalho consegue fazer sozinho.

### O que precisa ser feito para melhorar
Mesmos 2 itens da rodada anterior.

### Sugestão nova
Nenhuma — os itens fora de escopo (concorrência, revisão) continuam fora de escopo por
decisão já tomada pelo usuário.

---

## 4. Auditoria de Uso Profissional — Perfil de Edição com IA

### Nota: 8,5 / 10 (confirmada, sem mudança)

**Prós (reconfirmados):** `--mode upscale`, comparação antes/depois e a mensagem
"rascunho vs. produção" (manual + `PROMPT_MASTER.md` + banner na webui) seguem no
lugar e sem sinal de quebra.

**Contras (os mesmos, registrados por transparência, não pedidos nesta rodada):** sem
processamento em lote; mensagens de erro técnicas pra iniciante; sem LoRA/ControlNet;
modo `video` mais lento do que a VRAM permitiria (tradeoff aceito).

### O que precisa ser feito para melhorar
Nada pendente do que foi pedido — os 4 contras acima seguem como candidatos de uma
futura rodada.

### Sugestão nova
Nenhuma além da já registrada ("modo simples" de mensagens de erro).

---

## Média final: 8,9 / 10 (confirmada, sem mudança em relação à rodada anterior)

| Perspectiva | Nota |
|---|---|
| Código | 9,0 |
| SO / DevOps | 8,5 |
| Testes (QA + Cybersecurity) | 9,5 |
| Uso profissional | 8,5 |

## Estado do repositório (transparência)

Continua sem nenhum commit/push nesta sessão. 43 itens pendentes agora (os 42 de
antes + este arquivo). `origin/main` continua em `35dc3d0`. **Commit/push seguem
pendentes de autorização explícita sua**, como combinado desde o início.
