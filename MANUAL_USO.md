# Manual do Usuário — AP AI Studio

> Guia didático, escrito para quem nunca usou esse tipo de ferramenta. Cobre todas as
> funções que existem hoje no pipeline (atualizado em 2026-07-03), verificadas ao vivo
> contra o código real (`run_vfx.py`, `tts_synthesize.py`, `demucs_separate.py`,
> `webui/`) e o estado real do servidor — não é um resumo do `PROMPT_MASTER.md`, é um
> manual operacional derivado dele. Onde alguma coisa ainda não está pronta ou tem uma
> limitação real, isso está dito explicitamente, sem maquiagem.

> 💡 **Atalho:** existem comandos curtos (`vfx-rosto`, `vfx-video`, `vfx-ajuda` etc.) que
> já resolvem o ambiente Conda certo por trás e evitam digitar o comando completo do
> `run_vfx.py` toda vez. Já estão instalados e ativos em qualquer terminal novo — veja a
> seção 10 para a lista completa. As seções 2 a 4 abaixo continuam explicando o comando
> "por baixo do capô", pra você entender o que cada atalho está fazendo de verdade.

> 🖥️ **Interface web:** se preferir nem usar terminal, existe uma interface gráfica
> acessível pelo navegador (`vfx-web`) — veja a seção 11. Já cobre as 11 funções do
> pipeline (Fases A e B completas + upscale).

---

## 0. Antes de começar — o que é isto e quais são os limites

O **AP AI Studio** é um pipeline pessoal de edição de vídeo/imagem com IA, rodando
inteiramente no seu próprio servidor (`ap-srv`). Ele existe para um objetivo específico:
inserir você, sua esposa e seu filho em cenas de filmes que ele gosta (Como Treinar seu
Dragão, Vingadores, Jurassic World etc.), trocando o rosto de um personagem pelo de vocês.
Mas o conjunto de ferramentas cresceu e hoje também faz geração de vídeo do zero, edição
de imagem, clonagem de voz, remoção de ruído e geração de música.

**Duas regras fixas, decididas antes deste manual e que não mudam:**
1. **Uso estritamente privado/familiar.** Os vídeos não saem do servidor nem são
   publicados — isso existe para respeitar direitos autorais do material fonte (os
   filmes originais).
2. **Nunca contornar o filtro de proteção de idade do FaceFusion** (o "age-analyzer"),
   mesmo sendo uso familiar privado. A ferramenta resolve a troca de rosto sem precisar
   disso, usando o **modo de rosto de referência** (você aponta uma foto da pessoa certa,
   em vez de deixar o sistema "adivinhar" por filtros).

Tudo o que segue assume essas duas regras como pano de fundo.

**Uma distinção importante de qualidade, pra calibrar expectativa:**
- **Troca de rosto** (seção 4.1-4.3) é o modo de **produção** do pipeline — a imagem/vídeo
  original continua com a qualidade original, só o rosto é trocado. É o que dá o
  resultado final pronto pra assistir com a família.
- **Geração de vídeo do zero, texto→vídeo ou imagem→vídeo** (seção 4.4/4.5) é modo
  **rascunho/experimental** — resolução travada em no máximo 720×720, poucos segundos de
  duração, e o resultado tem qualidade visivelmente inferior a um vídeo de verdade
  (esperado: é um modelo pequeno, otimizado pra caber nesta GPU, não uma ferramenta de
  produção final). Útil pra testar ideias e prompts, não pra entregar como resultado
  definitivo.
- **Upscale standalone** (seção 4.13, novo) ajuda a compensar isso pra fotos/vídeos já
  prontos — mas não "conserta" a geração do zero, só amplia resolução do que já existe.

---

## 1. Conceitos básicos (glossário para quem começa do zero)

Antes de digitar qualquer comando, vale entender o vocabulário. Pule esta seção se já
souber o que é terminal, ambiente virtual, GPU/VRAM etc.

| Termo | O que é, em termos simples |
|---|---|
| **Terminal** | A janela de texto onde você digita comandos em vez de clicar em ícones. Tudo neste manual roda ali. |
| **Ambiente Conda** | Uma "caixa isolada" com uma versão específica de Python e de bibliotecas, separada do resto do sistema. Este projeto usa **4 caixas diferentes** (explicado abaixo) porque partes do pipeline exigem versões de biblioteca que brigam entre si — misturar tudo numa caixa só quebraria alguma parte. |
| **GPU / VRAM** | A placa de vídeo (RTX 5060 Ti, 16GB) e a memória dela. A maior parte do trabalho pesado (gerar imagem/vídeo, trocar rosto) roda nela, não no processador comum. VRAM é um recurso escasso e compartilhado com o Ollama (seu servidor de LLM/Qwen) — por isso existem os "Gates" (seção 3). |
| **ComfyUI** | O motor por trás da geração de imagem e vídeo (texto→vídeo, imagem→vídeo, edição de imagem, geração de música). Roda como um servidor local na porta `8288`, e o `run_vfx.py` conversa com ele por HTTP. |
| **FaceFusion** | A ferramenta especializada em rosto: troca de rosto, sincronia labial (dublagem), remoção de fundo. Roda como programa de linha de comando, não como servidor contínuo. |
| **`run_vfx.py`** | O "controle remoto" único: um script Python que você chama do terminal, e ele decide se vai conversar com o ComfyUI, com o FaceFusion, ou rodar um script auxiliar (TTS, Demucs), sempre checando segurança antes (Gates). |
| **Gate (portão)** | Uma pausa de segurança que pede sua confirmação `[Y/n]` antes de fazer algo que consome muita memória, VRAM ou disco. Detalhado na seção 3. |
| **`--dry-run`** | Modo "simulação": roda todas as checagens de segurança mas não executa nada de verdade (nenhum vídeo é gerado, nenhum arquivo é escrito). Útil pra testar se os comandos estão certos antes de gastar tempo/GPU de verdade. |
| **`--auto-approve`** | Pula a pergunta `[Y/n]` dos Gates 1 e 2 (não do Gate 3, que nunca é pulável). Útil depois que você já validou manualmente que os limites fazem sentido, pra não ter que confirmar toda vez em testes rápidos. |

