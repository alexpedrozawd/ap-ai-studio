import { useState } from "react";
import type { FormEvent } from "react";
import { Alert, Button, Card, Col, Form, Row } from "react-bootstrap";
import { createRemoveBgJob, jobOutputUrl } from "../api";
import type { JobStatusResponse } from "../api";
import JobLogPanel from "../components/JobLogPanel";

export default function RemoveBgPage() {
  const [target, setTarget] = useState<File | null>(null);
  const [dryRun, setDryRun] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [finishedJob, setFinishedJob] = useState<JobStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!target) {
      setError("Selecione a foto ou video.");
      return;
    }
    setError(null);
    setSubmitting(true);
    setFinishedJob(null);
    try {
      const resp = await createRemoveBgJob({ target, dryRun });
      setJobId(resp.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div>
      <h4 className="mb-3">Remover Fundo</h4>
      <p className="text-muted">Remove o fundo de uma foto ou video, deixando so' o primeiro plano (com transparencia).</p>

      <Form onSubmit={handleSubmit}>
        <Row className="g-3">
          <Col md={6}>
            <Form.Group controlId="target">
              <Form.Label>Foto ou video</Form.Label>
              <Form.Control
                type="file"
                accept="image/*,video/*"
                onChange={(e) => setTarget((e.target as HTMLInputElement).files?.[0] ?? null)}
              />
            </Form.Group>
          </Col>
          <Col xs={12}>
            <Form.Check
              type="checkbox"
              id="dryRunRemoveBg"
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
            <img src={jobOutputUrl(finishedJob.id)} alt="resultado" style={{ maxWidth: "100%", maxHeight: 400 }} />
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
