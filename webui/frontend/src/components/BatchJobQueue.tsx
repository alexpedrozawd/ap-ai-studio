import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Alert, Badge, ListGroup } from "react-bootstrap";
import type { JobCreateResponse, JobStatusResponse } from "../api";
import JobLogPanel from "./JobLogPanel";

interface BatchItem {
  file: File;
  jobId: string | null;
  finishedJob: JobStatusResponse | null;
  error: string | null;
}

interface BatchJobQueueProps {
  files: File[];
  createJob: (file: File) => Promise<JobCreateResponse>;
  renderResult: (file: File, finishedJob: JobStatusResponse) => ReactNode;
}

// Achado de auditoria (uso profissional): nao havia processamento em lote - cada
// foto/video/audio tinha que ser enviado e acompanhado um de cada vez. Este componente
// processa varios arquivos em fila SEQUENCIAL (nao em paralelo) - decisao deliberada,
// ja que a GPU e' compartilhada com o Ollama e nao ha limite de concorrencia (os
// Gates do run_vfx.py protegem cada job individualmente, mas nao coordenam entre
// jobs simultaneos). Rodar em fila evita que N jobs disputem VRAM ao mesmo tempo.
//
// `renderResult` fica a cargo de cada pagina (antes/depois de imagem, player de audio,
// etc.) - o componente so' cuida da fila/sequenciamento, nao de como cada modo mostra
// o resultado (paginas bem diferentes entre si: Trocar Rosto, Limpar Audio, Upscale).
export default function BatchJobQueue({ files, createJob, renderResult }: BatchJobQueueProps) {
  const [items, setItems] = useState<BatchItem[]>(() =>
    files.map((file) => ({ file, jobId: null, finishedJob: null, error: null })),
  );
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => {
    setItems(files.map((file) => ({ file, jobId: null, finishedJob: null, error: null })));
    setActiveIndex(0);
  }, [files]);

  useEffect(() => {
    if (activeIndex >= items.length) return;
    const active = items[activeIndex];
    if (active.jobId || active.error) return;

    let cancelled = false;
    createJob(active.file)
      .then((resp) => {
        if (cancelled) return;
        setItems((prev) => prev.map((it, i) => (i === activeIndex ? { ...it, jobId: resp.job_id } : it)));
      })
      .catch((err) => {
        if (cancelled) return;
        const message = err instanceof Error ? err.message : String(err);
        setItems((prev) => prev.map((it, i) => (i === activeIndex ? { ...it, error: message } : it)));
        setActiveIndex((i) => i + 1);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeIndex, items.length]);

  function handleItemFinished(index: number, job: JobStatusResponse) {
    setItems((prev) => prev.map((it, i) => (i === index ? { ...it, finishedJob: job } : it)));
    if (index === activeIndex) setActiveIndex((i) => i + 1);
  }

  const doneCount = items.filter((it) => it.finishedJob || it.error).length;

  return (
    <div className="mt-3">
      <div className="mb-2 text-muted small">
        Processando em fila: {doneCount}/{items.length} concluídos
      </div>
      <ListGroup>
        {items.map((item, index) => {
          const isPending = index > activeIndex;
          return (
            <ListGroup.Item key={`${item.file.name}-${index}`}>
              <div className="d-flex align-items-center gap-2">
                <span className="fw-semibold">{item.file.name}</span>
                {isPending && <Badge bg="secondary">na fila</Badge>}
                {item.error && <Badge bg="danger">erro</Badge>}
              </div>
              {item.error && (
                <Alert variant="danger" className="mt-2 mb-0">
                  {item.error}
                </Alert>
              )}
              {item.jobId && (
                <JobLogPanel jobId={item.jobId} onFinished={(job) => handleItemFinished(index, job)} />
              )}
              {item.finishedJob?.status === "done" && renderResult(item.file, item.finishedJob)}
              {item.finishedJob?.status === "error" && (
                <Alert variant="danger" className="mt-2 mb-0">
                  Este arquivo terminou com erro - veja o log acima para o motivo.
                </Alert>
              )}
            </ListGroup.Item>
          );
        })}
      </ListGroup>
    </div>
  );
}
