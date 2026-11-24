import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { cpSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const legacy = fileURLToPath(new URL('../frontend/js', import.meta.url));
const assets = fileURLToPath(new URL('../frontend/assets', import.meta.url));

// The graph engine, API client, markdown/mermaid/highlight helpers are reused from frontend/js. Vendored fonts and Mermaid are copied to dist/assets.
const copyAssets = () => ({ name: 'copy-raven-assets', closeBundle() { cpSync(assets, 'dist/assets', { recursive: true }); } });

export default defineConfig({
  plugins: [react(), copyAssets()],
  resolve: { alias: { '@legacy': legacy } },
  build: { outDir: 'dist', assetsDir: 'static', sourcemap: false },
  server: { port: 5173, proxy: { '/api': 'http://localhost:8000', '/assets': 'http://localhost:8000' } },
});
