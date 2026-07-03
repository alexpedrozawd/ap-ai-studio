# Verificação visual manual (e2e)

Achado de auditoria (2026-07-03, perspectivas de Código e QA): a primeira verificação
visual real da webui (Chrome headless, não mockado) foi feita com um script
descartável, criado e apagado na hora da sessão. Este diretório formaliza esse script,
pra não precisar reescrever do zero da próxima vez que alguém quiser confirmar
visualmente uma mudança de UI.

**Deliberadamente fora do CI e do `pre-commit`** — isso não é um teste automatizado
que roda a cada commit, é uma ferramenta manual pra quando alguém (você ou uma sessão
futura do Claude) quiser ver com os próprios olhos se a interface está renderizando
certo, algo que o Vitest (que roda em `jsdom`, sem layout de verdade) não consegue
verificar sozinho.

## O que faz

1. Abre cada rota da webui (`/`, `/video`, `/rosto`, etc.) no estado inicial e tira um
   screenshot — pega regressão visual óbvia (CSS quebrado, componente que não
   renderiza) sem precisar rodar nenhum job de verdade.
2. Roda um fluxo real de ponta a ponta no modo `upscale` (upload de arquivo → clique em
   "Iniciar" → espera o job de verdade terminar, sem `--dry-run` → screenshot do
   resultado) — confirma que a comparação antes/depois (`BeforeAfterCompare.tsx`)
   aparece certa na tela de verdade, não só em teste unitário.
3. Limpa o job/upload de teste do servidor depois (mesma máquina onde o script roda —
   usa os caminhos conhecidos de `webui_jobs/`/`webui_uploads/` diretamente, sem
   precisar de uma rota de API de exclusão que não existe).

## Como rodar

Requer o Chrome do sistema (`/usr/bin/google-chrome`, já confirmado presente no
`ap-srv`) e a webui já rodando (`vfx-web-status` pra conferir).

```bash
cd webui/frontend/e2e
npm install       # so' na primeira vez (instala puppeteer-core)
npm run check
```

Por padrão os screenshots ficam em `./screenshots/` (gitignorado) pra serem
conferidos depois — peça pro Claude ler os PNGs, ou copie via Tailscale/scp pro seu
computador. Rode com `CLEAN_SCREENSHOTS=1 npm run check` se quiser que o script já
apague os PNGs no final.

## Por que não está no `package.json` principal do frontend

`puppeteer-core` teria um aviso `EBADENGINE` no Node 18.19.1 instalado no servidor
(mesma limitação já documentada pro `vitest`/`tailwindcss`) — isolar num
`package.json`/`node_modules` próprio evita poluir a árvore de dependências de
produção só por causa de uma ferramenta de verificação manual.
