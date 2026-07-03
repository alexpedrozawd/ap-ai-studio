# Auditoria Multi-Perspectiva — AP AI Studio

**Data:** 2026-07-03 · **Auditor:** Claude (Sonnet 5)
**Método:** quatro papéis sênior independentes, cada um com nota própria. Verificação
ao vivo contra o servidor real (não só leitura de código) onde aplicável. Nenhuma
afirmação abaixo é suposição — onde não consegui confirmar algo (ex.: UFW sem senha de
sudo), isso está dito explicitamente em vez de inventado.

---

## 1. Auditoria de Código — Engenheiro de Software / Full Stack

### Nota: 7,5 / 10

**Por quê:** o código em si é limpo, tipado, bem comentado (comentários explicam o
*porquê*, não o *quê* — raro de ver). Mas faltam peças básicas de higiene de projeto
que qualquer repositório profissional teria desde o dia 1: nenhum arquivo de
dependências reprodutível, nenhum changelog estruturado, um arquivo central grande
demais pro que faz.

**Prós:**
- Boa cobertura de type hints em `run_vfx.py` (49 anotações de retorno pra 46 funções).
- `webui/backend` bem modularizado (uma rota por arquivo, helpers compartilhados em
  `jobs.py`/`utils.py`/`config.py`) — fácil de navegar.
- Frontend em TypeScript estrito, ESLint configurado e **zero warnings** (corrigi 1
  warning residual — `eslint-disable` órfão em `ComfyUINotice.tsx` — durante esta
  auditoria).
- Comentários no código documentam decisões reais com causa raiz, não just "o quê" —
  facilita manutenção futura por qualquer pessoa (ou IA) que pegar o projeto depois.
- `.gitignore` cobre o que precisa (build artifacts, `node_modules`, `__pycache__`).

**Contras:**
- **Nenhum `requirements.txt`/`pyproject.toml` em lugar nenhum do projeto** — nem pro
  `run_vfx.py` (5 ambientes Conda diferentes), nem pro `webui/backend`. Recriar
  qualquer ambiente do zero hoje exige garimpar comandos `pip install` espalhados em
  prosa dentro do `PROMPT_MASTER.md`, em vez de rodar um comando só.
- **Sem `CHANGELOG.md`** — todo o histórico de mudanças vive dentro do
  `PROMPT_MASTER.md` como texto corrido ("Fase 5... achado real..."), sem formato
  escaneável (data, versão, o que mudou). Funciona pra quem já conhece o projeto, mas
  não é o padrão que outro engenheiro esperaria.
- **`run_vfx.py` é um monólito de ~1500 linhas** fazendo orquestração, gates de
  segurança, construção de workflow do ComfyUI, comandos de FFmpeg e parsing de CLI
  tudo no mesmo arquivo. Funciona, mas dificulta navegação e teste isolado — dividir em
  módulos (`gates.py`, `workflows.py`, `ffmpeg.py`, `cli.py`) ajudaria.
- **Sem CI/CD** — os testes só rodam quando alguém lembra de rodar na mão. Um
  `.github/workflows/test.yml` simples (mesmo sem deploy, só rodando `pytest`/`npm
  test` a cada push) pegaria regressão automaticamente.
- **Sem `LICENSE`** — não crítico pra um projeto privado, mas ausente.

### O que precisa ser feito para melhorar
1. `requirements.txt` (ou `environment.yml`) por ambiente Conda, gerado com
   `pip freeze`/`conda env export` — comando único pra recriar qualquer um dos 5.
2. `CHANGELOG.md` simples, formato Keep a Changelog, alimentado daqui pra frente
   (o histórico dentro do `PROMPT_MASTER.md` continua valendo como "a razão", o
   changelog vira "o quê e quando", escaneável).
3. Dividir `run_vfx.py` em módulos menores por responsabilidade.

### Sugestões novas
- GitHub Actions rodando `pytest` + `npm test` a cada push (mesmo sem repo público,
  Actions funciona em repo privado gratuito até um limite generoso de minutos).
- `pre-commit` hook rodando `ruff`/`eslint --fix` automaticamente antes de cada commit.

---

## 2. Auditoria de SO — DevOps / SysAdmin Linux (Ubuntu)

### Nota: 8 / 10

