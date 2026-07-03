import { useState } from "react";
import type { FormEvent } from "react";
import { Alert, Button, Card, Col, Form, Row } from "react-bootstrap";
import { createInpaintJob, jobOutputUrl } from "../api";
import type { JobStatusResponse } from "../api";
import ComfyUINotice from "../components/ComfyUINotice";
import JobLogPanel from "../components/JobLogPanel";

export default function InpaintPage() {
  const [sourceImage, setSourceImage] = useState<File | null>(null);
  const [maskImage, setMaskImage] = useState<File | null>(null);
  const [prompt, setPrompt] = useState("");
  const [dryRun, setDryRun] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [finishedJob, setFinishedJob] = useState<JobStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!sourceImage || !maskImage) {
      setError("Selecione a foto original e a mascara.");
      return;
    }
    setError(null);
    setSubmitting(true);
    setFinishedJob(null);
    try {
      const resp = await createInpaintJob({ sourceImage, maskImage, prompt: prompt || undefined, dryRun });
      setJobId(resp.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div>
      <h4 className="mb-3">Editar Imagem (Inpainting)</h4>
      <p className="text-muted">
        Apaga/reescreve uma area da foto marcada numa mascara (branco = apagar, preto =
        manter). Sempre descreva o que deve aparecer no lugar - sem isso o resultado
        tende a sair estranho.
      </p>
      <ComfyUINotice />

      <Form onSubmit={handleSubmit}>
        <Row className="g-3">
          <Col md={6}>
            <Form.Group controlId="sourceImage">
              <Form.Label>Foto original</Form.Label>
              <Form.Control
                type="file"
                accept="image/*"
                onChange={(e) => setSourceImage((e.target as HTMLInputElement).files?.[0] ?? null)}
              />
            </Form.Group>
          </Col>
          <Col md={6}>
            <Form.Group controlId="maskImage">
              <Form.Label>Mascara (branco = apagar, preto = manter)</Form.Label>
              <Form.Control
                type="file"
                accept="image/*"
                onChange={(e) => setMaskImage((e.target as HTMLInputElement).files?.[0] ?? null)}
              />
            </Form.Group>
          </Col>
          <Col xs={12}>
            <Form.Group controlId="prompt">
              <Form.Label>O que deve aparecer no lugar (recomendado)</Form.Label>
              <Form.Control
                type="text"
                placeholder="ex.: fundo gradiente rosa e azul liso"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
              />
            </Form.Group>
          </Col>
          <Col xs={12}>
            <Form.Check
              type="checkbox"
              id="dryRunInpaint"
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
