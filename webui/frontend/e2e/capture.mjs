// Ferramenta generica de uso ad-hoc contra a webui - screenshot, leitura de texto ou
// clique, sem precisar escrever um script novo pra cada verificacao pontual.
//
// Uso:
//   node capture.mjs shot  <rota> [saida.png]              -> screenshot da rota
//   node capture.mjs text  <rota> [seletor]                -> texto visivel (body inteiro se omitido)
//   node capture.mjs click <rota> <seletor> [saida.png]    -> clica e tira screenshot depois
//   node capture.mjs html  <rota>                          -> HTML renderizado (debug)
//
// Variaveis opcionais: WEBUI_URL (default: le de ~/.config/ap-ai-studio/webui.env),
// AP_AI_STUDIO_HOME (default: raiz do repo, calculada a partir deste arquivo).
//
// Screenshots sem caminho de saida vao para ./screenshots/<timestamp>.png.

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { chromium } from "playwright";
import { resolveWebuiUrl } from "./webui-url.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREENSHOTS_DIR = path.join(__dirname, "screenshots");
const WEBUI_URL = resolveWebuiUrl();

const [, , cmd, rota, ...rest] = process.argv;

function usage() {
  console.error("uso: node capture.mjs <shot|text|click|html> <rota> [args...]");
  process.exit(1);
}
if (!cmd || !rota) usage();

fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });

async function run() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const url = `${WEBUI_URL}${rota}`;
  try {
    await page.goto(url, { waitUntil: "networkidle", timeout: 30000 });

    if (cmd === "shot") {
      const out = rest[0] ?? path.join(SCREENSHOTS_DIR, `${Date.now()}.png`);
      await page.screenshot({ path: out, fullPage: true });
      console.log(`OK: ${url} -> ${out}`);
    } else if (cmd === "text") {
      const sel = rest[0];
      const texto = sel ? await page.locator(sel).innerText() : await page.locator("body").innerText();
      console.log(texto);
    } else if (cmd === "click") {
      const [sel, out] = rest;
      if (!sel) usage();
      await page.locator(sel).click();
      await page.waitForTimeout(500);
      const saida = out ?? path.join(SCREENSHOTS_DIR, `${Date.now()}_click.png`);
      await page.screenshot({ path: saida, fullPage: true });
      console.log(`OK: cliquei em "${sel}" -> ${saida}`);
    } else if (cmd === "html") {
      console.log(await page.content());
    } else {
      usage();
    }
  } finally {
    await browser.close();
  }
}

run().catch((err) => {
  console.error(`ERRO em ${url}:`, err.message);
  process.exit(1);
});
