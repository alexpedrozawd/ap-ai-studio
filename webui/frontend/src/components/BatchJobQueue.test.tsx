import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import BatchJobQueue from "./BatchJobQueue";
import * as api from "../api";

function file(name: string) {
  return new File(["conteudo"], name, { type: "image/jpeg" });
}

describe("BatchJobQueue", () => {
  it("processa os arquivos em fila, um de cada vez (nao dispara o 2o job antes do 1o terminar)", async () => {
    const createJob = vi.fn().mockResolvedValueOnce({ job_id: "job1" }).mockResolvedValueOnce({ job_id: "job2" });
    const getJobSpy = vi.spyOn(api, "getJob");
    getJobSpy.mockResolvedValueOnce({
      id: "job1",
      mode: "upscale",
      status: "done",
      returncode: 0,
      log_tail: ["ok"],
      output_ready: true,
      secondary_output_ready: false,
    });

    render(
      <BatchJobQueue
        files={[file("a.jpg"), file("b.jpg")]}
        createJob={createJob}
        isVideo={() => false}
        jobOutputUrl={(id) => `/api/jobs/${id}/output`}
      />,
    );

    await waitFor(() => expect(createJob).toHaveBeenCalledTimes(1));
    expect(createJob).toHaveBeenCalledWith(expect.objectContaining({ name: "a.jpg" }));

    // So' depois que o job1 termina (getJob retorna "done") e' que o 2o arquivo entra na fila.
    await waitFor(() => expect(createJob).toHaveBeenCalledTimes(2));
    expect(createJob).toHaveBeenLastCalledWith(expect.objectContaining({ name: "b.jpg" }));
  });

  it("mostra 'na fila' pros arquivos que ainda nao comecaram", async () => {
    const createJob = vi.fn().mockResolvedValue({ job_id: "job1" });
    vi.spyOn(api, "getJob").mockResolvedValue({
      id: "job1",
      mode: "upscale",
      status: "running",
      returncode: null,
      log_tail: [],
      output_ready: false,
      secondary_output_ready: false,
    });

    render(
      <BatchJobQueue
        files={[file("a.jpg"), file("b.jpg")]}
        createJob={createJob}
        isVideo={() => false}
        jobOutputUrl={(id) => `/api/jobs/${id}/output`}
      />,
    );

    expect(await screen.findByText("na fila")).toBeInTheDocument();
  });

  it("continua a fila mesmo se um arquivo falhar ao criar o job", async () => {
    const createJob = vi.fn().mockRejectedValueOnce(new Error("400: tipo invalido")).mockResolvedValueOnce({ job_id: "job2" });

    render(
      <BatchJobQueue
        files={[file("ruim.txt"), file("b.jpg")]}
        createJob={createJob}
        isVideo={() => false}
        jobOutputUrl={(id) => `/api/jobs/${id}/output`}
      />,
    );

    expect(await screen.findByText(/tipo invalido/i)).toBeInTheDocument();
    await waitFor(() => expect(createJob).toHaveBeenCalledTimes(2));
  });
});
