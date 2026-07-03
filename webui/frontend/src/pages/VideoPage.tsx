import { useState } from "react";
import type { FormEvent } from "react";
import { Alert, Button, Card, Col, Form, Row } from "react-bootstrap";
import { createVideoJob, jobOutputUrl } from "../api";
import type { JobStatusResponse } from "../api";
import JobLogPanel from "../components/JobLogPanel";

export default function VideoPage() {
  const [prompt, setPrompt] = useState("");
  const [sourceImage, setSourceImage] = useState<File | null>(null);
  const [width, setWidth] = useState("");
  const [height, setHeight] = useState("");
  const [numFrames, setNumFrames] = useState("");
  const [dryRun, setDryRun] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [finishedJob, setFinishedJob] = useState<JobStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!prompt.trim()) {
      setError("Descreva o que deve acontecer no video (prompt).");
      return;
    }
    setError(null);
    setSubmitting(true);
    setFinishedJob(null);
    try {
      const resp = await createVideoJob({
        prompt,
        width: width ? Number(width) : undefined,
        height: height ? Number(height) : undefined,
        numFrames: numFrames ? Number(numFrames) : undefined,
        sourceImage: sourceImage ?? undefined,
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
      <h4 className="mb-3">Gerar Video</h4>
      <p className="text-muted">
        Sem foto: cria um video do zero a partir de uma descricao (texto → video). Com
        uma foto: anima essa foto seguindo a descricao (imagem → video). O ComfyUI liga
        sozinho se precisar - pode levar alguns minutos.
      </p>

      <Form onSubmit={handleSubmit}>
        <Row className="g-3">
          <Col xs={12}>
            <Form.Group controlId="prompt">
              <Form.Label>Prompt (descricao do que deve acontecer)</Form.Label>
              <Form.Control
                as="textarea"
                rows={3}
                placeholder="ex.: um dragao azul voando sobre um vale verde ao por do sol"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
              />
            </Form.Group>
          </Col>

          <Col md={6}>
            <Form.Group controlId="sourceImage">
              <Form.Label>Foto para animar (opcional - deixe vazio para gerar do zero)</Form.Label>
              <Form.Control
                type="file"
                accept="image/*"
                onChange={(e) => setSourceImage((e.target as HTMLInputElement).files?.[0] ?? null)}
              />
            </Form.Group>
          </Col>

          <Col md={2}>
            <Form.Group controlId="width">
              <Form.Label>Largura</Form.Label>
              <Form.Control type="number" placeholder="320" value={width} onChange={(e) => setWidth(e.target.value)} />
            </Form.Group>
          </Col>
          <Col md={2}>
            <Form.Group controlId="height">
              <Form.Label>Altura</Form.Label>
              <Form.Control type="number" placeholder="320" value={height} onChange={(e) => setHeight(e.target.value)} />
            </Form.Group>
          </Col>
          <Col md={2}>
            <Form.Group controlId="numFrames">
              <Form.Label>Frames</Form.Label>
              <Form.Control
                type="number"
                placeholder="161 (~10s)"
                value={numFrames}
                onChange={(e) => setNumFrames(e.target.value)}
              />
            </Form.Group>
          </Col>

          <Col xs={12}>
            <Form.Check
              type="checkbox"
              id="dryRunVideo"
              label="Modo teste (--dry-run): valida os Gates mas nao renderiza de verdade"
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
