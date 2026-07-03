// Achado de auditoria (perfil de uso profissional/iniciante): as mensagens de erro na
// interface repassam o texto tecnico cru do run_vfx.log - um iniciante vendo "Gate 2
// negado" ou "TimeoutError" nao necessariamente entende o que fazer a seguir. Esta
// funcao mapeia os poucos padroes de erro conhecidos (Gates, timeout, OOM, erro do
// ComfyUI) pra uma frase simples em portugues - o log tecnico completo continua
// visivel, isso so' adiciona uma explicacao por cima, nunca esconde nada.
//
// Retorna null quando o erro nao bate com nenhum padrao conhecido - nesse caso a
// interface mostra so' o log tecnico, sem arriscar um palpite errado sobre a causa.

interface ErrorPattern {
  regex: RegExp;
  message: string;
}

const KNOWN_PATTERNS: ErrorPattern[] = [
  {
    regex: /Gate 2 negado|GATE 2-vram.*negad/i,
    message: "Memória de vídeo (VRAM) insuficiente no momento. Feche o Ollama ou outros programas pesados e tente de novo.",
  },
  {
    regex: /Gate 1 negado|GATE 1-memoria.*negad/i,
    message: "Memória RAM insuficiente no momento. Feche outros programas e tente de novo.",
  },
  {
    regex: /Gate 3:?\s*espaco insuficiente|espaco livre.*abaixo da margem/i,
    message: "Espaço em disco insuficiente para processar com segurança. Libere espaço e tente de novo.",
  },
  {
    regex: /Gate 3 negado/i,
    message: "A operação foi cancelada na confirmação de espaço em disco.",
  },
  {
    regex: /falhou \(codigo (137|-9)\)/i,
    message: "O processo foi encerrado por falta de memória (RAM ou VRAM). Feche outros programas pesados (ex.: o Ollama) e tente de novo.",
  },
  {
    regex: /TimeoutError|nao respondeu.*dentro do timeout|nao terminou dentro do timeout/i,
    message: "A operação demorou mais que o esperado e foi cancelada. Tente novamente ou com um arquivo menor.",
  },
  {
    // Acha o achado real primeiro (mais especifico) do que o generico "ComfyUI
    // reportou erro" logo abaixo - a ordem dos padroes importa, o primeiro que bater
    // e' o usado.
    regex: /FileNotFoundError.*\.(safetensors|pth|ckpt|bin)/i,
    message: "Um arquivo de modelo necessário não foi encontrado no servidor - pode ser que um download não tenha terminado. Avise quem administra o servidor.",
  },
  {
    regex: /ComfyUI reportou erro|execution_error/i,
    message: "O ComfyUI encontrou um problema ao processar o arquivo (pode ser um arquivo corrompido ou não suportado pelo modelo). Veja os detalhes técnicos abaixo.",
  },
  {
    regex: /FaceFusion falhou \(codigo/i,
    message: "O FaceFusion não conseguiu processar esse arquivo. Verifique se o rosto está bem visível e iluminado na foto de origem, e se o alvo está num formato comum (mp4/mov para vídeo, jpg/png para foto).",
  },
  {
    regex: /Remocao de fundo falhou \(codigo/i,
    message: "A remoção de fundo não conseguiu processar esse arquivo. Verifique se o formato é comum (jpg/png/mp4) e se o arquivo não está corrompido.",
  },
  {
    regex: /TTS falhou \(codigo/i,
    message: "A síntese/clonagem de voz falhou. Se estiver clonando uma voz, verifique se a amostra de áudio tem alguns segundos de fala clara, sem muito ruído de fundo.",
  },
  {
    regex: /Remocao de ruido falhou \(codigo/i,
    message: "A separação de áudio (Demucs) falhou. Verifique se o arquivo de áudio não está corrompido e se o formato é comum (wav/mp3/flac).",
  },
  {
    regex: /FFmpeg \(masterizacao\) falhou \(codigo/i,
    message: "A masterização final (FFmpeg) falhou. Verifique se o vídeo original e o vídeo processado não estão corrompidos e se ambos têm um formato de vídeo comum.",
  },
];

export function friendlyErrorMessage(logTail: string[]): string | null {
  const text = logTail.join("\n");
  for (const pattern of KNOWN_PATTERNS) {
    if (pattern.regex.test(text)) return pattern.message;
  }
  return null;
}
