import { useState } from "react";
import type { FormEvent } from "react";
import { Alert, Button, Card, Col, Form, Row } from "react-bootstrap";
import { createUpscaleJob, jobOutputUrl } from "../api";
import type { JobStatusResponse } from "../api";
import BatchJobQueue from "../components/BatchJobQueue";
import BeforeAfterCompare from "../components/BeforeAfterCompare";
import JobLogPanel from "../components/JobLogPanel";

const isVideoFile = (file: File) => file.type.startsWith("video/");

export default function UpscalePage() {
  const [target, setTarget] = useState<File | null>(null);
  const [batchFiles, setBatchFiles] = useState<File[]>([]);
  const [fps, setFps] = useState("");
  const [dryRun, setDryRun] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [finishedJob, setFinishedJob] = useState<JobStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [batchStarted, setBatchStarted] = useState(false);

  const targetIsVideo = target ? isVideoFile(target) : false;
  const isBatch = batchFiles.length > 1;

  function handleFilesSelected(files: FileList | null) {
    const list = files ? Array.from(files) : [];
    setTarget(list[0] ?? null);
    setBatchFiles(list);
    setError(null);
    setFinishedJob(null);
    setJobId(null);
    setBatchStarted(false);
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!target) {
      setError("Selecione a foto ou video a aumentar de resolucao.");
      return;
    }
    if (isBatch) {
      setBatchStarted(true);
      return;
    }
    setError(null);
    setSubmitting(true);
    setFinishedJob(null);
    try {
      const resp = await createUpscaleJob({ target, fps: fps ? Number(fps) : undefined, dryRun });
      setJobId(resp.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div>
      <h4 className="mb-3">Aumentar Resolução (Upscale)</h4>
      <p className="text-muted">
        Aumenta a resolução de uma foto ou vídeo já existente em 4x (ex.: restaurar uma
        foto antiga de família) — não gera nada novo, reaproveita o mesmo modelo
        Real-ESRGAN já usado internamente na geração de vídeo. Selecione vários
        arquivos de uma vez (Ctrl/Shift + clique) para processar em lote, um de cada
        vez.
      </p>

      <Form onSubmit={handleSubmit}>
        <Row className="g-3">
          <Col md={6}>
            <Form.Group controlId="target">
              <Form.Label>Foto ou vídeo (ou vários, pra lote)</Form.Label>
              <Form.Control
                type="file"
                accept="image/*,video/*"
                multiple
                onChange={(e) => handleFilesSelected((e.target as HTMLInputElement).files)}
              />
            </Form.Group>
          </Col>

          {!isBatch && targetIsVideo && (
            <Col md={3}>
              <Form.Group controlId="fps">
                <Form.Label>FPS de saída (opcional)</Form.Label>
                <Form.Control
                  type="number"
                  placeholder="24"
                  value={fps}
                  onChange={(e) => setFps(e.target.value)}
                />
                <Form.Text className="text-muted">
                  Não detectado automaticamente do vídeo original.
                </Form.Text>
              </Form.Group>
            </Col>
          )}

          <Col xs={12}>
            <Form.Check
              type="checkbox"
              id="dryRunUpscale"
              label="Modo teste (--dry-run): valida os Gates mas nao processa de verdade"
              checked={dryRun}
              onChange={(e) => setDryRun(e.target.checked)}
            />
          </Col>
        </Row>

        {error && (
          <Alert variant="danger" className="mt-3">
            {error}
          </Alert>
        )}

        <Button type="submit" className="mt-3" disabled={submitting || batchStarted}>
          {submitting ? "Iniciando..." : isBatch ? `Iniciar lote (${batchFiles.length} arquivos)` : "Iniciar"}
        </Button>
      </Form>

      {isBatch && batchStarted ? (
        <BatchJobQueue
          files={batchFiles}
          createJob={(file) => createUpscaleJob({ target: file, fps: fps ? Number(fps) : undefined, dryRun })}
          renderResult={(file, job) =>
            job.output_ready && (
              <Card className="mt-2">
                <Card.Body>
                  <BeforeAfterCompare
                    originalFile={file}
                    resultUrl={jobOutputUrl(job.id)}
                    isVideo={isVideoFile(file)}
                    afterLabel="Depois (4x)"
                  />
                  <div className="mt-2">
                    <a href={jobOutputUrl(job.id)} download className="btn btn-outline-secondary btn-sm">
                      Baixar
                    </a>
                  </div>
                </Card.Body>
              </Card>
            )
          }
        />
      ) : (
        <>
          <JobLogPanel jobId={jobId} onFinished={setFinishedJob} />

          {finishedJob?.status === "done" && finishedJob.output_ready && (
            <Card className="mt-3">
              <Card.Body>
                <Card.Title>Resultado (4x)</Card.Title>
                <BeforeAfterCompare
                  originalFile={target}
                  resultUrl={jobOutputUrl(finishedJob.id)}
                  isVideo={targetIsVideo}
                  afterLabel="Depois (4x)"
                />
                <div className="mt-2">
                  <a href={jobOutputUrl(finishedJob.id)} download className="btn btn-outline-secondary btn-sm">
                    Baixar
                  </a>
                </div>
              </Card.Body>
            </Card>
          )}

          {finishedJob?.status === "error" && (
            <Alert variant="danger" className="mt-3">
              O job terminou com erro - veja o log acima para o motivo.
            </Alert>
          )}
        </>
      )}
    </div>
  );
}
