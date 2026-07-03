import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import JobLogPanel from "./JobLogPanel";
import * as api from "../api";

describe("JobLogPanel", () => {
  it("nao renderiza nada quando jobId e' null", () => {
    const { container } = render(<JobLogPanel jobId={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("mostra o badge 'concluido' e o log quando o job termina com sucesso", async () => {
    vi.spyOn(api, "getJob").mockResolvedValue({
      id: "abc",
      mode: "faceswap",
      status: "done",
      returncode: 0,
      log_tail: ["linha 1", "linha 2"],
      output_ready: true,
      secondary_output_ready: false,
    });
    render(<JobLogPanel jobId="abc" />);
    expect(await screen.findByText("concluido")).toBeInTheDocument();
    expect(screen.getByText(/linha 1/)).toBeInTheDocument();
  });

  it("mostra o badge 'erro' e o codigo de saida quando o job falha", async () => {
    vi.spyOn(api, "getJob").mockResolvedValue({
      id: "abc",
      mode: "faceswap",
      status: "error",
      returncode: 1,
      log_tail: ["algo deu errado"],
      output_ready: false,
      secondary_output_ready: false,
    });
    render(<JobLogPanel jobId="abc" />);
    expect(await screen.findByText("erro")).toBeInTheDocument();
    expect(screen.getByText(/codigo de saida: 1/)).toBeInTheDocument();
  });

  it("chama onFinished exatamente uma vez quando o job termina", async () => {
    vi.spyOn(api, "getJob").mockResolvedValue({
      id: "abc",
      mode: "video",
      status: "done",
      returncode: 0,
      log_tail: [],
      output_ready: true,
      secondary_output_ready: false,
    });
    const onFinished = vi.fn();
    render(<JobLogPanel jobId="abc" onFinished={onFinished} />);
    await waitFor(() => expect(onFinished).toHaveBeenCalledTimes(1));
  });

  it("mostra uma mensagem amigavel quando o log bate com um erro conhecido (Gate de VRAM)", async () => {
    vi.spyOn(api, "getJob").mockResolvedValue({
      id: "abc",
      mode: "video",
      status: "error",
      returncode: 1,
      log_tail: ["Pipeline abortado: Gate 2 negado pelo usuario"],
      output_ready: false,
      secondary_output_ready: false,
    });
    render(<JobLogPanel jobId="abc" />);
    expect(await screen.findByText(/VRAM/i)).toBeInTheDocument();
  });

  it("nao mostra mensagem amigavel quando o log nao bate com nenhum padrao conhecido", async () => {
    vi.spyOn(api, "getJob").mockResolvedValue({
      id: "abc",
      mode: "video",
      status: "error",
      returncode: 1,
      log_tail: ["algo deu errado, sem padrao reconhecido"],
      output_ready: false,
      secondary_output_ready: false,
    });
    render(<JobLogPanel jobId="abc" />);
    expect(await screen.findByText("erro")).toBeInTheDocument();
    expect(screen.queryByText(/VRAM|RAM insuficiente|disco insuficiente/i)).not.toBeInTheDocument();
  });

  it("mostra alerta de erro quando a consulta ao job falha", async () => {
    vi.spyOn(api, "getJob").mockRejectedValue(new Error("rede fora do ar"));
    render(<JobLogPanel jobId="abc" />);
    expect(await screen.findByText(/rede fora do ar/)).toBeInTheDocument();
  });
});
