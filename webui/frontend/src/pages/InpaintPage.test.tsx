import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import InpaintPage from "./InpaintPage";
import * as api from "../api";

vi.mock("../components/ComfyUINotice", () => ({ default: () => null }));

describe("InpaintPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("mostra erro e nao chama a API quando faltam os arquivos", async () => {
    const createSpy = vi.spyOn(api, "createInpaintJob");
    render(<InpaintPage />);

    await userEvent.click(screen.getByRole("button", { name: /iniciar/i }));

    expect(await screen.findByText(/selecione a foto original e a mascara/i)).toBeInTheDocument();
    expect(createSpy).not.toHaveBeenCalled();
  });

  it("mostra o antes/depois quando o job termina com sucesso", async () => {
    vi.spyOn(api, "createInpaintJob").mockResolvedValue({ job_id: "job123" });
    vi.spyOn(api, "getJob").mockResolvedValue({
      id: "job123",
      mode: "inpaint",
      status: "done",
      returncode: 0,
      log_tail: ["concluido"],
      output_ready: true,
      secondary_output_ready: false,
    });

    render(<InpaintPage />);
    await userEvent.upload(screen.getByLabelText(/foto original/i), new File(["a"], "original.jpg", { type: "image/jpeg" }));
    await userEvent.upload(screen.getByLabelText(/mascara/i), new File(["b"], "mascara.png", { type: "image/png" }));
    await userEvent.click(screen.getByRole("button", { name: /iniciar/i }));

    expect(await screen.findByText("Resultado")).toBeInTheDocument();
    expect(screen.getByText("Antes")).toBeInTheDocument();
    expect(screen.getByText("Depois")).toBeInTheDocument();
  });

  it("mostra o campo de forca so' quando o ControlNet de profundidade e' ativado, e envia os dois campos", async () => {
    vi.spyOn(api, "createInpaintJob").mockResolvedValue({ job_id: "job123" });
    vi.spyOn(api, "getJob").mockResolvedValue({
      id: "job123",
      mode: "inpaint",
      status: "running",
      returncode: null,
      log_tail: [],
      output_ready: false,
      secondary_output_ready: false,
    });

    render(<InpaintPage />);
    expect(screen.queryByLabelText(/força do controlnet/i)).not.toBeInTheDocument();

    await userEvent.upload(screen.getByLabelText(/foto original/i), new File(["a"], "original.jpg", { type: "image/jpeg" }));
    await userEvent.upload(screen.getByLabelText(/mascara/i), new File(["b"], "mascara.png", { type: "image/png" }));
    await userEvent.click(screen.getByLabelText(/guiar pela profundidade/i));
    expect(await screen.findByLabelText(/força do controlnet/i)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /iniciar/i }));

    expect(api.createInpaintJob).toHaveBeenCalledWith(
      expect.objectContaining({ useDepthControlnet: true, controlnetStrength: 0.6 }),
    );
  });
});
