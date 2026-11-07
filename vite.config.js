import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import {resolve} from 'node:path';

export default defineConfig({
  plugins: [react()],
  base: './',
  build: {rollupOptions: {input: {
    accounting: resolve(process.cwd(), 'accounting.html'),
  }}},
  server: {
    host: '127.0.0.1', port: 5173, strictPort: true,
    // Binary installer outputs are immutable build artifacts, never live UI
    // sources. Watching them can hit Windows EBUSY during Inno compilation.
    watch: {ignored: ['**/release/**', '**/.qa-inno-*/**', '**/.qa-p0-pyinstaller/**']},
  }
});