### Os 4 ambientes Conda e por que existem

Você vai precisar saber qual ambiente ativar dependendo do que for fazer:

| Ambiente | Para que serve | Por que é separado dos outros |
|---|---|---|
| `vfx-pipeline` | Rodar o `run_vfx.py` em si, e o ComfyUI (vídeo, imagem, música) | Base do projeto |
| `facefusion-pipeline` | O FaceFusion é chamado *de dentro* do `vfx-pipeline` automaticamente, mas se você quiser rodar o FaceFusion sozinho (ex.: interface visual) | Precisa de `numpy` numa versão fixa que colide com o ComfyUI |
| `tts-pipeline` | Só usado internamente pelo `run_vfx.py --mode tts` | Precisa de `transformers` numa versão exata |
| `noise-pipeline` | Só usado internamente pelo `run_vfx.py --mode denoise` | Precisa de uma versão de `torch` específica pra essa GPU |

**Na prática:** para 90% do trabalho (todos os `--mode` do `run_vfx.py`), você só precisa
ativar **um** ambiente — o `vfx-pipeline`. Ele mesmo chama os outros três por baixo dos
panos, trocando de intérprete Python automaticamente. Você só ativa os outros ambientes
na mão se quiser usar o FaceFusion pela interface visual (seção 4.9 e 5).

---

## 2. Preparando o terminal a cada sessão de trabalho

Isto é o "ritual de abertura" — faça isso toda vez que for usar o pipeline.

### 2.1 Ativar o ambiente certo

```bash
conda activate vfx-pipeline
cd /home/ap/ap-ai-studio
```

> ⚠️ **Não use `conda run -n vfx-pipeline ...`** para chamar o `run_vfx.py` diretamente.
> Isso é um bug conhecido e documentado no próprio código: `conda run` não repassa o
> teclado (stdin) pro processo filho, então as perguntas `[Y/n]` dos Gates travam com um
> erro `EOFError`. Sempre `conda activate` primeiro, depois rode o comando normalmente.

### 2.2 Verificar se o ComfyUI precisa estar ligado

Isto é importante e não é óbvio: **nem todo `--mode` liga o ComfyUI sozinho.**

| Se você vai usar... | O ComfyUI precisa já estar rodando? |
|---|---|
| `--mode video` (gerar/animar vídeo) | **Não** — o próprio comando liga (e religa) o ComfyUI sozinho, dentro da jaula de memória correta. |
| `--mode inpaint`, `--mode music` | **Sim** — o comando só verifica se já está respondendo; se não estiver, ele espera até 60s e falha com timeout. |
| `--mode faceswap`, `--mode removebg`, `--mode tts`, `--mode denoise`, `--mode master` | Não precisa (não usam o ComfyUI, ou só tentam liberar VRAM dele se ele por acaso estiver ligado). |

Para checar se está rodando, num outro terminal (ou no mesmo, rapidamente):

```bash
curl -s http://127.0.0.1:8288/system_stats | head -c 200
```

Se voltar um JSON, está no ar. Se der erro de conexão recusada, precisa ligar manualmente
antes de usar `inpaint` ou `music`:

```bash
conda activate vfx-pipeline
cd /home/ap/ai_pipeline/ComfyUI
python main.py --port 8288 --listen 127.0.0.1
```

Deixe esse terminal aberto (ou rode em segundo plano com `&` / `tmux`/`screen` se preferir
não travar o terminal). Ele só escuta em `127.0.0.1` (só o próprio servidor acessa) — é
proposital, por segurança (ver a regra de firewall no `CLAUDE.md` global do servidor).

**Para acessar a interface visual do ComfyUI de outro computador** (seu notebook, por
exemplo) via Tailscale, é preciso ligar apontando pro IP do Tailscale em vez de
`127.0.0.1`:

```bash
python main.py --port 8288 --listen 100.122.206.41
```

E então abrir `http://100.122.206.41:8288` no navegador do outro aparelho (que também
precisa estar na sua rede Tailscale). **Nunca** use `--listen 0.0.0.0` — isso exporia a
porta pra internet, e a política deste servidor proíbe isso.

### 2.3 Checar espaço em disco (opcional, mas recomendado antes de renders grandes)

```bash
df -h /
```

O próprio `run_vfx.py` já checa isso automaticamente (Gate 3) e aborta se sobrar menos de
30GB — mas rodar `df -h /` antes evita começar um trabalho longo pra só descobrir o
problema no meio.

---

## 3. Entendendo os "Gates" — o que são aquelas perguntas `[Y/n]`

Toda vez que você roda `run_vfx.py` (fora do modo `--dry-run`), até três perguntas podem
aparecer no terminal. Elas existem porque este mesmo servidor também roda seu Ollama
(Qwen) e é seu PC do dia a dia — os Gates evitam que um render trave a máquina inteira.

1. **Gate 1 — Jaula de memória.** Antes de rodar qualquer coisa pesada, o script avisa o
   limite de RAM que vai aplicar no subprocesso (`24GB` no modo padrão, `28GB` + `4GB` de
   swap de emergência no modo `video`). Responda `Y` (ou só Enter) pra prosseguir.
