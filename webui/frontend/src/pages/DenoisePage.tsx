import { useState } from "react";
import type { FormEvent } from "react";
import { Alert, Button, Card, Col, Form, Row } from "react-bootstrap";
import { createDenoiseJob, jobOutputUrl, jobSecondaryOutputUrl } from "../api";
import type { JobStatusResponse } from "../api";
import JobLogPanel from "../components/JobLogPanel";

export default function DenoisePage() {
  const [target, setTarget] = useState<File | null>(null);
  const [wantInstrumental, setWantInstrumental] = useState(false);
  const [dryRun, setDryRun] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [finishedJob, setFinishedJob] = useState<JobStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!target) {
      setError("Selecione o audio de entrada.");
      return;
    }
    setError(null);
    setSubmitting(true);
    setFinishedJob(null);
    try {
      const resp = await createDenoiseJob({ target, wantInstrumental, dryRun });
      setJobId(resp.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div>
      <h4 className="mb-3">Limpar Áudio / Isolar Voz</h4>
      <p className="text-muted">
        Separa a voz do resto (musica/ruido de fundo) usando Demucs. Nao e' um remove-
        ruido tecnico especifico (chiado, vento) - serve bem pra separar fala de
        musica/fundo.
      </p>

      <Form onSubmit={handleSubmit}>
        <Row className="g-3">
          <Col md={6}>
            <Form.Group controlId="target">
              <Form.Label>Audio de entrada</Form.Label>
              <Form.Control
                type="file"
                accept="audio/*"
                onChange={(e) => setTarget((e.target as HTMLInputElement).files?.[0] ?? null)}
              />
            </Form.Group>
          </Col>
          <Col xs={12}>
            <Form.Check
              type="checkbox"
              id="wantInstrumental"
              label="Tambem guardar o que sobrou (musica/ruido de fundo) num arquivo separado"
              checked={wantInstrumental}
              onChange={(e) => setWantInstrumental(e.target.checked)}
            />
          </Col>
          <Col xs={12}>
            <Form.Check
              type="checkbox"
              id="dryRunDenoise"
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

      {finishedJob?.status === "done" && (finishedJob.output_ready || finishedJob.secondary_output_ready) && (
        <Card className="mt-3">
          <Card.Body>
            <Card.Title>Resultado</Card.Title>
            {finishedJob.output_ready && (
              <div className="mb-3">
                <div className="text-muted small mb-1">Voz isolada</div>
                <audio src={jobOutputUrl(finishedJob.id)} controls />
                <div className="mt-1">
                  <a href={jobOutputUrl(finishedJob.id)} download className="btn btn-outline-secondary btn-sm">
                    Baixar voz
                  </a>
                </div>
              </div>
            )}
            {finishedJob.secondary_output_ready && (
              <div>
                <div className="text-muted small mb-1">Resto (musica/ruido de fundo)</div>
                <audio src={jobSecondaryOutputUrl(finishedJob.id)} controls />
                <div className="mt-1">
                  <a href={jobSecondaryOutputUrl(finishedJob.id)} download className="btn btn-outline-secondary btn-sm">
                    Baixar resto
                  </a>
                </div>
              </div>
            )}
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
