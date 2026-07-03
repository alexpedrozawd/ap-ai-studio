import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import FaceSwapPage from "./FaceSwapPage";
import * as api from "../api";

describe("FaceSwapPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("mostra erro e nao chama a API quando nenhum arquivo e' selecionado", async () => {
    const createSpy = vi.spyOn(api, "createFaceswapJob");
    render(<FaceSwapPage />);

    await userEvent.click(screen.getByRole("button", { name: /iniciar/i }));

    expect(await screen.findByText(/selecione a foto de origem/i)).toBeInTheDocument();
    expect(createSpy).not.toHaveBeenCalled();
  });

  it("chama createFaceswapJob com os arquivos selecionados e comeca o polling do job", async () => {
    vi.spyOn(api, "createFaceswapJob").mockResolvedValue({ job_id: "job123" });
    vi.spyOn(api, "getJob").mockResolvedValue({
      id: "job123",
      mode: "faceswap",
      status: "running",
      returncode: null,
      log_tail: ["comecando..."],
      output_ready: false,
      secondary_output_ready: false,
    });

    render(<FaceSwapPage />);

    const sourceInput = screen.getByLabelText(/foto de origem/i);
    const targetInput = screen.getByLabelText(/alvo \(foto ou video/i);
    const sourceFile = new File(["a"], "origem.jpg", { type: "image/jpeg" });
    const targetFile = new File(["b"], "alvo.jpg", { type: "image/jpeg" });

    await userEvent.upload(sourceInput, sourceFile);
    await userEvent.upload(targetInput, targetFile);
    await userEvent.click(screen.getByRole("button", { name: /iniciar/i }));

    await waitFor(() => expect(api.createFaceswapJob).toHaveBeenCalledTimes(1));
    const callArgs = vi.mocked(api.createFaceswapJob).mock.calls[0][0];
    expect(callArgs.source.name).toBe("origem.jpg");
    expect(callArgs.target.name).toBe("alvo.jpg");

    expect(await screen.findByText("rodando")).toBeInTheDocument();
  });

  it("mostra o antes/depois e o botao de baixar quando o job termina com sucesso", async () => {
    vi.spyOn(api, "createFaceswapJob").mockResolvedValue({ job_id: "job123" });
    vi.spyOn(api, "getJob").mockResolvedValue({
      id: "job123",
      mode: "faceswap",
      status: "done",
      returncode: 0,
      log_tail: ["concluido"],
      output_ready: true,
      secondary_output_ready: false,
    });

    render(<FaceSwapPage />);

    const sourceInput = screen.getByLabelText(/foto de origem/i);
    const targetInput = screen.getByLabelText(/alvo \(foto ou video/i);
    await userEvent.upload(sourceInput, new File(["a"], "origem.jpg", { type: "image/jpeg" }));
    await userEvent.upload(targetInput, new File(["b"], "alvo.jpg", { type: "image/jpeg" }));
    await userEvent.click(screen.getByRole("button", { name: /iniciar/i }));

    expect(await screen.findByText("Resultado")).toBeInTheDocument();
    expect(screen.getByText("Antes")).toBeInTheDocument();
    expect(screen.getByText("Depois")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /baixar/i })).toBeInTheDocument();
  });

  it("mostra alerta de erro quando o job termina com falha", async () => {
    vi.spyOn(api, "createFaceswapJob").mockResolvedValue({ job_id: "job123" });
    vi.spyOn(api, "getJob").mockResolvedValue({
      id: "job123",
      mode: "faceswap",
      status: "error",
      returncode: 1,
      log_tail: ["falhou"],
      output_ready: false,
      secondary_output_ready: false,
    });

    render(<FaceSwapPage />);

    await userEvent.upload(screen.getByLabelText(/foto de origem/i), new File(["a"], "origem.jpg", { type: "image/jpeg" }));
    await userEvent.upload(screen.getByLabelText(/alvo \(foto ou video/i), new File(["b"], "alvo.jpg", { type: "image/jpeg" }));
    await userEvent.click(screen.getByRole("button", { name: /iniciar/i }));

    expect(await screen.findByText(/o job terminou com erro/i)).toBeInTheDocument();
  });

  it("entra em modo lote quando varios alvos sao selecionados, mantendo a mesma origem", async () => {
    const createSpy = vi.spyOn(api, "createFaceswapJob").mockResolvedValue({ job_id: "job1" });
    vi.spyOn(api, "getJob").mockResolvedValue({
      id: "job1",
      mode: "faceswap",
      status: "running",
      returncode: null,
      log_tail: [],
      output_ready: false,
      secondary_output_ready: false,
    });

    render(<FaceSwapPage />);
    await userEvent.upload(screen.getByLabelText(/foto de origem/i), new File(["a"], "origem.jpg", { type: "image/jpeg" }));
    await userEvent.upload(screen.getByLabelText(/alvo \(foto ou video/i), [
      new File(["b"], "alvo1.jpg", { type: "image/jpeg" }),
      new File(["c"], "alvo2.jpg", { type: "image/jpeg" }),
    ]);

    const startButton = await screen.findByRole("button", { name: /iniciar lote \(2 arquivos\)/i });
    await userEvent.click(startButton);

    expect(await screen.findByText("alvo1.jpg")).toBeInTheDocument();
    expect(screen.getByText("alvo2.jpg")).toBeInTheDocument();

    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));
    const callArgs = vi.mocked(createSpy).mock.calls[0][0];
    expect(callArgs.source.name).toBe("origem.jpg");
    expect(callArgs.target.name).toBe("alvo1.jpg");
  });
});