2. **Gate 2 — VRAM.** Mostra quanta VRAM está livre agora e avisa se está abaixo de
   15GB (pico esperado de uso). No modo `video`, também mostra RAM livre e swap em uso.
   Se estiver apertado por causa do Qwen carregado no Ollama, você pode descarregar o
   modelo antes de continuar.
3. **Gate 3 — Disco.** Confirma que há espaço suficiente (mínimo 30GB livres em `/`) antes
   de escrever arquivos grandes. **Este gate nunca pode ser pulado**, nem com
   `--auto-approve` — se o disco estiver abaixo da margem, o comando aborta sozinho, sem
   perguntar.

Responder `n` (ou qualquer coisa que não seja "sim") em qualquer gate cancela a operação
sem executar nada.

**Atalhos:**
- `--dry-run`: mostra os três gates (sem aplicar nada de verdade) e para — nenhum
  subprocesso roda, nenhum arquivo é escrito. Bom pra validar que os argumentos do
  comando estão certos.
- `--auto-approve`: responde "sim" automaticamente aos Gates 1 e 2 (não ao Gate 3). A
  decisão continua sendo gravada no log mesmo assim.

Tudo fica registrado em `/home/ap/ai_pipeline/logs/run_vfx.log` — se algo der errado numa
execução que você deixou rodando sem acompanhar, é ali que você vai olhar depois.

---

## 4. Receitas passo a passo, por função

Todos os comandos abaixo assumem que você já fez a seção 2 (ambiente ativado, e ComfyUI
ligado quando necessário). Troque os caminhos de exemplo (`/home/ap/...`) pelos seus
arquivos reais.

### 4.1 Trocar o rosto em uma foto (face swap)

Use quando quiser colocar o rosto de alguém (seu filho, por exemplo) por cima do rosto de
um personagem numa imagem/frame parado.

```bash
python run_vfx.py --mode faceswap \
  --source /home/ap/fotos/rosto_do_filho.jpg \
  --target /home/ap/cenas/frame_do_heroi.jpg \
  --output /home/ap/ai_pipeline/resultado_faceswap.jpg
```

- `--source`: a **foto da pessoa real** cujo rosto vai ser inserido (quanto mais nítida e
  de frente, melhor o resultado).
- `--target`: a cena/imagem onde o rosto vai ser colocado.
- `--output`: onde salvar o resultado.

O sistema já limpa automaticamente metadados EXIF (localização, autor etc.) da foto de
origem antes de processar — não precisa fazer isso manualmente.

### 4.2 Trocar o rosto em um vídeo curto

Mesmo comando, só que `--target` é um arquivo de vídeo em vez de imagem:

```bash
python run_vfx.py --mode faceswap \
  --source /home/ap/fotos/rosto_do_filho.jpg \
  --target /home/ap/cenas/cena_do_filme.mp4 \
  --output /home/ap/ai_pipeline/resultado_faceswap.mp4
```

### 4.3 Trocar o rosto em um vídeo **longo** (cena inteira de um filme)

Para vídeos mais longos, adicione `--chunk-seconds N`: o sistema divide o vídeo em pedaços
de N segundos, processa cada um, e junta tudo de volta no final automaticamente.

```bash
python run_vfx.py --mode faceswap \
  --source /home/ap/fotos/rosto_do_filho.jpg \
  --target /home/ap/cenas/cena_longa.mp4 \
  --output /home/ap/ai_pipeline/resultado_final.mp4 \
  --chunk-seconds 30
```

Use isto sempre que o vídeo de destino for longo o suficiente pra estourar memória se
processado de uma vez só — pedaços de 20 a 60 segundos costumam ser um bom ponto de
partida (não há um número "certo" testado para todo tipo de vídeo; ajuste se der erro de
memória).

### 4.4 Criar um vídeo do zero, só a partir de texto (texto → vídeo)

> ⚠️ **Modo rascunho, não produção** (ver seção 0). Diferente da troca de rosto, aqui
> você está pedindo pro modelo *inventar* um vídeo do zero — a resolução e a duração são
> limitadas pela VRAM desta GPU (16GB), e o resultado tem qualidade de teste/rascunho, não
> de entrega final. Se você quer aumentar a resolução de algo que já existe (uma foto
> antiga, por exemplo), use o `--mode upscale` da seção 4.13 em vez deste.

Isso **não** usa uma foto de referência — o vídeo é inteiramente gerado a partir da
descrição que você escrever.

```bash
python run_vfx.py --mode video \
  --prompt "um dragão azul voando sobre um vale verde ao pôr do sol" \
  --width 480 --height 480 --num-frames 161
```

- `--prompt`: a descrição em texto do que deve aparecer (em inglês costuma dar resultado
  melhor que em português, mas português também funciona).
- `--width`/`--height`: resolução. Padrão é `320x320`; o teto absoluto que o sistema aceita
  é `720x720` — acima disso o comando recusa de propósito, porque os limites de memória
  dos Gates foram calculados pra essa faixa.
- `--num-frames`: quantidade de quadros. O modelo roda nativamente a 16 quadros/segundo,
  então `161` quadros ≈ 10 segundos (é o padrão). O teto é `241` (~15s) — **atenção:**
  essa duração maior ainda não foi testada de ponta a ponta no momento em que este manual
  foi escrito (só validamos ~10s de verdade); é mais arriscado quanto a travar por falta
  de memória.
- `--blocks-to-swap` (avançado, opcional): reduz o padrão (`20`) pra acelerar o render,
  usando mais VRAM de pico. **Testado ao vivo:** `--blocks-to-swap 5` rendeu ~33% mais
  rápido em testes curtos e ficou seguro até ~80 quadros em 480×480 (~12GB de pico) —
  mas **travou o ComfyUI com falta de memória de verdade** nos 161 quadros padrão na
  mesma resolução (precisou religar o ComfyUI depois). Use só em renders curtos e por
  sua conta e risco; não mude o padrão pra renders no tamanho normal sem testar antes
  com uma duração pequena primeiro.

