import { useEffect, useState } from "react";
import { Alert, Button, Card, Col, ProgressBar, Row, Spinner } from "react-bootstrap";
import { getStatus, startComfyUI, stopComfyUI } from "../api";
import type { StatusResponse } from "../api";

const REFRESH_INTERVAL_MS = 5000;

export default function StatusPage() {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    try {
      const data = await getStatus();
      setStatus(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, REFRESH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, []);

  async function handleStart() {
    setBusy(true);
    try {
      await startComfyUI();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleStop() {
    setBusy(true);
    try {
      await stopComfyUI();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const vramPercent = status?.vram ? Math.round((status.vram.used_mb / status.vram.total_mb) * 100) : 0;
  const diskUsedGb = status ? Math.max(status.disk_total_gb - status.disk_free_gb, 0) : 0;
  const diskPercent = status ? Math.round((diskUsedGb / status.disk_total_gb) * 100) : 0;

  return (
    <div>
      <h4 className="mb-3">Status do servidor</h4>
      {error && <Alert variant="danger">{error}</Alert>}
      {!status && !error && <Spinner animation="border" />}

      {status && (
        <Row className="g-3">
          <Col md={4}>
            <Card>
              <Card.Body>
                <Card.Title>ComfyUI</Card.Title>
                <p className="mb-2">
                  {status.comfyui_up ? (
                    <span className="text-success fw-semibold">no ar</span>
                  ) : (
                    <span className="text-danger fw-semibold">desligado</span>
                  )}
                </p>
                <div className="d-flex gap-2">
                  <Button size="sm" variant="success" disabled={busy || status.comfyui_up} onClick={handleStart}>
                    Ligar
                  </Button>
                  <Button size="sm" variant="outline-danger" disabled={busy || !status.comfyui_up} onClick={handleStop}>
                    Parar
                  </Button>
                </div>
                <p className="text-muted small mt-2 mb-0">
                  Necessario para os modos "Editar Imagem" e "Musica" (Fase B). O modo
                  "Gerar Video" liga sozinho quando precisa.
                </p>
              </Card.Body>
            </Card>
          </Col>

          <Col md={4}>
            <Card>
              <Card.Body>
                <Card.Title>VRAM (GPU)</Card.Title>
                {status.vram ? (
                  <>
                    <ProgressBar now={vramPercent} label={`${vramPercent}%`} className="mb-2" />
                    <p className="text-muted small mb-0">
                      {(status.vram.used_mb / 1024).toFixed(1)}GB usados de{" "}
                      {(status.vram.total_mb / 1024).toFixed(1)}GB (
                      {(status.vram.free_mb / 1024).toFixed(1)}GB livres)
                    </p>
                  </>
                ) : (
                  <p className="text-muted">nvidia-smi indisponivel</p>
                )}
              </Card.Body>
            </Card>
          </Col>

          <Col md={4}>
            <Card>
              <Card.Body>
                <Card.Title>Disco (/)</Card.Title>
                <ProgressBar
                  now={diskPercent}
                  label={`${diskPercent}%`}
                  variant={status.disk_free_gb < 30 ? "danger" : "info"}
                  className="mb-2"
                />
                <p className="text-muted small mb-0">
                  {status.disk_free_gb}GB livres de {status.disk_total_gb}GB
                  {status.disk_free_gb < 30 && (
                    <span className="text-danger"> - abaixo da margem minima (30GB) dos Gates</span>
                  )}
                </p>
              </Card.Body>
            </Card>
          </Col>
        </Row>
      )}
    </div>
  );
}