**Por quê:** os invariantes críticos do servidor (documentados no `CLAUDE.md` global)
continuam intactos — verifiquei ao vivo, não assumi. A supervisão via `systemd` está
correta e testada. O que falta é um passo a mais de "defesa em profundidade" (limites
de recurso no próprio `systemd`) que custaria poucos minutos.

**Prós (tudo verificado ao vivo nesta auditoria, não assumido):**
- `rp_filter` continua em `2` (loose) — Tailscale não corre risco de quebrar.
- ClamAV já exclui `/home/ap/ai_pipeline` do scan noturno (`/etc/cron.d/clamav-nightly`,
  confirmado lendo o arquivo real).
- Nenhuma porta do projeto em `0.0.0.0` — `8299` só no IP Tailscale, `8288`/`7860` só
  em `127.0.0.1`.
- `vfx-webui.service` ativo, habilitado (sobrevive a reboot), e o auto-restart foi
  testado de verdade com `kill -9` (não só lido no arquivo do serviço).
- Sem nenhum evento de OOM-kill real no `dmesg` fora dos testes de aceitação
  propositais do Gate 1 — o sistema não travou de verdade em nenhum momento desta
  sessão.
- Uptime de 6 dias e 22h, load average baixo (0,23) no momento da checagem — sistema
  não está sob stress.
- 5 ambientes Conda somam ~28GB de disco — razoável, não é um problema de espaço hoje.

**Contras:**
- **`vfx-webui.service` não tem limite de memória/CPU nenhum** (`MemoryMax=infinity`,
  `CPUQuota=infinity`) — hoje o processo usa pouco (40-60MB), mas nada no nível do
  `systemd` o conteria se algum dia vazasse memória ou entrasse num loop. Contraditório
  com a filosofia de "jaula" que o próprio `run_vfx.py` já aplica nos subprocessos
  pesados — a webui em si ficou de fora dessa mesma disciplina.
- `journald` está usando limites padrão do sistema, não foi explicitamente calibrado
  (177,9MB usados hoje, sem risco imediato, mas sem teto explícito documentado).
- **Não consegui verificar o status do UFW nesta auditoria** — o comando pede senha de
  sudo que não tenho nesta sessão. Não vou inventar que está tudo certo; isso fica como
  não-verificado, não como confirmado.
- O disco SATA/SSD externo (`/mnt/dados_sata`) genuinamente está quebrado —
  confirmei ao vivo (tentativa de escrita/leitura real falhou com erro de I/O, apesar
  do `df -h` mostrar números que pareciam normais — um detalhe técnico real: `df` pode
  mostrar metadados desatualizados de um sistema de arquivos degradado). Já sabido e
  aceito pelo usuário (resolve na troca do hardware), citado aqui só pra registro
  factual, não como novo achado preocupante.

### O que precisa ser feito para melhorar
1. Adicionar `MemoryMax` generoso (ex.: 1GB — muito acima do uso real, só um teto de
   segurança) e `TasksMax` ao `vfx-webui.service`.
2. Confirmar o `ufw status verbose` na próxima vez que houver acesso a sudo — item
   pendente de verificação, não uma falha confirmada.

### Sugestões novas
- `systemd-run --user --scope` com `MemoryMax` similar ao que já existe pro modo vídeo
  também poderia envolver o processo do `vfx-webui.service` diretamente no unit file
  (`MemoryMax=1G` no `[Service]` já resolve, não precisa de scope extra).
- Um timer `systemd` simples rodando `df -h /` semanalmente e mandando um aviso (ex.:
  log ou notificação) se cair abaixo de alguma margem maior que os 30GB do Gate 3, pra
  dar alerta antecipado antes de chegar no limite crítico.

---

## 3. Auditoria de Testes — QA + Cybersecurity (equilíbrio, sem exagero)

### Nota: 8,5 / 10

**Por quê:** a cobertura de segurança que existe é real (3 vulnerabilidades
encontradas, exploradas ao vivo, corrigidas e reexploradas em rodadas anteriores desta
mesma sessão) e **nenhuma delas adicionou fricção real de uso** — verifiquei
especificamente isso nesta auditoria, já que foi pedido explicitamente pra não
exagerar na blindagem.

**Prós:**
- 112 testes automatizados, incluindo regressão específica pra cada vulnerabilidade
  encontrada (não só os bugs "de funcionalidade").
