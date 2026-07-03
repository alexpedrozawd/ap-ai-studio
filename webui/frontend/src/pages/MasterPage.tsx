import { useState } from "react";
import type { FormEvent } from "react";
import { Alert, Button, Card, Col, Form, Row } from "react-bootstrap";
import { createMasterJob, jobOutputUrl } from "../api";
import type { JobStatusResponse } from "../api";
import JobLogPanel from "../components/JobLogPanel";

export default function MasterPage() {
  const [original, setOriginal] = useState<File | null>(null);
  const [processedVideo, setProcessedVideo] = useState<File | null>(null);
  const [fps, setFps] = useState("");
  const [dryRun, setDryRun] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [finishedJob, setFinishedJob] = useState<JobStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!original || !processedVideo) {
      setError("Selecione o video original e o video processado.");
      return;
    }
    setError(null);
    setSubmitting(true);
    setFinishedJob(null);
    try {
      const resp = await createMasterJob({
        original,
        processedVideo,
        fps: fps ? Number(fps) : undefined,
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
      <h4 className="mb-3">Masterização Final</h4>
      <p className="text-muted">
        Junta a imagem do video processado (troca de rosto/geracao) com o audio,
        legendas e metadados do video original, com frame rate constante e cor no
        padrao bt709.
      </p>

      <Form onSubmit={handleSubmit}>
        <Row className="g-3">
          <Col md={6}>
            <Form.Group controlId="original">
              <Form.Label>Video original (audio/legendas a preservar)</Form.Label>
              <Form.Control
                type="file"
                accept="video/*"
                onChange={(e) => setOriginal((e.target as HTMLInputElement).files?.[0] ?? null)}
              />
            </Form.Group>
          </Col>
          <Col md={6}>
            <Form.Group controlId="processedVideo">
              <Form.Label>Video processado (sem o audio certo ainda)</Form.Label>
              <Form.Control
                type="file"
                accept="video/*"
                onChange={(e) => setProcessedVideo((e.target as HTMLInputElement).files?.[0] ?? null)}
              />
            </Form.Group>
          </Col>
          <Col md={3}>
            <Form.Group controlId="fps">
              <Form.Label>FPS de saida</Form.Label>
              <Form.Control type="number" placeholder="24" value={fps} onChange={(e) => setFps(e.target.value)} />
            </Form.Group>
          </Col>
          <Col xs={12}>
            <Form.Check
              type="checkbox"
              id="dryRunMaster"
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
            <video src={jobOutputUrl(finishedJob.id)} controls style={{ maxWidth: "100%", maxHeight: 400 }} />
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