O resultado sai automaticamente com interpolação de quadros (fluidez de ~30fps, mesmo o
modelo gerando a 16fps nativos) e já em resolução ampliada 4x (upscale automático). Ele é
salvo dentro de `ComfyUI/output/` — acompanhe o terminal, que mostra o progresso e o nome
do arquivo gerado ao final.

### 4.5 Animar uma foto existente (imagem → vídeo)

Mesmo comando do item anterior, mas adicionando `--source-image` com uma foto real. Em vez
de criar do zero, o modelo anima a partir dessa imagem, seguindo o que o prompt descreve
(ex.: "vira a cabeça pra olhar de lado", "sorri").

```bash
python run_vfx.py --mode video \
  --source-image /home/ap/fotos/foto_de_familia.jpg \
  --prompt "a pessoa vira lentamente a cabeça para olhar de lado e sorri" \
  --width 480 --height 480 --num-frames 161
```

Todos os limites e comportamento de `--width`/`--height`/`--num-frames` são os mesmos do
item 4.4.

### 4.6 Editar/remover algo de uma imagem (inpainting)

Serve para apagar um objeto/pessoa de uma foto e preencher o espaço com outra coisa (ex.:
remover uma pessoa de fundo, trocar o cenário de uma área específica).

**Pré-requisito:** o ComfyUI precisa já estar rodando (ver seção 2.2) — este modo não liga
ele sozinho.

Você precisa preparar uma **máscara**: uma imagem do mesmo tamanho da foto original, em
preto e branco, onde **branco = área a apagar/reescrever** e **preto = área a manter
intacta**. Pode desenhar isso em qualquer editor de imagem simples (até o Paint/GIMP
servem).

```bash
python run_vfx.py --mode inpaint \
  --source-image /home/ap/fotos/foto_original.jpg \
  --mask-image /home/ap/fotos/mascara.png \
  --prompt "fundo de floresta com árvores verdes, iluminação natural" \
  --output /home/ap/ai_pipeline/foto_editada.jpg
```

**Importante:** sempre use `--prompt` descrevendo o que deve aparecer na área apagada. Sem
isso, o resultado tende a ficar estranho e sem relação com o resto da cena (achado real,
confirmado em teste) — o sistema avisa isso no terminal se você esquecer, mas não bloqueia
a execução.

**Avançado — `--use-depth-controlnet`:** guia a edição por um mapa de profundidade da
própria foto original (ControlNet SDXL), além da máscara manual — ajuda a manter a
composição/perspectiva da cena coerente ao editar (ex.: trocar o fundo mantendo objetos
em primeiro plano em escala/posição condizentes). Desligado por padrão (custo extra de
VRAM/tempo, ~25% mais lento em teste real). Use `--controlnet-strength` (padrão `0.6`,
de 0 a 1) pra ajustar o quanto o resultado deve seguir a profundidade original:

```bash
python run_vfx.py --mode inpaint \
  --source-image /home/ap/fotos/foto_original.jpg \
  --mask-image /home/ap/fotos/mascara.png \
  --prompt "céu azul com nuvens" \
  --output /home/ap/ai_pipeline/foto_editada.jpg \
  --use-depth-controlnet --controlnet-strength 0.6
```

Também disponível na interface web (checkbox "Avançado" na página "Editar Imagem").

**Qualidade da borda da edição (sempre ativo, sem precisar configurar):** a borda da
máscara é suavizada e o resultado gerado é colado de volta na foto original (em vez de
usar a imagem inteira reprocessada) — a área fora da máscara fica idêntica à original,
sem a leve deriva de cor que existia antes, e a transição fica menos visível. Achado
real de um teste com ControlNet que mostrou uma linha de costura na borda da edição.

### 4.7 Remover o fundo de uma foto/vídeo

```bash
python run_vfx.py --mode removebg \
  --target /home/ap/fotos/foto_com_fundo.jpg \
  --output /home/ap/ai_pipeline/foto_sem_fundo.png
```

Não precisa do ComfyUI ligado — usa o FaceFusion.

### 4.8 Clonar uma voz / gerar fala (texto → voz)

Duas formas de usar:

**(a) Vozes prontas embutidas** (sem clonar ninguém, só escolher um timbre padrão):

```bash
python run_vfx.py --mode tts \
  --text "Olá, esse é um teste de voz gerada por inteligência artificial." \
  --speaker "Ana Florence" \
  --language pt \
  --output /home/ap/ai_pipeline/fala_gerada.wav
```

**(b) Clonar uma voz específica**, a partir de uma amostra de áudio curta (ex.: um áudio
de alguém da família falando alguns segundos):

```bash
python run_vfx.py --mode tts \
  --text "Texto que a voz clonada vai falar." \
  --speaker-wav /home/ap/audios/amostra_da_voz.wav \
  --language pt \
  --output /home/ap/ai_pipeline/fala_clonada.wav
```

Use **ou** `--speaker` **ou** `--speaker-wav` (um dos dois é obrigatório, não os dois).
`--language` aceita códigos como `pt`, `en`, `es` etc.; o padrão já é `pt`.

> Não tenho neste momento a lista exata dos nomes de vozes embutidas disponíveis (não
> verifiquei isso ao vivo) — se `--speaker "Nome"` der erro de nome inválido, rode com
> qualquer amostra em `--speaker-wav` como alternativa garantida, ou me peça pra levantar
> a lista real de vozes do XTTS-v2 antes de tentar de novo.

### 4.9 Dublagem completa (trocar a fala de um vídeo, com boca sincronizada)

