import { useEffect, useState } from "react";
import { Alert, Button } from "react-bootstrap";
import { getStatus, startComfyUI } from "../api";

// Aviso reutilizavel pras paginas que usam o ComfyUI (Editar Imagem, Musica, Upscale) -
// achado de auditoria: video/inpaint/music/upscale ja ligam/religam o ComfyUI sozinhos,
// dentro da jaula de memoria (ver MANUAL_USO.md secao 2.2) - este aviso e' so'
// informativo (avisa que vai demorar mais na primeira chamada), nao bloqueia o envio.
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
      <span>ComfyUI está desligado agora - este modo religa ele sozinho ao clicar em
      "Iniciar" (pode levar um minuto a mais), ou você pode ligar antes se preferir:</span>
      <Button size="sm" onClick={handleStart} disabled={starting}>
        {starting ? "Ligando..." : "Ligar ComfyUI"}
      </Button>
    </Alert>
  );
}