- As proteções adicionadas são discretas de propósito: limite de upload de 4GB (bem
  acima de qualquer arquivo real do fluxo — vídeos de família não chegam nem perto),
  margem de disco de 30GB (mesmo valor que o Gate 3 já usava antes, não é uma trava
  nova), validação de filename só rejeita nomes degenerados (`""`, `"."`, `".."`) que
  nenhum uso legítimo produziria.
- Confirmei nesta auditoria: **todos os checkboxes "Modo teste (--dry-run)" da
  interface começam desmarcados por padrão** em todas as 9 páginas — clicar "Iniciar"
  faz a coisa de verdade, do jeito que o usuário espera, sem surpresa.
- Decisão de não ter login está calibrada certo pro contexto (uso individual,
  confirmado pelo usuário) — autenticação obrigatória aqui seria fricção sem ganho de
  segurança real, dado que a rede Tailscale já é a barreira.
- SAST rodado de verdade (bandit + npm audit) nesta sessão, achados reais corrigidos,
  não só uma lista de sugestões nunca executadas.

**Contras:**
- **Sem validação de tipo de arquivo no upload** — hoje qualquer arquivo passa pela
  validação de nome e vai direto pro FFmpeg/FaceFusion, que vai falhar com um erro
  técnico cru se o formato for incompatível. Isso é tanto uma lacuna de robustez quanto
  de usabilidade (ver auditoria #4) — um aviso amigável na hora do upload ("isso não
  parece ser uma imagem") seria mais seguro *e* mais fácil de usar, não uma troca.
- Sem limite de jobs simultâneos (decisão já tomada e aceita pelo usuário — uso
  individual não precisa disso agora).
- Processo de revisão de segurança ainda é de uma pessoa só, numa sessão só — não
  substitui um histórico de revisões independentes ao longo do tempo.

### O que precisa ser feito para melhorar
1. Checar a extensão/assinatura do arquivo (ex.: primeiros bytes / `python-magic`) no
   upload e rejeitar com mensagem clara antes de gastar tempo processando algo que vai
   falhar de qualquer jeito — isso melhora segurança *e* usabilidade ao mesmo tempo,
   não é um trade-off.

### Sugestões novas
- Nenhuma sugestão de "blindagem extra" — a cobertura atual já está bem calibrada pro
  contexto (uso pessoal, rede já protegida pelo Tailscale). Adicionar mais camadas
  agora (rate limiting agressivo, CAPTCHA, 2FA) seria desproporcional ao risco real e
  iria contra o pedido explícito de manter o sistema acessível.

---

## 4. Auditoria de Uso Profissional — Editor de IA (imagem, vídeo, música, voz)

### Nota: 7 / 10

**Por quê:** pra um estúdio pessoal construído do zero, a amplitude de ferramentas é
genuinamente incomum (troca de rosto, geração de vídeo do zero, edição de imagem,
clonagem de voz, dublagem, isolamento de voz, geração de música, remoção de fundo — 9
funções). A interface web torna isso acessível pra quem nunca usou nada disso. Mas
comparado ao que ferramentas profissionais de mercado entregam hoje, várias
capacidades ficam abaixo do que um editor mais experiente esperaria — a maioria por
limitação de hardware real (GPU de 16GB), não por descuido.

**Prós:**
- **A função principal do projeto (trocar o rosto da família em cenas de filme) não
  tem limite artificial de resolução** — confirmei no código: o comando do FaceFusion
  passa o vídeo/foto de destino direto, sem forçar downscale. Um filme em 1080p ou 4K
  é processado nessa mesma resolução.
- Cobertura ampla: além de troca de rosto, dá pra gerar vídeo do zero a partir de
  texto ou animar uma foto parada, editar imagem com máscara, clonar voz, dublar,
  isolar voz de música, gerar trilha sonora e remover fundo — tudo pela mesma
  interface.
- Muito acessível pra quem começa do zero: formulário visual, sem precisar entender
  linha de comando, com prévia do resultado e botão de download. Testei isso
  pessoalmente em sessões anteriores desta auditoria, funcionando de ponta a ponta.
- As "jaulas" de segurança (Gates) protegem justamente o cenário mais comum de um
  iniciante quebrar as coisas: pedir demais da GPU/RAM sem saber o custo, e travar o
  servidor inteiro (que também é usado pra outras coisas na casa).

**Contras (limitações reais, não descuido):**
- **Geração de vídeo do zero (texto→vídeo, imagem→vídeo) trava em 720×720 pixels e
  ~15 segundos** (essa duração máxima nem foi testada de ponta a ponta ainda, só ~10s
  validados de verdade) — bem abaixo do padrão de produção atual (1080p/4K, e
  tipicamente 24-60fps; aqui o nativo é 16fps, interpolado pra ~30fps). Pra um
  profissional acostumado com ferramentas comerciais, isso é uma geração "rascunho",
  não entrega final.
- **Sem suporte a LoRA, ControlNet ou qualquer forma de customizar o modelo pra um
  rosto/estilo específico** — a fidelidade da geração de vídeo do zero depende só do
  prompt de texto, sem jeito de "ensinar" o modelo a reconhecer melhor uma pessoa
  específica (diferente da troca de rosto, que usa uma foto de referência direta e não
  precisa disso).
- **Sem ferramenta de upscale pra uma foto ou vídeo já existente** — o upscale (Real-
  ESRGAN) só roda internamente dentro do pipeline de geração de vídeo; não dá pra
  pegar uma foto antiga de baixa resolução e simplesmente aumentar a qualidade dela
  como uma função separada.
- **Sem processamento em lote** — cada job é um arquivo de cada vez; quem quiser
  trocar o rosto em 20 fotos precisa enviar uma de cada vez.
- **Sem comparação antes/depois lado a lado** no resultado — só mostra o resultado
  final, não uma visão comparativa com o original.
- **Mensagens de erro técnicas quando algo falha** — o painel de log mostra a saída
  crua do processo (ex.: linhas de log do Gate, tracebacks de subprocesso), o que é
  ótimo pra transparência/depuração mas intimidador pra um iniciante completo que só
  queria saber "o que eu fiz de errado".
- **Renders de vídeo do zero são de 3 a 10 vezes mais lentos** que um render que
  coubesse inteiro na VRAM — esperado e já documentado, mas um profissional
  acostumado a nuvem/GPU dedicada vai sentir a diferença.

### O que precisa ser feito para melhorar
1. Documentar de forma bem visível (já parcialmente feito no `MANUAL_USO.md`) que a
   geração de vídeo do zero é modo "rascunho/experimental" e a troca de rosto é o modo
   "produção" — pra calibrar a expectativa antes de começar, não depois de frustrar.
2. Validação de tipo de arquivo com mensagem amigável (mesmo item da auditoria #3,
   ajuda dos dois lados).

### Sugestões novas (melhorias reais pro caso de uso do projeto)
- Um modo `--mode upscale` separado, reaproveitando o node Real-ESRGAN que já está
  instalado, pra restaurar fotos antigas de família — encaixa direto no objetivo
  original do projeto e usa um modelo que já está baixado, custo de implementação
  baixo.
- Visualização antes/depois lado a lado na interface web pras funções de imagem
  (trocar rosto, remover fundo, editar) — melhoria de UX de baixo custo, alto retorno
  pra quem está comparando resultados.
- Se algum dia o hardware permitir (upgrade de GPU), revisitar o teto de 720×720 —
  hoje é uma limitação real de VRAM (16GB), não de design.

---

## Resumo das 4 notas

| Perspectiva | Nota |
|---|---|
| Código (Engenheiro de Software) | 7,5 / 10 |
| Sistema Operacional (DevOps/SysAdmin) | 8,0 / 10 |
| Testes (QA + Cybersecurity) | 8,5 / 10 |
| Uso profissional de edição com IA | 7,0 / 10 |
| **Média simples** | **7,75 / 10** |

Nenhuma das quatro notas é uma repetição das auditorias anteriores desta sessão — cada
uma olhou o sistema por uma lente diferente das já usadas (código/estrutura, SO/
estabilidade, equilíbrio segurança-vs-uso, e capacidade real como ferramenta de
edição), e cada uma encontrou pelo menos um achado novo verificado ao vivo (o warning
do ESLint corrigido, a ausência de `requirements.txt`, a falta de limite de memória no
`systemd`, a ausência de validação de tipo de arquivo, e as limitações reais de
resolução/duração da geração de vídeo).

---

*Documento gerado em 2026-07-03. Correções pontuais já aplicadas durante esta
auditoria (fix do warning do ESLint) estão refletidas no código, mas ainda não foram
commitadas — aguardando confirmação, mesma regra já combinada.*
