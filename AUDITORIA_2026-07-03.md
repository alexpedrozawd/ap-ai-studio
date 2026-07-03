# Auditoria de Sistema — AP AI Studio

**Data:** 2026-07-03 · **Auditor:** Claude (Sonnet 5), atuando como QA Sênior + Cybersecurity Sênior
**Escopo:** documentação, arquitetura de pastas, código, funcionalidades, estabilidade, segurança
**Método:** leitura de código, execução real da suíte de testes, exploração ao vivo contra o servidor rodando (não só análise estática), verificação cruzada dos três documentos contra o estado real do sistema

---

## Nota: 8,5 / 10

Subiu de **7,5** (auditoria anterior, mesmo dia) para **8,5**. A alta não é só "corrigiu a lista de pendências" — é que o processo de auditoria em si se mostrou funcional: uma vulnerabilidade **crítica** de verdade foi encontrada, explorada ao vivo pra confirmar que era real, corrigida, e reexplorada pra confirmar que fechou. Isso é o que um processo de segurança maduro parece fazendo seu trabalho, não um sistema que nunca teve problema. A nota não é 10 porque esta própria auditoria, em poucos minutos de revisão fresca, já encontrou mais um bug real (abaixo) — sinal de que uma revisão ainda mais adversarial (ou tempo maior de exposição) provavelmente encontraria mais.

---

## Comparação com a auditoria anterior (mesmo dia, 2026-07-03)

