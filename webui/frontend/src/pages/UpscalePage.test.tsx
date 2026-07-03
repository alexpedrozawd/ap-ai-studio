import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import UpscalePage from "./UpscalePage";
import * as api from "../api";

describe("UpscalePage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("mostra erro e nao chama a API quando nenhum arquivo e' selecionado", async () => {
    const createSpy = vi.spyOn(api, "createUpscaleJob");
    render(<UpscalePage />);

    await userEvent.click(screen.getByRole("button", { name: /iniciar/i }));

    expect(await screen.findByText(/selecione a foto ou video/i)).toBeInTheDocument();
    expect(createSpy).not.toHaveBeenCalled();
  });

  it("mostra o antes/depois (4x) quando o job termina com sucesso", async () => {
    vi.spyOn(api, "createUpscaleJob").mockResolvedValue({ job_id: "job123" });
    vi.spyOn(api, "getJob").mockResolvedValue({
      id: "job123",
      mode: "upscale",
      status: "done",
      returncode: 0,
      log_tail: ["concluido"],
      output_ready: true,
      secondary_output_ready: false,
    });

    render(<UpscalePage />);
    await userEvent.upload(screen.getByLabelText(/foto ou vídeo/i), new File(["a"], "foto.jpg", { type: "image/jpeg" }));
    await userEvent.click(screen.getByRole("button", { name: /iniciar/i }));

    expect(await screen.findByText("Resultado (4x)")).toBeInTheDocument();
    expect(screen.getByText("Antes")).toBeInTheDocument();
    expect(screen.getByText("Depois (4x)")).toBeInTheDocument();
  });

  it("mostra campo de FPS so' quando o arquivo selecionado e' video", async () => {
    render(<UpscalePage />);
    expect(screen.queryByLabelText(/fps de saída/i)).not.toBeInTheDocument();

    await userEvent.upload(screen.getByLabelText(/foto ou vídeo/i), new File(["a"], "cena.mp4", { type: "video/mp4" }));
    expect(await screen.findByLabelText(/fps de saída/i)).toBeInTheDocument();
  });

  it("entra em modo lote quando mais de um arquivo e' selecionado, e processa em fila", async () => {
    vi.spyOn(api, "createUpscaleJob").mockResolvedValue({ job_id: "job1" });
    vi.spyOn(api, "getJob").mockResolvedValue({
      id: "job1",
      mode: "upscale",
      status: "running",
      returncode: null,
      log_tail: [],
      output_ready: false,
      secondary_output_ready: false,
    });

    render(<UpscalePage />);
    await userEvent.upload(screen.getByLabelText(/foto ou vídeo/i), [
      new File(["a"], "foto1.jpg", { type: "image/jpeg" }),
      new File(["b"], "foto2.jpg", { type: "image/jpeg" }),
    ]);

    const startButton = await screen.findByRole("button", { name: /iniciar lote \(2 arquivos\)/i });
    await userEvent.click(startButton);

    expect(await screen.findByText("foto1.jpg")).toBeInTheDocument();
    expect(screen.getByText("foto2.jpg")).toBeInTheDocument();
    expect(screen.getByText("na fila")).toBeInTheDocument();
  });
});
