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
});
