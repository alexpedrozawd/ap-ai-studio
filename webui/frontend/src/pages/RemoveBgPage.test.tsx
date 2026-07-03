import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import RemoveBgPage from "./RemoveBgPage";
import * as api from "../api";

describe("RemoveBgPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("mostra erro e nao chama a API quando nenhum arquivo e' selecionado", async () => {
    const createSpy = vi.spyOn(api, "createRemoveBgJob");
    render(<RemoveBgPage />);

    await userEvent.click(screen.getByRole("button", { name: /iniciar/i }));

    expect(await screen.findByText(/selecione a foto ou video/i)).toBeInTheDocument();
    expect(createSpy).not.toHaveBeenCalled();
  });

  it("mostra o antes/depois quando o job termina com sucesso (imagem)", async () => {
    vi.spyOn(api, "createRemoveBgJob").mockResolvedValue({ job_id: "job123" });
    vi.spyOn(api, "getJob").mockResolvedValue({
      id: "job123",
      mode: "removebg",
      status: "done",
      returncode: 0,
      log_tail: ["concluido"],
      output_ready: true,
      secondary_output_ready: false,
    });

    render(<RemoveBgPage />);
    await userEvent.upload(screen.getByLabelText(/foto ou video/i), new File(["a"], "foto.jpg", { type: "image/jpeg" }));
    await userEvent.click(screen.getByRole("button", { name: /iniciar/i }));

    expect(await screen.findByText("Resultado")).toBeInTheDocument();
    expect(screen.getByText("Antes")).toBeInTheDocument();
    expect(screen.getByText("Depois")).toBeInTheDocument();
    expect(screen.queryAllByRole("img")).toHaveLength(2);
  });

  it("mostra <video> nos dois lados quando o alvo enviado e' um video", async () => {
    vi.spyOn(api, "createRemoveBgJob").mockResolvedValue({ job_id: "job123" });
    vi.spyOn(api, "getJob").mockResolvedValue({
      id: "job123",
      mode: "removebg",
      status: "done",
      returncode: 0,
      log_tail: ["concluido"],
      output_ready: true,
      secondary_output_ready: false,
    });

    const { container } = render(<RemoveBgPage />);
    await userEvent.upload(screen.getByLabelText(/foto ou video/i), new File(["a"], "cena.mp4", { type: "video/mp4" }));
    await userEvent.click(screen.getByRole("button", { name: /iniciar/i }));

    await screen.findByText("Resultado");
    expect(container.querySelectorAll("video")).toHaveLength(2);
    expect(container.querySelectorAll("img")).toHaveLength(0);
  });

  it("entra em modo lote quando mais de um arquivo e' selecionado, e processa em fila", async () => {
    vi.spyOn(api, "createRemoveBgJob").mockResolvedValue({ job_id: "job1" });
    vi.spyOn(api, "getJob").mockResolvedValue({
      id: "job1",
      mode: "removebg",
      status: "running",
      returncode: null,
      log_tail: [],
      output_ready: false,
      secondary_output_ready: false,
    });

    render(<RemoveBgPage />);
    await userEvent.upload(screen.getByLabelText(/foto ou video/i), [
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
