// Verificacao visual manual da webui, com Chromium headless de verdade (nao mockado) -
// achado de auditoria (perspectiva de Codigo/QA): a primeira verificacao visual feita
// nesta sessao foi um script descartavel, criado e apagado na hora. Este arquivo
// formaliza esse script pra nao precisar reescrever do zero da proxima vez.
//
// Migrado de puppeteer-core (exigia Chrome nativo em /usr/bin/google-chrome, que nao
// existe no Bazzite - so' Flatpak, inacessivel por caminho) para Playwright, que traz
// o proprio Chromium embutido (baixado via `npx playwright install chromium`).
//
// Deliberadamente FORA do CI/pre-commit - roda manualmente quando alguem (ou o Claude)
// quiser confirmar visualmente que a interface nao quebrou. Nao substitui os testes
// automatizados (Vitest), so' complementa o unico tipo de bug que eles nao pegam: "o
// codigo passa no teste mas fica feio/errado na tela de verdade".
//
// Uso: cd webui/frontend/e2e && npm install && npx playwright install chromium && npm run check
// Variaveis opcionais: WEBUI_URL (default: le de ~/.config/ap-ai-studio/webui.env),
// AP_AI_STUDIO_HOME (default: raiz do repo), CLEAN_SCREENSHOTS=1 (apaga os PNGs no final).

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { chromium } from "playwright";
import { resolveWebuiUrl, resolvePipelineDir } from "./webui-url.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEBUI_URL = resolveWebuiUrl();
const SCREENSHOTS_DIR = path.join(__dirname, "screenshots");
const AI_PIPELINE_DIR = resolvePipelineDir();

// Rotas que so' precisam renderizar certo no estado inicial (formulario vazio) - pega
// regressao de layout/CSS sem precisar rodar um job de verdade em cada uma.
const STATIC_ROUTES = [
  "/", "/video", "/rosto", "/editar", "/semfundo", "/upscale",
  "/voz", "/dublar", "/limpar", "/musica", "/masterizar",
];

async function checkStaticRoutes(browser) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  for (const route of STATIC_ROUTES) {
    await page.goto(`${WEBUI_URL}${route}`, { waitUntil: "networkidle" });
    const name = route === "/" ? "status" : route.slice(1);
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, `static_${name}.png`) });
  }
  await page.close();
  console.log(`[OK] ${STATIC_ROUTES.length} rotas estaticas capturadas.`);
}

// Cria uma imagem PNG minima real (64x64, cor solida) sem depender do Pillow/Python -
// so' JS puro. O ComfyUI (via Pillow no backend) eh estrito sobre PNG bem formado,
// entao precisa ser uma imagem de verdade, nao uma string qualquer com o prefixo certo.
function makeTestImage(destPath) {
  const png64x64 = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAY0lEQVR4nO3PQQ3AIADAQEA1wpCDmIngcVnSU9DOfe74s6UD" +
      "XjWgNaA1oDWgNaA1oDWgNaA1oDWgNaA1oDWgNaA1oDWgNaA1oDWgNaA1oDWgNaA1oDWgNaA1oDWgNaA1oDWgfUQ+AoiyyMOqAAAAAElFTkSuQmCC",
    "base64",
  );
  fs.writeFileSync(destPath, png64x64);
}

async function checkUpscaleEndToEnd(browser) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

  const testImagePath = path.join(SCREENSHOTS_DIR, "_input.png");
  makeTestImage(testImagePath);

  await page.goto(`${WEBUI_URL}/upscale`, { waitUntil: "networkidle" });

  const [createResponse] = await Promise.all([
    page.waitForResponse((res) => res.url().endsWith("/api/jobs/upscale") && res.request().method() === "POST"),
    (async () => {
      await page.locator('input[type="file"]').setInputFiles(testImagePath);
      await page.locator('button[type="submit"]').click();
    })(),
  ]);
  const { job_id: jobId } = await createResponse.json();

  await page.waitForFunction(() => document.body.innerText.includes("concluido"), { timeout: 60000 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(SCREENSHOTS_DIR, "upscale_e2e_result.png"), fullPage: true });

  await page.close();
  fs.unlinkSync(testImagePath);

  // Limpeza: apaga o job/upload de teste do servidor (mesma maquina onde o script
  // roda - nao precisa de API de delete, so' os caminhos conhecidos de jobs.py).
  for (const dir of ["webui_jobs", "webui_uploads"]) {
    const jobDir = path.join(AI_PIPELINE_DIR, dir, jobId);
    fs.rmSync(jobDir, { recursive: true, force: true });
  }

  console.log(`[OK] Fluxo real de upscale (job ${jobId}) verificado e limpo.`);
}

async function main() {
  fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });
  const browser = await chromium.launch({ headless: true });

  try {
    await checkStaticRoutes(browser);
    await checkUpscaleEndToEnd(browser);
  } finally {
    await browser.close();
  }

  console.log(`\nScreenshots em: ${SCREENSHOTS_DIR}`);
  console.log("Confira visualmente (ex.: pedindo pro Claude ler os PNGs) - este script");
  console.log("nao afirma nada sozinho, so' captura.");
  if (process.env.CLEAN_SCREENSHOTS) {
    fs.rmSync(SCREENSHOTS_DIR, { recursive: true, force: true });
    console.log("(apagados - CLEAN_SCREENSHOTS estava definida)");
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
