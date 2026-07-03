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
    regex: /ComfyUI reportou erro|execution_error/i,
    message: "O ComfyUI encontrou um problema ao processar o arquivo (pode ser um arquivo corrompido ou não suportado pelo modelo). Veja os detalhes técnicos abaixo.",
  },
];

export function friendlyErrorMessage(logTail: string[]): string | null {
  const text = logTail.join("\n");
  for (const pattern of KNOWN_PATTERNS) {
    if (pattern.regex.test(text)) return pattern.message;
  }
  return null;
}
