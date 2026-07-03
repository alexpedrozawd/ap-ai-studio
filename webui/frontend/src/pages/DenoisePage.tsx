import { useState } from "react";
import type { FormEvent } from "react";
import { Alert, Button, Card, Col, Form, Row } from "react-bootstrap";
import { createDenoiseJob, jobOutputUrl, jobSecondaryOutputUrl } from "../api";
import type { JobStatusResponse } from "../api";
import BatchJobQueue from "../components/BatchJobQueue";
import JobLogPanel from "../components/JobLogPanel";

export default function DenoisePage() {
  const [target, setTarget] = useState<File | null>(null);
  const [batchFiles, setBatchFiles] = useState<File[]>([]);
  const [wantInstrumental, setWantInstrumental] = useState(false);
  const [dryRun, setDryRun] = useState(false);
  const [batchStarted, setBatchStarted] = useState(false);
  const isBatch = batchFiles.length > 1;
  const [jobId, setJobId] = useState<string | null>(null);
  const [finishedJob, setFinishedJob] = useState<JobStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function handleFilesSelected(files: FileList | null) {
    const list = files ? Array.from(files) : [];
    setTarget(list[0] ?? null);
    setBatchFiles(list);
    setError(null);
    setFinishedJob(null);
    setJobId(null);
    setBatchStarted(false);
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!target) {
      setError("Selecione o audio de entrada.");
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
      const resp = await createDenoiseJob({ target, wantInstrumental, dryRun });
      setJobId(resp.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  function renderAudioResult(job: JobStatusResponse) {
    return (
      <>
        {job.output_ready && (
          <div className="mb-3">
            <div className="text-muted small mb-1">Voz isolada</div>
            <audio src={jobOutputUrl(job.id)} controls />
            <div className="mt-1">
              <a href={jobOutputUrl(job.id)} download className="btn btn-outline-secondary btn-sm">
                Baixar voz
              </a>
            </div>
          </div>
        )}
        {job.secondary_output_ready && (
          <div>
            <div className="text-muted small mb-1">Resto (musica/ruido de fundo)</div>
            <audio src={jobSecondaryOutputUrl(job.id)} controls />
            <div className="mt-1">
              <a href={jobSecondaryOutputUrl(job.id)} download className="btn btn-outline-secondary btn-sm">
                Baixar resto
              </a>
            </div>
          </div>
        )}
      </>
    );
  }

  return (
    <div>
      <h4 className="mb-3">Limpar Áudio / Isolar Voz</h4>
      <p className="text-muted">
        Separa a voz do resto (musica/ruido de fundo) usando Demucs. Nao e' um remove-
        ruido tecnico especifico (chiado, vento) - serve bem pra separar fala de
        musica/fundo. Selecione vários arquivos de uma vez (Ctrl/Shift + clique) para
        processar em lote, um de cada vez.
      </p>

      <Form onSubmit={handleSubmit}>
        <Row className="g-3">
          <Col md={6}>
            <Form.Group controlId="target">
              <Form.Label>Audio de entrada (ou vários, pra lote)</Form.Label>
              <Form.Control
                type="file"
                accept="audio/*"
                multiple
                onChange={(e) => handleFilesSelected((e.target as HTMLInputElement).files)}
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

        <Button type="submit" className="mt-3" disabled={submitting || batchStarted}>
          {submitting ? "Iniciando..." : isBatch ? `Iniciar lote (${batchFiles.length} arquivos)` : "Iniciar"}
        </Button>
      </Form>

      {isBatch && batchStarted ? (
        <BatchJobQueue
          files={batchFiles}
          createJob={(file) => createDenoiseJob({ target: file, wantInstrumental, dryRun })}
          renderResult={(_file, job) =>
            (job.output_ready || job.secondary_output_ready) && (
              <Card className="mt-2">
                <Card.Body>{renderAudioResult(job)}</Card.Body>
              </Card>
            )
          }
        />
      ) : (
        <>
          <JobLogPanel jobId={jobId} onFinished={setFinishedJob} />

          {finishedJob?.status === "done" && (finishedJob.output_ready || finishedJob.secondary_output_ready) && (
            <Card className="mt-3">
              <Card.Body>
                <Card.Title>Resultado</Card.Title>
                {renderAudioResult(finishedJob)}
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
