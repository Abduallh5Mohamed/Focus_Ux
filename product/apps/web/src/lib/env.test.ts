import { afterEach, expect, it, vi } from 'vitest';

afterEach(() => { vi.unstubAllEnvs(); vi.resetModules(); });

it('uses the Vite API proxy in development without an override', async () => {
  vi.stubEnv('DEV', true);
  vi.stubEnv('VITE_API_BASE_URL', undefined);
  vi.resetModules();
  expect((await import('./env')).API_BASE_URL).toBe('/api');
});

it('preserves an explicit API deployment override in development', async () => {
  vi.stubEnv('DEV', true);
  vi.stubEnv('VITE_API_BASE_URL', '/custom-api');
  vi.resetModules();
  expect((await import('./env')).API_BASE_URL).toBe('/custom-api');
});

it('falls back to same-origin requests in a production build without an override', async () => {
  vi.stubEnv('DEV', false);
  vi.stubEnv('PROD', true);
  vi.stubEnv('VITE_API_BASE_URL', undefined);
  vi.resetModules();
  expect((await import('./env')).API_BASE_URL).toBe('');
});

it('preserves an explicit API deployment override in production', async () => {
  vi.stubEnv('DEV', false);
  vi.stubEnv('PROD', true);
  vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.test');
  vi.resetModules();
  expect((await import('./env')).API_BASE_URL).toBe('https://api.example.test');
});
