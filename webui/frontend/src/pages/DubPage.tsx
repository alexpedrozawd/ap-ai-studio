import { useState } from "react";
import type { FormEvent } from "react";
import { Alert, Button, Card, Col, Form, Row } from "react-bootstrap";
import { createDubJob, jobOutputUrl } from "../api";
import type { JobStatusResponse } from "../api";
import JobLogPanel from "../components/JobLogPanel";

export default function DubPage() {
  const [audio, setAudio] = useState<File | null>(null);
  const [video, setVideo] = useState<File | null>(null);
  const [dryRun, setDryRun] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [finishedJob, setFinishedJob] = useState<JobStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!audio || !video) {
      setError("Selecione o audio novo e o video original.");
      return;
    }
    setError(null);
    setSubmitting(true);
    setFinishedJob(null);
    try {
      const resp = await createDubJob({ audio, video, dryRun });
      setJobId(resp.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div>
      <h4 className="mb-3">Dublagem (sincronia labial)</h4>
      <p className="text-muted">
        Sincroniza a boca do video com um audio novo (gere a fala na pagina "Voz"
        primeiro, se ainda nao tiver o audio). Roda em CPU por decisao de arquitetura ja
        validada nesta GPU - pode demorar mais que as outras funcoes.
      </p>

      <Form onSubmit={handleSubmit}>
        <Row className="g-3">
          <Col md={6}>
            <Form.Group controlId="audio">
              <Form.Label>Audio novo (a fala que vai substituir)</Form.Label>
              <Form.Control
                type="file"
                accept="audio/*"
                onChange={(e) => setAudio((e.target as HTMLInputElement).files?.[0] ?? null)}
              />
            </Form.Group>
          </Col>
          <Col md={6}>
            <Form.Group controlId="video">
              <Form.Label>Video original</Form.Label>
              <Form.Control
                type="file"
                accept="video/*"
                onChange={(e) => setVideo((e.target as HTMLInputElement).files?.[0] ?? null)}
              />
            </Form.Group>
          </Col>
          <Col xs={12}>
            <Form.Check
              type="checkbox"
              id="dryRunDub"
              label="Modo teste: so' valida os arquivos, nao roda a sincronia de verdade (facefusion.py nao tem --dry-run nativo)"
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
