import { useEffect, useRef, useState } from "react";
import { Alert, Badge, Spinner } from "react-bootstrap";
import { getJob } from "../api";
import type { JobStatusResponse } from "../api";

interface Props {
  jobId: string | null;
  onFinished?: (job: JobStatusResponse) => void;
}

const POLL_INTERVAL_MS = 1500;

const STATUS_VARIANT: Record<string, string> = {
  queued: "secondary",
  running: "primary",
  done: "success",
  error: "danger",
};

const STATUS_LABEL: Record<string, string> = {
  queued: "na fila",
  running: "rodando",
  done: "concluido",
  error: "erro",
};

// Painel reutilizavel: recebe um jobId, faz polling de GET /api/jobs/{id} ate o job
// terminar (done/error) e mostra o log ao vivo. Usado por qualquer pagina que dispare
// um job (Trocar Rosto, Gerar Video, e as que vierem na Fase B).
export default function JobLogPanel({ jobId, onFinished }: Props) {
  const [job, setJob] = useState<JobStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const logRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    setJob(null);
    setError(null);
    if (!jobId) return;

    let cancelled = false;
    let finished = false;

    async function poll() {
      try {
        const data = await getJob(jobId as string);
        if (cancelled) return;
        setJob(data);
        if ((data.status === "done" || data.status === "error") && !finished) {
          finished = true;
          onFinished?.(data);
        }
        if (data.status === "queued" || data.status === "running") {
          setTimeout(poll, POLL_INTERVAL_MS);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      }
    }
    poll();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [job?.log_tail.length]);

  if (!jobId) return null;
  if (error) return <Alert variant="danger">Erro ao consultar o job: {error}</Alert>;
  if (!job) {
    return (
      <div className="mt-3">
        <Spinner animation="border" size="sm" /> <span className="ms-2">iniciando...</span>
      </div>
    );
  }

  return (
    <div className="mt-3">
      <div className="d-flex align-items-center gap-2 mb-2">
        <Badge bg={STATUS_VARIANT[job.status] ?? "secondary"}>{STATUS_LABEL[job.status] ?? job.status}</Badge>
        {(job.status === "queued" || job.status === "running") && <Spinner animation="border" size="sm" />}
        {job.returncode !== null && (
          <span className="text-muted small">codigo de saida: {job.returncode}</span>
        )}
      </div>
      <pre
        ref={logRef}
        className="bg-dark text-light p-2 rounded"
        style={{ maxHeight: 260, overflowY: "auto", fontSize: "0.8rem", whiteSpace: "pre-wrap" }}
      >
        {job.log_tail.length > 0 ? job.log_tail.join("\n") : "(sem saida ainda)"}
      </pre>
    </div>
  );
}
