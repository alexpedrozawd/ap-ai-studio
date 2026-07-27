// Resolve a URL da webui sem hardcode. Repositorio publico - nao pode conter o IP
// Tailscale do servidor (ja vazou uma vez, ver MIGRACAO_BAZZITE.md). Le do mesmo
// arquivo que o systemd usa (~/.config/ap-ai-studio/webui.env), com fallback seguro.
import fs from "fs";
import os from "os";
import path from "path";

export function resolveWebuiUrl() {
  if (process.env.WEBUI_URL) return process.env.WEBUI_URL;

  const envFile = path.join(os.homedir(), ".config", "ap-ai-studio", "webui.env");
  let host = "127.0.0.1";
  let port = "8299";
  try {
    const content = fs.readFileSync(envFile, "utf8");
    for (const line of content.split("\n")) {
      const [key, ...rest] = line.split("=");
      const value = rest.join("=").trim();
      if (!value) continue;
      if (key === "WEBUI_HOST") host = value;
      if (key === "WEBUI_PORT") port = value;
    }
  } catch {
    // arquivo ausente - segue com o default seguro (localhost)
  }
  return `http://${host}:${port}`;
}

export function resolvePipelineDir() {
  if (process.env.AP_AI_STUDIO_HOME) return path.join(process.env.AP_AI_STUDIO_HOME, "ai_pipeline");
  // e2e/ fica em <raiz>/webui/frontend/e2e - tres niveis acima e' a raiz do repo.
  const here = path.dirname(new URL(import.meta.url).pathname);
  return path.join(here, "..", "..", "..", "ai_pipeline");
}
