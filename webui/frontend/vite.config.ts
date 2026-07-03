/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
  },
  server: {
    // Dev only (npm run dev): repassa /api pro backend FastAPI rodando em 8299,
    // pra nao precisar de CORS durante o desenvolvimento.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8299',
        changeOrigin: true,
      },
    },
  },
  build: {
    // `npm run build` grava direto na pasta que o FastAPI serve como estatico
    // (webui/backend/static) - um unico processo/porta em uso normal, sem CORS.
    outDir: '../backend/static',
    emptyOutDir: true,
  },
})
