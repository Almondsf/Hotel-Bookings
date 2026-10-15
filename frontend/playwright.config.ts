/**
 * Browser (end-to-end) tests: `npm run e2e`.
 *
 * Starts its own Django and Vite servers on separate ports with a throwaway
 * SQLite database (../e2e.sqlite3) seeded by `seed_demo`, so it never touches
 * the development database or servers. Tests share that one hotel and run one
 * at a time; the night audit runs last because it moves the business date.
 *
 * Environment:
 *   PYTHON      Python with the backend installed (default: python)
 *   PW_CHANNEL  use an installed browser instead of Playwright's Chromium,
 *               e.g. PW_CHANNEL=msedge on Windows
 */
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { defineConfig, devices } from '@playwright/test';

import type { Options } from './e2e/fixtures';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const API_PORT = 8100;
const WEB_PORT = 3100;
const python = process.env.PYTHON ?? 'python';

const backendEnv = {
  ...process.env,
  DATABASE_URL: `sqlite:///${path.join(ROOT, 'e2e.sqlite3').replace(/\\/g, '/')}`,
  DJANGO_DEBUG: 'True', // seed_demo only runs in development mode
  DJANGO_ALLOWED_HOSTS: 'localhost,127.0.0.1',
  EMAIL_BACKEND: 'django.core.mail.backends.dummy.EmailBackend',
  // Every test signs in from the same address
  THROTTLE_LOGIN_IP: '1000/min',
  THROTTLE_LOGIN_EMAIL: '1000/hour',
} as Record<string, string>;

export default defineConfig<Options>({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  timeout: 120_000, // long flows on a busy machine; CI is faster
  expect: { timeout: 10_000 },
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    channel: process.env.PW_CHANNEL || undefined,
    viewport: { width: 1400, height: 1000 },
  },
  projects: [
    {
      name: 'staff',
      testIgnore: [/night-audit\.spec\.ts/, /public-site\.spec\.ts/],
      use: { ...devices['Desktop Chrome'], viewport: { width: 1400, height: 1000 }, signedIn: true },
    },
    {
      name: 'public',
      testMatch: /public-site\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], viewport: { width: 1400, height: 1000 } },
    },
    {
      // Closing the day changes "today" for everything else, so it goes last
      name: 'night-audit',
      dependencies: ['staff', 'public'],
      testMatch: /night-audit\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], viewport: { width: 1400, height: 1000 }, signedIn: true },
    },
  ],
  webServer: [
    {
      command: `${python} manage.py migrate --noinput && ${python} manage.py seed_demo --reset && ${python} manage.py runserver 127.0.0.1:${API_PORT} --noreload`,
      cwd: ROOT,
      env: backendEnv,
      url: `http://127.0.0.1:${API_PORT}/api/health/`,
      timeout: 600_000, // seeding replays two weeks of trading
      reuseExistingServer: false,
      stdout: 'ignore',
    },
    {
      command: `npx vite --port ${WEB_PORT} --strictPort`,
      env: { ...process.env, API_TARGET: `http://127.0.0.1:${API_PORT}` } as Record<string, string>,
      url: `http://localhost:${WEB_PORT}`,
      timeout: 120_000,
      reuseExistingServer: false,
    },
  ],
});
