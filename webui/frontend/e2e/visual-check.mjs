// Verificacao visual manual da webui, com Chrome headless de verdade (nao mockado) -
// achado de auditoria (perspectiva de Codigo/QA): a primeira verificacao visual feita
// nesta sessao foi um script descartavel, criado e apagado na hora. Este arquivo
// formaliza esse script pra nao precisar reescrever do zero da proxima vez.
//
// Deliberadamente FORA do CI/pre-commit - roda manualmente quando alguem quiser
// confirmar visualmente que a interface nao quebrou (ex.: depois de mexer em CSS/
// layout/Bootstrap). Nao substitui os testes automatizados (Vitest), so' complementa
// o unico tipo de bug que eles nao pegam: "o codigo passa no teste mas fica feio/
// errado na tela de verdade".
//
// Uso: cd webui/frontend/e2e && npm install && npm run check
// Variaveis de ambiente opcionais: WEBUI_URL (default abaixo), CHROME_PATH (default
// abaixo), CLEAN_SCREENSHOTS=1 (apaga os PNGs gerados no final - por padrao ficam em
// ./screenshots/ pra serem conferidos).

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import puppeteer from "puppeteer-core";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEBUI_URL = process.env.WEBUI_URL ?? "http://100.122.206.41:8299";
const CHROME_PATH = process.env.CHROME_PATH ?? "/usr/bin/google-chrome";
const SCREENSHOTS_DIR = path.join(__dirname, "screenshots");
const AI_PIPELINE_DIR = "/home/ap/ap-ai-studio/ai_pipeline";

// Rotas que so' precisam renderizar certo no estado inicial (formulario vazio) - pega
// regressao de layout/CSS sem precisar rodar um job de verdade em cada uma.
const STATIC_ROUTES = [
  "/", "/video", "/rosto", "/editar", "/semfundo", "/upscale",
  "/voz", "/dublar", "/limpar", "/musica", "/masterizar",
];

async function checkStaticRoutes(browser) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 900 });
  for (const route of STATIC_ROUTES) {
    await page.goto(`${WEBUI_URL}${route}`, { waitUntil: "networkidle0" });
    const name = route === "/" ? "status" : route.slice(1);
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, `static_${name}.png`) });
  }
  await page.close();
  console.log(`[OK] ${STATIC_ROUTES.length} rotas estaticas capturadas.`);
}

// Cria uma imagem PNG minima real (64x64, cor solida) sem depender do Pillow/Python -
// so' JS puro, pra este script nao ter nenhuma dependencia alem do puppeteer-core.
// Gerada com Pillow uma vez soh (Image.new("RGB", (64, 64), ...).save(..., "PNG")) e
// embutida aqui - o ComfyUI (via Pillow no backend) eh estrito sobre PNG bem formado,
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
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 900 });

  const testImagePath = path.join(SCREENSHOTS_DIR, "_input.png");
  makeTestImage(testImagePath);

  await page.goto(`${WEBUI_URL}/upscale`, { waitUntil: "networkidle0" });

  const [createResponse] = await Promise.all([
    page.waitForResponse((res) => res.url().endsWith("/api/jobs/upscale") && res.request().method() === "POST"),
    (async () => {
      const fileInput = await page.$('input[type="file"]');
      await fileInput.uploadFile(testImagePath);
      await page.click('button[type="submit"]');
    })(),
  ]);
  const { job_id: jobId } = await createResponse.json();

  await page.waitForFunction(() => document.body.innerText.includes("concluido"), { timeout: 60000 });
  await new Promise((r) => setTimeout(r, 500));
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
  const browser = await puppeteer.launch({
    executablePath: CHROME_PATH,
    headless: "new",
    args: ["--no-sandbox", "--disable-gpu"],
  });

  try {
    await checkStaticRoutes(browser);
    await checkUpscaleEndToEnd(browser);
  } finally {
    await browser.close();
  }

  console.log(`\nScreenshots em: ${SCREENSHOTS_DIR}`);
  console.log("Confira visualmente (ex.: pedindo pro Claude ler os PNGs, ou copiando");
  console.log("via Tailscale/scp) - este script nao afirma nada sozinho, so' captura.");
  if (process.env.CLEAN_SCREENSHOTS) {
    fs.rmSync(SCREENSHOTS_DIR, { recursive: true, force: true });
    console.log("(apagados - CLEAN_SCREENSHOTS estava definida)");
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
