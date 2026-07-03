import { useState } from "react";
import type { FormEvent } from "react";
import { Alert, Button, Card, Col, Form, Row } from "react-bootstrap";
import { createMusicJob, jobOutputUrl } from "../api";
import type { JobStatusResponse } from "../api";
import ComfyUINotice from "../components/ComfyUINotice";
import JobLogPanel from "../components/JobLogPanel";

export default function MusicPage() {
  const [prompt, setPrompt] = useState("");
  const [duration, setDuration] = useState("");
  const [dryRun, setDryRun] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [finishedJob, setFinishedJob] = useState<JobStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!prompt.trim()) {
      setError("Descreva a musica que voce quer gerar.");
      return;
    }
    setError(null);
    setSubmitting(true);
    setFinishedJob(null);
    try {
      const resp = await createMusicJob({ prompt, duration: duration ? Number(duration) : undefined, dryRun });
      setJobId(resp.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div>
      <h4 className="mb-3">Gerar Música</h4>
      <p className="text-muted">Gera uma trilha musical curta a partir de uma descricao (MusicGen).</p>
      <ComfyUINotice />

      <Form onSubmit={handleSubmit}>
        <Row className="g-3">
          <Col xs={12}>
            <Form.Group controlId="prompt">
              <Form.Label>Prompt (descricao da musica)</Form.Label>
              <Form.Control
                as="textarea"
                rows={2}
                placeholder="ex.: trilha orquestral epica, tema de aventura, tom heroico"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
              />
            </Form.Group>
          </Col>
          <Col md={3}>
            <Form.Group controlId="duration">
              <Form.Label>Duracao (segundos)</Form.Label>
              <Form.Control type="number" placeholder="5" value={duration} onChange={(e) => setDuration(e.target.value)} />
            </Form.Group>
          </Col>
          <Col xs={12}>
            <Form.Check
              type="checkbox"
              id="dryRunMusic"
              label="Modo teste (--dry-run): valida os Gates mas nao gera de verdade"
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
            <audio src={jobOutputUrl(finishedJob.id)} controls />
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
