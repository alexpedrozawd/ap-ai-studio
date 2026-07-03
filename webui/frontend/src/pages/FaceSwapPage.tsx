import { useState } from "react";
import type { FormEvent } from "react";
import { Alert, Button, Card, Col, Form, Row } from "react-bootstrap";
import { createFaceswapJob, jobOutputUrl } from "../api";
import type { JobStatusResponse } from "../api";
import BeforeAfterCompare from "../components/BeforeAfterCompare";
import JobLogPanel from "../components/JobLogPanel";

export default function FaceSwapPage() {
  const [source, setSource] = useState<File | null>(null);
  const [target, setTarget] = useState<File | null>(null);
  const [chunkSeconds, setChunkSeconds] = useState("");
  const [dryRun, setDryRun] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [finishedJob, setFinishedJob] = useState<JobStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const targetIsVideo = target?.type.startsWith("video/");

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!source || !target) {
      setError("Selecione a foto de origem e o alvo (foto ou video).");
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
        (modo de rosto de referencia do FaceFusion).
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
              <Form.Label>Alvo (foto ou video onde o rosto entra)</Form.Label>
              <Form.Control
                type="file"
                accept="image/*,video/*"
                onChange={(e) => setTarget((e.target as HTMLInputElement).files?.[0] ?? null)}
              />
            </Form.Group>
          </Col>

          {targetIsVideo && (
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

        <Button type="submit" className="mt-3" disabled={submitting}>
          {submitting ? "Iniciando..." : "Iniciar"}
        </Button>
      </Form>

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
    </div>
  );
}
