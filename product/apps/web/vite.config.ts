import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

const srcDir = fileURLToPath(new URL('./src', import.meta.url));

// Overridable so a second dev server can run beside the trial deployment
// (A:\FocusLocalTrial on :5000) and talk to its own API.
const apiTarget = process.env.FOCUS_API_TARGET ?? 'http://127.0.0.1:8000';
const devPort = Number(process.env.FOCUS_WEB_PORT ?? 5000);

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': srcDir,
    },
  },
  server: {
    host: '0.0.0.0',
    port: devPort,
    strictPort: true,
    allowedHosts: true,
    proxy: {
      '/api': {
        target: apiTarget,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  build: {
    target: 'es2020',
    sourcemap: true,
  },
  test: {
    environment: 'jsdom',
    globals: false,
    include: ['src/**/*.test.{ts,tsx}'],
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    // Serialised: the jsdom environments are heavy and parallel workers were being
    // dropped intermittently on Windows, which silently skipped test files.
    pool: 'forks',
    maxWorkers: 1,
    fileParallelism: false,
  },
});
