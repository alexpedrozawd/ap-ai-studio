import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DenoisePage from "./DenoisePage";
import * as api from "../api";

describe("DenoisePage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("mostra erro e nao chama a API quando nenhum arquivo e' selecionado", async () => {
    const createSpy = vi.spyOn(api, "createDenoiseJob");
    render(<DenoisePage />);

    await userEvent.click(screen.getByRole("button", { name: /iniciar/i }));

    expect(await screen.findByText(/selecione o audio de entrada/i)).toBeInTheDocument();
    expect(createSpy).not.toHaveBeenCalled();
  });

  it("mostra a voz isolada quando o job termina com sucesso", async () => {
    vi.spyOn(api, "createDenoiseJob").mockResolvedValue({ job_id: "job123" });
    vi.spyOn(api, "getJob").mockResolvedValue({
      id: "job123",
      mode: "denoise",
      status: "done",
      returncode: 0,
      log_tail: ["concluido"],
      output_ready: true,
      secondary_output_ready: false,
    });

    render(<DenoisePage />);
    await userEvent.upload(screen.getByLabelText(/audio de entrada/i), new File(["a"], "audio.wav", { type: "audio/wav" }));
    await userEvent.click(screen.getByRole("button", { name: /iniciar/i }));

    expect(await screen.findByText("Voz isolada")).toBeInTheDocument();
    expect(screen.queryByText("Resto (musica/ruido de fundo)")).not.toBeInTheDocument();
  });

  it("entra em modo lote quando varios arquivos sao selecionados, e processa em fila", async () => {
    vi.spyOn(api, "createDenoiseJob").mockResolvedValue({ job_id: "job1" });
    vi.spyOn(api, "getJob").mockResolvedValue({
      id: "job1",
      mode: "denoise",
      status: "running",
      returncode: null,
      log_tail: [],
      output_ready: false,
      secondary_output_ready: false,
    });

    render(<DenoisePage />);
    await userEvent.upload(screen.getByLabelText(/audio de entrada/i), [
      new File(["a"], "audio1.wav", { type: "audio/wav" }),
      new File(["b"], "audio2.wav", { type: "audio/wav" }),
    ]);

    const startButton = await screen.findByRole("button", { name: /iniciar lote \(2 arquivos\)/i });
    await userEvent.click(startButton);

    expect(await screen.findByText("audio1.wav")).toBeInTheDocument();
    expect(screen.getByText("audio2.wav")).toBeInTheDocument();
    expect(screen.getByText("na fila")).toBeInTheDocument();
  });
});
