# AP AI Studio

Repositório principal da arquitetura do "AP AI Studio". Este repositório contém a fundação (Prompt Architect) e o código fonte (em desenvolvimento) para orquestração assíncrona, segura e de alto desempenho de IA generativa em vídeo (ComfyUI e FaceFusion) num servidor Linux multi-tarefa.

## Estrutura do Repositório
- `PROMPT_MASTER.md`: O "código-fonte" lógico (Prompt Nível 10) que deve ser usado para inicializar a criação ou atualização da infraestrutura do estúdio pela IA.

---

## ⚠️ Troubleshooting (Problemas Possíveis e Soluções)

Durante a execução da arquitetura gerada pelo script, você pode encontrar alguns problemas decorrentes da complexidade de lidar com Hardware, I/O e Kernel simultaneamente no Ubuntu. Aqui está o guia de sobrevivência:

### 1. Erro de Permissão do `systemd-run` via SSH (Gate 1 Falha)
**Problema:** Ao rodar via SSH de outro computador, o Ubuntu pode negar a criação do escopo de memória do `systemd-run` retornando um erro de "Failed to connect to bus".
**Solução:** O script Python do AP AI Studio possui um Fallback automático para usar a biblioteca `resource`. Mas caso queira consertar isso permanentemente no servidor, habilite o "linger" para o seu usuário rodando: `loginctl enable-linger ap`. E certifique-se de que a variável de ambiente do DBus está ativa no terminal remoto executando `export DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus"`.

### 2. FFmpeg Gerando "Audio Drift" (Sincronia labial atrasada)
**Problema:** O vídeo final aparece com o áudio alguns milissegundos ou segundos atrasado em relação à imagem.
**Solução:** Isso ocorre se o vídeo original possui uma Taxa de Quadros Variável (VFR) originada de um celular, e o script de IA tentou processar como se fosse fixo. A automação deve ter um "Passo Zero" forçado. Você também pode rodar o FFmpeg manualmente para travar os quadros antes de jogar na IA:
`ffmpeg -i original.mp4 -r 24 -c:v libx264 -c:a copy cfr_original.mp4`

### 3. VRAM Estourando Repentinamente (Crash no Gate 2)
**Problema:** O script alerta no Gate 2 que a VRAM tem menos de 15.5GB livres. O ComfyUI recusa a renderização.
**Solução:** O seu Qwen 2.5 (Ollama/LM Studio) ou a Steam estão monopolizando a Placa de Vídeo em segundo plano. Rode o comando `nvidia-smi` no terminal para descobrir o PID (ID do Processo) que está usando a VRAM. Encerre o jogo ou descarregue temporariamente o modelo do Qwen da memória até a renderização do vídeo acabar.

### 4. Lentidão Extrema e Placa de Vídeo Ociosa (SATA Bottleneck)
**Problema:** O render do vídeo está sendo executado de forma absurdamente lenta, com processamento na GPU baixo.
**Solução:** O disco SATA não está conseguindo acompanhar o ritmo da gravação dos frames. Verifique se o script Python gerado pela IA realmente incluiu o formato de gravação compactado *lossless* (como `-c:v ffv1` no FFmpeg) ao invés de usar imagens PNG descompactadas pesadas. Se o FFmpeg estiver gerando PNGs crus, ele engasgará a velocidade (banda) do disco SATA.

### 5. Wayland Crash no Ubuntu 24.04 (Falta de Monitor)
**Problema:** O terminal acusa um erro de "Could not load the Qt platform plugin wayland". O script aborta.
**Solução:** Bibliotecas de processamento visual como o OpenCV tentaram invocar um renderizador de janelas e não encontraram uma tela gráfica disponível (comum em sessões remotas/SSH ou scripts sem janela). Confirme se a variável `export QT_QPA_PLATFORM=offscreen` está ativada (ou injetada no script) para forçar as bibliotecas a rodarem de modo "Headless" (Invisível).
