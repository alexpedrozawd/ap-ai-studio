import { useState } from "react";
import type { FormEvent } from "react";
import { Alert, Button, Card, Col, Form, Row } from "react-bootstrap";
import { createTtsJob } from "../api";
import type { JobStatusResponse } from "../api";
import JobLogPanel from "../components/JobLogPanel";
import { jobOutputUrl } from "../api";

type VoiceMode = "pronta" | "clonar";

export default function VoicePage() {
  const [mode, setMode] = useState<VoiceMode>("pronta");
  const [text, setText] = useState("");
  const [language, setLanguage] = useState("pt");
  const [speaker, setSpeaker] = useState("");
  const [speakerWav, setSpeakerWav] = useState<File | null>(null);
  const [dryRun, setDryRun] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [finishedJob, setFinishedJob] = useState<JobStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!text.trim()) {
      setError("Escreva o texto que a voz vai falar.");
      return;
    }
    if (mode === "pronta" && !speaker.trim()) {
      setError("Informe o nome de uma voz pronta do XTTS-v2.");
      return;
    }
    if (mode === "clonar" && !speakerWav) {
      setError("Envie uma amostra de audio (alguns segundos de fala) para clonar a voz.");
      return;
    }
    setError(null);
    setSubmitting(true);
    setFinishedJob(null);
    try {
      const resp = await createTtsJob({
        text,
        language,
        speaker: mode === "pronta" ? speaker : undefined,
        speakerWav: mode === "clonar" ? (speakerWav ?? undefined) : undefined,
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
      <h4 className="mb-3">Voz (TTS / Clonagem)</h4>
      <p className="text-muted">Gera fala a partir de texto, com uma voz pronta do XTTS-v2 ou clonando uma voz de uma amostra de audio.</p>

      <Form onSubmit={handleSubmit}>
        <Row className="g-3">
          <Col xs={12}>
            <Form.Check
              inline
              type="radio"
              name="voiceMode"
              id="modePronta"
              label="Voz pronta"
              checked={mode === "pronta"}
              onChange={() => setMode("pronta")}
            />
            <Form.Check
              inline
              type="radio"
              name="voiceMode"
              id="modeClonar"
              label="Clonar de amostra"
              checked={mode === "clonar"}
              onChange={() => setMode("clonar")}
            />
          </Col>

          <Col xs={12}>
            <Form.Group controlId="text">
              <Form.Label>Texto a falar</Form.Label>
              <Form.Control as="textarea" rows={3} value={text} onChange={(e) => setText(e.target.value)} />
            </Form.Group>
          </Col>

          <Col md={4}>
            <Form.Group controlId="language">
              <Form.Label>Idioma</Form.Label>
              <Form.Control type="text" value={language} onChange={(e) => setLanguage(e.target.value)} />
            </Form.Group>
          </Col>

          {mode === "pronta" ? (
            <Col md={8}>
              <Form.Group controlId="speaker">
                <Form.Label>Nome da voz pronta</Form.Label>
                <Form.Control
                  type="text"
                  placeholder='ex.: "Ana Florence"'
                  value={speaker}
                  onChange={(e) => setSpeaker(e.target.value)}
                />
              </Form.Group>
            </Col>
          ) : (
            <Col md={8}>
              <Form.Group controlId="speakerWav">
                <Form.Label>Amostra de audio (alguns segundos de fala)</Form.Label>
                <Form.Control
                  type="file"
                  accept="audio/*"
                  onChange={(e) => setSpeakerWav((e.target as HTMLInputElement).files?.[0] ?? null)}
                />
              </Form.Group>
            </Col>
          )}

          <Col xs={12}>
            <Form.Check
              type="checkbox"
              id="dryRunVoice"
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
