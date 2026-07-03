import { useState } from "react";
import type { FormEvent } from "react";
import { Alert, Button, Card, Col, Form, Row } from "react-bootstrap";
import { createFaceswapJob, jobOutputUrl } from "../api";
import type { JobStatusResponse } from "../api";
import BatchJobQueue from "../components/BatchJobQueue";
import BeforeAfterCompare from "../components/BeforeAfterCompare";
import JobLogPanel from "../components/JobLogPanel";

const isVideoFile = (file: File) => file.type.startsWith("video/");

export default function FaceSwapPage() {
  const [source, setSource] = useState<File | null>(null);
  const [target, setTarget] = useState<File | null>(null);
  const [batchTargets, setBatchTargets] = useState<File[]>([]);
  const [chunkSeconds, setChunkSeconds] = useState("");
  const [dryRun, setDryRun] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [finishedJob, setFinishedJob] = useState<JobStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [batchStarted, setBatchStarted] = useState(false);

  const targetIsVideo = target ? isVideoFile(target) : false;
  const isBatch = batchTargets.length > 1;

  function handleTargetsSelected(files: FileList | null) {
    const list = files ? Array.from(files) : [];
    setTarget(list[0] ?? null);
    setBatchTargets(list);
    setError(null);
    setFinishedJob(null);
    setJobId(null);
    setBatchStarted(false);
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!source || !target) {
      setError("Selecione a foto de origem e o alvo (foto ou video).");
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
      const resp = await createFaceswapJob({
        source,
        target,
        chunkSeconds: chunkSeconds ? Number(chunkSeconds) : undefined,
        dryRun,
      });
      setJobId(resp.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div>
      <h4 className="mb-3">Trocar Rosto</h4>
      <p className="text-muted">
        Troca o rosto de uma foto ou video de destino pelo rosto de uma foto de origem
        (modo de rosto de referencia do FaceFusion). Selecione vários alvos de uma vez
        (Ctrl/Shift + clique) para trocar o mesmo rosto em vários arquivos, um de cada
        vez.
      </p>

      <Form onSubmit={handleSubmit}>
        <Row className="g-3">
          <Col md={6}>
            <Form.Group controlId="source">
              <Form.Label>Foto de origem (o rosto a inserir)</Form.Label>
              <Form.Control
                type="file"
                accept="image/*"
                onChange={(e) => setSource((e.target as HTMLInputElement).files?.[0] ?? null)}
              />
            </Form.Group>
          </Col>
          <Col md={6}>
            <Form.Group controlId="target">
              <Form.Label>Alvo (foto ou video onde o rosto entra, ou vários pra lote)</Form.Label>
              <Form.Control
                type="file"
                accept="image/*,video/*"
                multiple
                onChange={(e) => handleTargetsSelected((e.target as HTMLInputElement).files)}
              />
            </Form.Group>
          </Col>

          {!isBatch && targetIsVideo && (
            <Col md={6}>
              <Form.Group controlId="chunkSeconds">
                <Form.Label>Dividir em pedacos de quantos segundos? (opcional, video longo)</Form.Label>
                <Form.Control
                  type="number"
                  min={5}
                  placeholder="ex.: 30"
                  value={chunkSeconds}
                  onChange={(e) => setChunkSeconds(e.target.value)}
                />
              </Form.Group>
            </Col>
          )}

          <Col xs={12}>
            <Form.Check
              type="checkbox"
              id="dryRun"
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
          {submitting ? "Iniciando..." : isBatch ? `Iniciar lote (${batchTargets.length} arquivos)` : "Iniciar"}
        </Button>
      </Form>

      {isBatch && batchStarted ? (
        <BatchJobQueue
          files={batchTargets}
          createJob={(file) =>
            createFaceswapJob({
              source: source as File,
              target: file,
              chunkSeconds: chunkSeconds ? Number(chunkSeconds) : undefined,
              dryRun,
            })
          }
          renderResult={(file, job) =>
            job.output_ready && (
              <Card className="mt-2">
                <Card.Body>
                  <BeforeAfterCompare originalFile={file} resultUrl={jobOutputUrl(job.id)} isVideo={isVideoFile(file)} />
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
                <Card.Title>Resultado</Card.Title>
                <BeforeAfterCompare
                  originalFile={target}
                  resultUrl={jobOutputUrl(finishedJob.id)}
                  isVideo={targetIsVideo}
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
