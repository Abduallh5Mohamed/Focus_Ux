import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  outputDir: '../../../generated-artifacts/playwright',
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  use: {
    baseURL: 'http://127.0.0.1:5173',
    browserName: 'chromium',
    permissions: ['camera', 'microphone'],
    launchOptions: {
      executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
      args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream',
        '--autoplay-policy=no-user-gesture-required'],
    },
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'VITE_LIVE_ENABLED=1 VITE_API_BASE_URL=/api npm run dev -- --port 5173',
    url: 'http://127.0.0.1:5173',
    reuseExistingServer: false,
  },
});
