import { useEffect, useState } from "react";
import { Alert, Button } from "react-bootstrap";
import { getStatus, startComfyUI } from "../api";

// Aviso reutilizavel pras paginas que exigem o ComfyUI ja ligado (Editar Imagem,
// Musica) - o modo video liga sozinho, mas esses dois nao (ver MANUAL_USO.md secao 2.2).
export default function ComfyUINotice() {
  const [up, setUp] = useState<boolean | null>(null);
  const [starting, setStarting] = useState(false);

  async function check() {
    try {
      const status = await getStatus();
      setUp(status.comfyui_up);
    } catch {
      setUp(null);
    }
  }

  useEffect(() => {
    check();
    const interval = setInterval(check, 5000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (up !== false) return null;

  async function handleStart() {
    setStarting(true);
    try {
      await startComfyUI();
      await check();
    } finally {
      setStarting(false);
    }
  }

  return (
    <Alert variant="warning" className="d-flex justify-content-between align-items-center">
      <span>Este modo precisa do ComfyUI ligado.</span>
      <Button size="sm" onClick={handleStart} disabled={starting}>
        {starting ? "Ligando..." : "Ligar ComfyUI"}
      </Button>
    </Alert>
  );
}