**Atenção — limitação real que preciso ser transparente sobre:** diferente dos outros
modos, a dublagem completa **não tem um `--mode` único no `run_vfx.py`** hoje. O que
existe são duas peças que funcionam, mas que você precisa encadear manualmente:

**Passo 1 — gerar o áudio novo** (usando o modo `tts`, item 4.8 acima):

```bash
python run_vfx.py --mode tts \
  --text "Nova fala que vai substituir o áudio original do vídeo." \
  --speaker-wav /home/ap/audios/amostra_da_voz.wav \
  --output /home/ap/ai_pipeline/fala_nova.wav
```

**Passo 2 — sincronizar a boca do vídeo com esse áudio**, chamando o FaceFusion
diretamente (fora do `run_vfx.py`, já que esse modo ainda não foi conectado ao "controle
remoto"):

```bash
conda deactivate  # sai do vfx-pipeline
conda activate facefusion-pipeline
cd /home/ap/ai_pipeline/facefusion
python facefusion.py headless-run \
  --processors lip_syncer \
  -s /home/ap/ai_pipeline/fala_nova.wav \
  -t /home/ap/cenas/video_original.mp4 \
  -o /home/ap/ai_pipeline/video_dublado.mp4 \
  --execution-providers cpu
```

**Por que `--execution-providers cpu` e não `cuda`?** Decisão de arquitetura já validada:
essa etapa específica (sincronia labial) falha na GPU desta máquina por incompatibilidade
de driver com a arquitetura da RTX 5060 Ti (Blackwell) — sem solução limpa disponível
ainda no ecossistema. Rodar em CPU funciona de ponta a ponta, só é mais lento (~136
segundos para um clipe de 270 quadros, num teste real).

### 4.10 Isolar voz / remover ruído de fundo de um áudio

Separa a voz do resto (música, ruído, barulho de fundo) usando o Demucs.

```bash
python run_vfx.py --mode denoise \
  --target /home/ap/audios/audio_com_ruido.wav \
  --output /home/ap/ai_pipeline/voz_isolada.wav \
  --output-instrumental /home/ap/ai_pipeline/resto_do_audio.wav
```

`--output-instrumental` é opcional — só use se também quiser guardar o que **não** é voz
(música/ruído de fundo) num arquivo separado.

**Sobre o que isso faz de verdade:** é uma separação de fontes de áudio (voz vs. resto),
não um removedor de tipos específicos de ruído (vento, chiado de gravação etc.). Para
gravações com voz misturada a música/barulho de fundo, funciona bem. Para ruído técnico
puro (chiado constante, por exemplo), pode não ser a ferramenta certa.

### 4.11 Gerar uma música

**Pré-requisito:** o ComfyUI precisa já estar rodando (mesma observação do item 4.6).

```bash
python run_vfx.py --mode music \
  --prompt "trilha orquestral épica, tema de aventura, tom heroico" \
  --music-duration 15 \
  --output /home/ap/ai_pipeline/musica_gerada.wav
```

### 4.12 Masterização final (juntar o vídeo processado com o áudio/legendas originais)

Depois de qualquer processamento de vídeo (face-swap, geração Wan2.2), o resultado sai só
com o vídeo — sem o áudio/legendas originais do arquivo de origem. Este modo costura os
dois: pega a **imagem** do vídeo processado e o **áudio/legendas/metadados** do vídeo
original, gerando um arquivo final único, com frame rate constante e cor no padrão de
transmissão (bt709).

```bash
python run_vfx.py --mode master \
  --original /home/ap/cenas/cena_original.mp4 \
  --processed-video /home/ap/ai_pipeline/resultado_faceswap.mp4 \
  --output /home/ap/ai_pipeline/video_final_pronto.mp4 \
  --fps 24
```

- `--original`: o vídeo de origem (com o áudio/legendas que você quer manter).
- `--processed-video`: o vídeo já processado pela IA (sem o áudio certo ainda).
- `--fps`: taxa de quadros final. Padrão `24` (cinema); use `30` se preferir o padrão TV/
  vídeo online, ou combine com a saída do modo `video` (que já sai a 30fps).

### 4.13 Aumentar a resolução de uma foto ou vídeo já pronto (upscale)

Diferente da seção 4.4/4.5, este modo **não gera nada novo** — ele pega uma foto ou vídeo
que já existe (ex.: uma foto antiga de família, de baixa resolução) e amplia 4x, usando o
mesmo modelo Real-ESRGAN que já roda internamente no modo `video`. Serve, por exemplo,
para restaurar fotos antigas sem precisar recriar a cena do zero.

```bash
python run_vfx.py --mode upscale \
  --target /home/ap/fotos/foto_antiga.jpg \
  --output /home/ap/ai_pipeline/foto_antiga_4x.jpg
```

Para vídeo, o comando é o mesmo (o sistema detecta automaticamente pela extensão do
arquivo em `--target`); use `--fps` se quiser fixar a taxa de quadros de saída (o valor
não é detectado automaticamente do vídeo original):

```bash
python run_vfx.py --mode upscale \
  --target /home/ap/videos/cena_curta.mp4 \
  --output /home/ap/ai_pipeline/cena_curta_4x.mp4 \
  --fps 24
```

**Pré-requisito:** o ComfyUI precisa já estar rodando (mesma observação do item 4.6) —
o upscale usa os mesmos nodes do ComfyUI que a geração de vídeo.

---

## 5. Fluxo completo de exemplo (do zero até o vídeo final)

Cenário: você quer colocar seu filho lutando ao lado de um herói numa cena de um filme.

1. **Preparar a foto de referência** do seu filho (nítida, de frente, boa iluminação).
2. **(Opcional) Cortar a cena do filme** no trecho que interessa, usando um editor de
   vídeo comum, ou o próprio `ffmpeg`.
3. **Trocar o rosto** (seção 4.2 ou 4.3, dependendo da duração):
   ```bash
   python run_vfx.py --mode faceswap --source foto_filho.jpg --target cena.mp4 \
     --output resultado_faceswap.mp4 --chunk-seconds 30
   ```
4. **(Opcional) Dublar** se quiser trocar alguma fala (seção 4.9, duas etapas manuais).
5. **Masterizar** para recuperar o áudio original e travar o frame rate (seção 4.12):
   ```bash
   python run_vfx.py --mode master --original cena.mp4 \
     --processed-video resultado_faceswap.mp4 --output video_final.mp4
   ```
6. Assista o `video_final.mp4` — pronto.

Para uma cena inteiramente **gerada** (sem filmagem original, ex.: "meu filho voando num
dragão desenhado do zero"), o fluxo muda: use a seção 4.4 ou 4.5 em vez do face-swap, e
pule direto pra masterização se precisar adicionar áudio/música (seção 4.11) por cima.

---

## 6. Solução de problemas comuns

O `README.md` do projeto já traz um guia de troubleshooting mais técnico (erros de
`systemd-run`, drift de áudio, Wayland). Aqui vai um resumo prático, em ordem de
frequência esperada:

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| Gate 3 aborta sozinho, sem perguntar | Menos de 30GB livres em `/` | `df -h /`, apague renders antigos de `/home/ap/ai_pipeline` que não precisa mais |
| Gate 2 avisa VRAM baixa | O Ollama (Qwen) está com um modelo carregado na GPU | Descarregue o modelo (`ollama stop <modelo>`) antes de renders pesados |
| `EOFError` ao responder um Gate | Você chamou com `conda run -n ...` em vez de `conda activate` | Use `conda activate vfx-pipeline && python run_vfx.py ...` |
| `--mode inpaint`/`music` trava e dá timeout | ComfyUI não está rodando | Ligue manualmente (seção 2.2) antes de rodar |
| Face-swap/removebg muito lento, sem uso visível de GPU | `onnxruntime` caiu silenciosamente pra CPU (bug conhecido, já contornado no código) — se persistir, pode ser outro processo prendendo a GPU | `nvidia-smi` pra ver o que está usando a placa |
| Dublagem (lip sync) lenta | É esperado — essa etapa roda em CPU por decisão de arquitetura (ver seção 4.9) | Nenhuma ação — ~136s por clipe curto é o tempo normal |
| Vídeo final com áudio dessincronizado | Vídeo original tinha frame rate variável (comum em vídeo de celular) | Trave o frame rate antes: `ffmpeg -i original.mp4 -r 24 -c:v libx264 -c:a copy cfr_original.mp4`, e use esse arquivo como `--original` no modo `master` |

---

## 7. Referência rápida (cheat sheet)

```bash
conda activate vfx-pipeline
cd /home/ap/ap-ai-studio
```

| Quero... | Comando base |
|---|---|
| Trocar rosto (foto ou vídeo curto) | `python run_vfx.py --mode faceswap --source F.jpg --target T.mp4 --output O.mp4` |
| Trocar rosto (vídeo longo) | ...acima + `--chunk-seconds 30` |
| Gerar vídeo do zero (texto) | `python run_vfx.py --mode video --prompt "..." --width 480 --height 480 --num-frames 161` |
| Animar uma foto | ...acima + `--source-image F.jpg` |
| Editar/apagar algo de uma foto | `python run_vfx.py --mode inpaint --source-image F.jpg --mask-image M.png --prompt "..." --output O.jpg` (ComfyUI precisa estar ligado) |
| Remover fundo | `python run_vfx.py --mode removebg --target F.jpg --output O.png` |
| Gerar fala / clonar voz | `python run_vfx.py --mode tts --text "..." --speaker-wav V.wav --output O.wav` |
| Dublar vídeo (2 passos) | TTS (acima) + FaceFusion `headless-run --processors lip_syncer` manual (seção 4.9) |
| Isolar voz / remover ruído | `python run_vfx.py --mode denoise --target A.wav --output O.wav` |
| Gerar música | `python run_vfx.py --mode music --prompt "..." --music-duration 15 --output O.wav` (ComfyUI precisa estar ligado) |
| Juntar áudio original + vídeo processado | `python run_vfx.py --mode master --original ORIG.mp4 --processed-video PROC.mp4 --output FINAL.mp4` |
| Aumentar resolução de foto/vídeo pronto (4x) | `python run_vfx.py --mode upscale --target F.jpg --output O.jpg` (ComfyUI precisa estar ligado) |
| Testar sem executar nada de verdade | adicione `--dry-run` em qualquer comando acima |
| Pular confirmações repetidas (exceto disco) | adicione `--auto-approve` |

---

## 8. Onde tudo fica guardado no servidor

- **Código do pipeline:** `/home/ap/ap-ai-studio/` (este repositório).
- **Modelos de IA baixados, saídas do ComfyUI, logs:** `/home/ap/ai_pipeline/` — inclui
  `ComfyUI/output/` (resultado de vídeo/imagem/música gerados pelo ComfyUI) e `logs/`
  (`run_vfx.log` é o log central de tudo que passa pelo orquestrador).
- **FaceFusion:** `/home/ap/ai_pipeline/facefusion/`.
- **Log de decisões dos Gates e erros:** `/home/ap/ai_pipeline/logs/run_vfx.log` — sempre
  olhe aqui primeiro se algo rodou sem você acompanhar (ex.: um render longo deixado em
  segundo plano) e você quer saber o que aconteceu.

⚠️ **Nota sobre o disco:** hoje tudo isso compartilha o mesmo disco NVMe do sistema
operacional (o SSD SATA dedicado está com problema e será trocado). Por isso a margem de
segurança de 30GB do Gate 3 é levada a sério — evite deixar o disco chegar perto do limite.

---

## 9. O que ainda não existe / limitações conhecidas (transparência total)

- **Dublagem** não tem um `--mode` dedicado ainda — é um processo manual em duas etapas
  (seção 4.9).
- **Sincronia labial (lip sync) roda em CPU**, não GPU — mais lenta que o resto do
  pipeline, por incompatibilidade de driver com esta GPU (decisão de arquitetura aceita,
  não é bug pendente).
- **Vídeos de ~15 segundos** (o teto de `--num-frames 241`) ainda não foram testados de
  ponta a ponta — só validamos até ~10 segundos de verdade. É mais arriscado quanto a
  falta de memória nessa duração maior.
- **Segmentação automática por texto no inpainting** (ex.: "apague a pessoa da esquerda"
  sem precisar desenhar máscara) não existe — a máscara é sempre manual.
- **Nomes exatos das vozes embutidas do TTS** não foram levantados/confirmados neste
  manual — use `--speaker-wav` como alternativa garantida se um nome específico falhar.
- **ComfyUI não tem supervisão automática (`systemd`)** — só a interface web tem essa
  opção (`vfx-web-enable`, seção 11). Decisão deliberada: o modo `video` já mata e
  religa o ComfyUI dentro da própria jaula de memória toda vez que roda, e um serviço
  com reinício automático brigaria com isso. Se o ComfyUI cair, religue com `vfx-ligar`
  ou o botão "Ligar" da interface web.

---

## 10. Atalhos de terminal (recomendado para o dia a dia)

Em vez de digitar `python run_vfx.py --mode faceswap --source ... --target ... --output
...` toda vez, existem comandos curtos definidos em
`/home/ap/ap-ai-studio/vfx_aliases.sh` e carregados automaticamente em todo terminal novo
(via uma linha adicionada ao seu `~/.bashrc`). Eles chamam o Python certo pelo caminho
completo por baixo dos panos — funcionam **em qualquer terminal**, mesmo que você não
tenha ativado nenhum ambiente Conda antes.

**Padrão de uso:** `<atalho> <argumentos obrigatórios> [flags extras]`. Qualquer flag do
`run_vfx.py` que não vira argumento obrigatório do atalho (`--dry-run`,
`--auto-approve`, `--chunk-seconds`, `--width`, `--fps` etc.) pode ser adicionada no
final do comando, exatamente como no comando completo.

| Atalho | Equivale a | Uso |
|---|---|---|
| `vfx-status` | — | Mostra se o ComfyUI está ligado, VRAM/disco livres |
| `vfx-ligar` | ligar o ComfyUI manualmente (seção 2.2) | `vfx-ligar` |
| `vfx-parar` | encerrar o ComfyUI (libera VRAM) | `vfx-parar` |
| `vfx-rosto` | `--mode faceswap` (seções 4.1-4.3) | `vfx-rosto origem.jpg alvo.mp4 saida.mp4 [--chunk-seconds 30]` |
| `vfx-video` | `--mode video`, texto→vídeo (seção 4.4) | `vfx-video "um dragão azul voando"` |
| `vfx-anima` | `--mode video --source-image`, imagem→vídeo (seção 4.5) | `vfx-anima foto.jpg "vira a cabeça e sorri"` |
| `vfx-editar` | `--mode inpaint` (seção 4.6) | `vfx-editar foto.jpg mascara.png saida.jpg --prompt "fundo verde"` |
| `vfx-semfundo` | `--mode removebg` (seção 4.7) | `vfx-semfundo foto.jpg saida.png` |
| `vfx-fala` | `--mode tts --speaker` (seção 4.8a) | `vfx-fala "texto" "Ana Florence" saida.wav` |
| `vfx-clonar` | `--mode tts --speaker-wav` (seção 4.8b) | `vfx-clonar "texto" amostra.wav saida.wav` |
| `vfx-dublar` | FaceFusion `lip_syncer` manual (seção 4.9) | `vfx-dublar fala_nova.wav video.mp4 saida.mp4` |
| `vfx-limpar` | `--mode denoise` (seção 4.10) | `vfx-limpar audio.wav voz.wav [resto.wav]` |
| `vfx-musica` | `--mode music` (seção 4.11) | `vfx-musica "trilha épica" musica.wav` |
| `vfx-juntar` | `--mode master` (seção 4.12) | `vfx-juntar original.mp4 processado.mp4 final.mp4` |
| `vfx-ajuda` | — | Imprime esta lista no terminal, a qualquer momento |

`vfx-editar` e `vfx-musica` checam sozinhos se o ComfyUI está ligado e, se não estiver,
perguntam `[Y/n]` se você quer ligar agora — não precisa lembrar de rodar `vfx-ligar`
antes, só confirmar quando ele perguntar.

**Se os comandos não funcionarem num terminal já aberto** (só passam a valer em terminais
*novos* depois de instalados), rode uma vez: `source ~/.bashrc` — ou simplesmente feche e
abra o terminal de novo.

**Se quiser desfazer:** remova o bloco `# --- AP AI Studio: atalhos de terminal ---` do
final do seu `~/.bashrc` (há um backup do arquivo original salvo como
`~/.bashrc.bak_ap_ai_studio_<data>`).

---

## 11. Interface web (Fases A + B — todas as funções)

Se você não quiser usar terminal no dia a dia, existe uma interface gráfica pelo
navegador, acessível do próprio servidor ou de qualquer outro aparelho na sua rede
Tailscale (celular, notebook). Ela é um "controle remoto" visual do mesmo `run_vfx.py` —
por baixo dos panos, cada clique em "Iniciar" dispara exatamente o mesmo comando que os
atalhos `vfx-*` da seção 10 disparariam (com uma exceção: dublagem, ver abaixo).

**Todas as 11 funções já estão na interface:**
- **Status**: ComfyUI (Ligar/Parar), VRAM livre, espaço em disco — atualiza sozinho.
- **Gerar Vídeo**: texto→vídeo e imagem→vídeo (seções 4.4/4.5) numa página só.
- **Menu "Imagem"**: Trocar Rosto (4.1-4.3), Editar Imagem/inpainting (4.6), Remover
  Fundo (4.7), Aumentar Resolução/upscale (4.13).
- **Menu "Áudio"**: Voz/TTS e clonagem (4.8, com um seletor pra escolher entre voz
  pronta ou amostra), Dublagem (4.9), Limpar Áudio/isolar voz (4.10, com opção de
  também baixar o "resto" separado), Música (4.11).
- **Masterizar**: junta áudio/legendas originais com o vídeo processado (4.12).

**Particularidade da Dublagem:** assim como no terminal (seção 4.9), esse modo não passa
pelo `run_vfx.py` — a interface chama o FaceFusion diretamente. Por isso o "Modo teste"
dessa página não é um `--dry-run` de verdade (o `facefusion.py` não tem essa flag) — ele
só confirma que os arquivos foram enviados, sem processar nada.

**Editar Imagem e Música continuam exigindo o ComfyUI ligado** (mesma regra da seção
2.2) — essas duas páginas checam sozinhas e oferecem um botão "Ligar ComfyUI" se
estiver desligado.

### Como ligar

> ✅ **Já está ligada agora**, na versão supervisionada (ativada em 2026-07-03, ver
> abaixo) — não precisa fazer nada pra usar, só abrir o navegador (próxima seção). O
> texto abaixo serve pra quando você quiser desligar/religar/trocar de modo.

Duas formas, escolha a que preferir:

```bash
vfx-web            # primeiro plano - fica preso ao terminal, Ctrl+C desliga
vfx-web-enable      # supervisionada - roda em segundo plano via systemd --user,
                     # reinicia sozinha se cair ou se o servidor reiniciar
```

Na primeira vez, builda o frontend automaticamente (pode demorar um pouco) — nas
próximas, sobe direto. Depois de qualquer mudança no código da interface, rode
`vfx-web-build` pra gerar uma versão nova antes de ligar de novo (nas duas formas).

Com a versão supervisionada: `vfx-web-status` mostra se está rodando, `vfx-web-disable`
desliga a supervisão. Recomendada se você quer que a interface fique sempre disponível
sem precisar lembrar de religar depois de um reboot ou de uma queda — a versão em
primeiro plano é melhor só quando você quer acompanhar o log do processo em tempo real
enquanto testa alguma coisa.

### Como acessar

Abra no navegador: **`http://100.122.206.41:8299`**

Funciona tanto no navegador do próprio servidor (via VNC/Remmina) quanto de outro
aparelho — celular, notebook — desde que ele também esteja na sua rede Tailscale. Não
existe login: a mesma barreira de rede que já protege o ComfyUI e o FaceFusion Gradio
neste servidor (só quem está na sua tailnet alcança a porta) protege a interface web
também — decisão deliberada, não uma lacuna esquecida.

**Varredura de segurança (2026-07-03):** a interface passou por uma revisão dedicada de
segurança, que encontrou e corrigiu uma falha real de leitura arbitrária de arquivo
(path traversal) e duas falhas menores de validação de entrada — todas confirmadas por
exploração real contra o servidor e reexploradas depois da correção pra confirmar que
fecharam. Detalhes técnicos completos no `PROMPT_MASTER.md`. Nenhuma delas dependia de
autenticação pra ser explorada, então a correção era necessária mesmo com a barreira do
Tailscale — a rede protege contra estranhos, não contra o que um dispositivo já
confiável na tailnet poderia fazer sem querer ou por engano.

### Como os Gates de segurança aparecem aqui

Diferente do terminal (que pergunta `[Y/n]` três vezes), na interface web um único clique
em "Iniciar" já equivale a aprovar tudo — o painel de log que aparece embaixo do
formulário mostra as decisões reais de cada Gate (memória, VRAM, disco) conforme
acontecem, exatamente como ficariam gravadas no log do terminal. O Gate 3 (espaço em
disco) continua bloqueando sozinho e sem exceção se o disco estiver crítico, igual ao
terminal — isso não muda entre as duas formas de usar.

Cada formulário tem uma caixinha **"Modo teste (--dry-run)"** — marque se quiser só
validar que os Gates passariam, sem gastar GPU/tempo de verdade (equivalente à flag
`--dry-run` do terminal).

### Limites de upload e de disco

Antes de aceitar qualquer arquivo enviado pela interface, ela checa duas coisas: se o
arquivo não passa de 4GB, e se o disco não está abaixo da margem de segurança de 30GB
(mesma margem do Gate 3) — as duas checagens acontecem *antes* de gastar tempo
recebendo o arquivo, não depois. Se cair em algum desses casos, aparece uma mensagem de
erro clara no formulário explicando qual dos dois foi (ver também a seção de
Troubleshooting do `README.md`).

### Onde ficam os arquivos

Uploads e resultados da interface web ficam em `/home/ap/ai_pipeline/webui_uploads/` e
`/home/ap/ai_pipeline/webui_jobs/` (uma pasta por job), separados dos arquivos que você
gera direto pelo terminal — não se misturam. Pastas de job com mais de 7 dias são
apagadas automaticamente (junto com o registro do job na memória da interface, que
também não é mantido pra sempre) — se quiser guardar algum resultado por mais tempo,
baixe ou copie pra outro lugar antes disso.