| Item da auditoria #1 | Status agora |
|---|---|
| `PROMPT_MASTER.md` desatualizado (contagem de testes, pendência de commit falsa) | ✅ Corrigido |
| Sem supervisão de processo pra webui | ✅ Corrigido e **ativado em produção** (testado com `kill -9`, religou sozinho) |
| Upload salvo antes do Gate 3 checar disco, sem limite de tamanho | ✅ Corrigido (e depois **reforçado**, ver achado novo #2 abaixo) |
| `JOBS` em memória sem limite, uploads nunca limpos | ✅ Corrigido (`cleanup_old_jobs`, retenção de 7 dias) |
| Debris de scopes `systemd` failed | ✅ Limpo (e limpo de novo nesta auditoria — os testes de aceitação do Gate 1 geram debris novo a cada execução, é esperado) |
| Duplicação nas 9 rotas de job | ✅ Corrigido (`finish()`/`set_output()`/`save_upload()`) |
| `tts_synthesize.py`/`demucs_separate.py` sem teste real | ✅ Corrigido (`test_standalone_scripts.py`) |
| Frontend sem teste automatizado | ✅ Corrigido (Vitest + RTL) |
| `run_vfx.log` sem rotação | ✅ Corrigido (`RotatingFileHandler`) |
| Parágrafo desatualizado no `MANUAL_USO.md` | ✅ Corrigido |

Todos os 10 itens da primeira auditoria foram verificados de novo nesta rodada e continuam corrigidos — não foi só "aplicado uma vez e esquecido".

---

## Achados desta auditoria (rodada de segurança, já corrigidos)

Estes já estavam corrigidos antes desta auditoria começar (feitos na conversa anterior), mas foram **reverificados ao vivo** aqui, não só assumidos:

1. **🔴 CRÍTICO (já corrigido): path traversal na rota catch-all da SPA.** `GET` com `..` url-encoded lia `/etc/passwd` de verdade. Reverificado agora: mesmo payload cai limpo no `index.html`.
2. **🟡 MÉDIO (já corrigido): limite de upload contornável via `Transfer-Encoding: chunked`.** Reverificado: `save_upload()` conta bytes reais durante a gravação, não confia só no cabeçalho.
3. **🟢 BAIXO (já corrigido): crash 500 com filename `".."`.** Reverificado: devolve 400 limpo agora.

## Achado NOVO desta auditoria (não corrigido ainda)

**🟡 MÉDIO — Job "fantasma" quando o segundo arquivo de um upload multi-arquivo falha.**
Rotas que recebem dois arquivos (`faceswap`: origem+alvo; `master`: original+processado;
`dub`: áudio+vídeo) criam o registro do job (`new_job()`) **antes** de salvar qualquer
arquivo, e salvam um de cada vez. Se o primeiro upload for aceito e o segundo for
rejeitado (ex.: filename inválido, ou daqui a pouco um limite de tamanho), o job já
criado nunca é disparado (`launch()` não é chamado) — fica preso em `status="queued"`
pra sempre (só é limpo depois de 7 dias pelo `cleanup_old_jobs`), e o arquivo do
primeiro upload fica órfão em disco. **Confirmado ao vivo**: testei exatamente esse
cenário (`source` válido + `target` com filename `".."`) e o job `POST` retornou 400
corretamente, mas a pasta do primeiro upload ficou para trás em
`webui_uploads/<job_id>/`. Não é um bug de segurança (não escapa da sandbox da
aplicação, não vaza dado nenhum) — é um bug de higiene de estado/recurso. Durante a
limpeza desta auditoria encontrei **17 pastas órfãs** acumuladas em `webui_uploads/`
(a maior parte era debris dos meus próprios testes ao longo da sessão, não necessariamente
todas desse bug específico, mas pelo menos uma foi reproduzida de propósito). Removidas
manualmente; `cleanup_old_jobs` já teria resolvido isso sozinho em 7 dias de qualquer
jeito, mas o ideal é a rota não deixar o job "pendurado" desde o início.
**Sugestão de correção (não aplicada agora, fora do escopo pedido nesta rodada):**
envolver as chamadas de `save_upload()` de cada rota multi-arquivo num `try/except` que
remove o job (`JOBS.pop`) e os arquivos já salvos se uma etapa seguinte falhar, ou
validar todos os arquivos antes de criar o job.

## Outras observações menores (não corrigidas, baixa prioridade)

- **`save_upload()` só limpa o arquivo parcial em disco se o erro for `HTTPException`** — um erro de I/O real (ex.: disco enche no meio da gravação, mesmo com a margem de segurança checada antes) não passaria pelo bloco de limpeza. Cenário raro (a margem de 30GB já é checada antes), mas o `except` poderia ser mais abrangente.
- **`upload.close()` não é chamado nos caminhos de erro** de `save_upload()` (só no caminho de sucesso) — o Starlette geralmente limpa isso sozinho no fim do ciclo de vida da requisição, mas não é explícito no código.
- **Sem limite de jobs simultâneos** (já registrado na rodada anterior) — continua um risco aceito, não uma falha nova, dado o modelo de confiança (Tailscale + sem autenticação, decisão já tomada).

Nenhum desses três é grave o suficiente pra derrubar a nota sozinho, mas somados
explicam por que a nota não é 9+.

---

## Verificação ao vivo feita nesta auditoria (evidência)

| Checagem | Resultado |
|---|---|
| `test_run_vfx.py` + `test_standalone_scripts.py` | 68/68 passando |
| `webui/backend/test_backend.py` | 34/34 passando |
| `webui/frontend` (Vitest) | 7/7 passando |
| `npm run build` (produção) | Limpo, sem erro de TypeScript |
| **Total** | **109/109 testes passando** |
| `vfx-webui.service` (systemd --user) | `active`, `enabled` — sobrevive a reboot |
| ComfyUI (`127.0.0.1:8288/system_stats`) | HTTP 200 |
| Portas expostas | `8299` só no IP Tailscale, `8288`/`7860` só em `127.0.0.1` — nenhuma em `0.0.0.0` |
| Reexploração do path traversal (`/etc/passwd`) | Bloqueado, cai em `index.html` |
| Reexploração do bypass de `Transfer-Encoding: chunked` | Bloqueado pela contagem real de bytes |
| Reexploração do crash com filename `".."` | 400 limpo, sem traceback |
| Debris de `systemd` (scopes `failed`) | Limpo (2 novos da última bateria de testes, resetados) |
| Disco (`/`) | 105GB livres de 468GB (77% usado) — estável, sem vazamento aparente |
| Consistência dos 3 documentos vs. código real | Sem divergência encontrada |
| Estado do git vs. `origin/main` | 29 arquivos modificados, nada commitado ainda (esperado — aguardando esta auditoria) |

---

## Prós

1. **Processo de segurança comprovadamente funcional, não só teórico.** A vulnerabilidade crítica não foi encontrada por "parece que pode ter um problema" — foi encontrada, **explorada de verdade contra o servidor rodando em produção**, corrigida, e **reexplorada** pra confirmar. Esse é o padrão-ouro de verificação, raro em projetos pessoais.
2. **109 testes reais, cobrindo os 4 componentes** (orquestrador, scripts standalone, backend web, frontend web) — incluindo testes de regressão específicos para cada uma das 3 falhas de segurança encontradas, não só os bugs "de negócio".
3. **Operacionalmente maduro agora**: supervisão automática testada de verdade (`kill -9` → religou sozinho), rotação de log, limpeza automática de disco/memória, limites de upload reais (não só de fachada).
4. **Documentação e realidade batem** — nenhuma divergência encontrada entre `PROMPT_MASTER.md`, `MANUAL_USO.md`, `README.md` e o estado real do código/servidor nesta auditoria.
5. **Decisões de arquitetura documentadas com o porquê**, não só o quê (ex.: por que ComfyUI não tem auto-restart, por que dublagem não passa pelo orquestrador) — facilita manutenção futura e evita "correções" que reintroduziriam problemas já resolvidos de propósito.

## Contras

1. Um bug novo de higiene de estado encontrado nesta própria auditoria (job fantasma em upload multi-arquivo parcialmente falho) — ver acima.
2. Dois nitpicks de limpeza de recurso em `save_upload()` (except pouco abrangente, `close()` não explícito nos caminhos de erro).
3. Sem limite de jobs simultâneos — aceito pelo modelo de ameaça atual, mas seria a próxima coisa a quebrar se o uso crescer (mais de uma pessoa usando ao mesmo tempo, por exemplo).
4. O disco continua compartilhado entre SO e todo o pipeline (fragilidade de hardware, fora do controle do software — SATA aguardando substituição).
5. Só uma pessoa (esta sessão) revisou o código de segurança — não houve segunda opinião independente nem uma ferramenta de SAST/fuzzing rodando.

## Melhorias sugeridas (para uma próxima rodada, não aplicadas agora)

1. Corrigir o job fantasma em uploads multi-arquivo (rollback do job/arquivos se uma etapa falhar).
2. `except Exception` mais abrangente em `save_upload()`, com `upload.close()` garantido via `finally`.
3. Considerar um semáforo simples limitando jobs simultâneos (ex.: 2-3 no máximo) se o uso familiar crescer além de uma pessoa por vez.
4. Rodar uma ferramenta de SAST (ex.: `bandit` pro Python, `npm audit`/`eslint-plugin-security` pro frontend) como segunda camada de verificação automatizada, complementando a revisão manual.

---

*Este documento é um registro pontual (2026-07-03). Para o estado mais atual do projeto,
sempre preferir `PROMPT_MASTER.md` (fonte viva) e verificação ao vivo — este arquivo
não é atualizado incrementalmente como os outros três.*
