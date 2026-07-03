import { describe, expect, it } from "vitest";
import { friendlyErrorMessage } from "./friendlyErrors";

describe("friendlyErrorMessage", () => {
  it("retorna null quando o log nao bate com nenhum padrao conhecido", () => {
    expect(friendlyErrorMessage(["algo generico deu errado", "sem padrao reconhecido"])).toBeNull();
  });

  it("reconhece Gate 2 (VRAM) negado", () => {
    const msg = friendlyErrorMessage(["Pipeline abortado: Gate 2 negado pelo usuario"]);
    expect(msg).toMatch(/VRAM/i);
  });

  it("reconhece Gate 1 (memoria) negado", () => {
    const msg = friendlyErrorMessage(["Pipeline abortado: Gate 1 negado pelo usuario"]);
    expect(msg).toMatch(/RAM/i);
  });

  it("reconhece Gate 3 (disco) por espaco insuficiente", () => {
    const msg = friendlyErrorMessage(["Pipeline abortado: Gate 3: espaco insuficiente (espaco livre em /=5.0GB)"]);
    expect(msg).toMatch(/disco/i);
  });

  it("reconhece codigo de saida 137 (OOM-kill)", () => {
    const msg = friendlyErrorMessage(["FaceFusion falhou (codigo 137): "]);
    expect(msg).toMatch(/falta de memória/i);
  });

  it("reconhece timeout do ComfyUI", () => {
    const msg = friendlyErrorMessage(["RuntimeError: Prompt abc nao terminou dentro do timeout de 1800.0s"]);
    expect(msg).toMatch(/demorou mais/i);
  });

  it("reconhece erro de execucao reportado pelo ComfyUI", () => {
    const msg = friendlyErrorMessage(["RuntimeError: ComfyUI reportou erro no prompt abc: {...}"]);
    expect(msg).toMatch(/ComfyUI encontrou um problema/i);
  });

  it("reconhece falha do FaceFusion (troca de rosto)", () => {
    const msg = friendlyErrorMessage(["FaceFusion falhou (codigo 1): erro generico"]);
    expect(msg).toMatch(/FaceFusion/i);
  });

  it("reconhece falha da remocao de fundo", () => {
    const msg = friendlyErrorMessage(["Remocao de fundo falhou (codigo 1): erro generico"]);
    expect(msg).toMatch(/remoção de fundo/i);
  });

  it("reconhece falha do TTS", () => {
    const msg = friendlyErrorMessage(["TTS falhou (codigo 1): erro generico"]);
    expect(msg).toMatch(/síntese\/clonagem de voz/i);
  });

  it("reconhece falha do Demucs (limpar audio)", () => {
    const msg = friendlyErrorMessage(["Remocao de ruido falhou (codigo 1): erro generico"]);
    expect(msg).toMatch(/separação de áudio/i);
  });

  it("reconhece falha do FFmpeg na masterizacao", () => {
    const msg = friendlyErrorMessage(["FFmpeg (masterizacao) falhou (codigo 1): erro generico"]);
    expect(msg).toMatch(/masterização final/i);
  });

  it("reconhece modelo/arquivo ausente (FileNotFoundError de um .safetensors)", () => {
    const msg = friendlyErrorMessage([
      "FileNotFoundError: [Errno 2] No such file or directory: 'controlnet-depth-sdxl-1.0.safetensors'",
    ]);
    expect(msg).toMatch(/modelo necessário/i);
  });

  it("prioriza o codigo de saida 137 (OOM) sobre a mensagem generica de FaceFusion", () => {
    const msg = friendlyErrorMessage(["FaceFusion falhou (codigo 137): "]);
    expect(msg).toMatch(/falta de memória/i);
  });
});
