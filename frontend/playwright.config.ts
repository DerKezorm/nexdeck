/**
 * The end-to-end run: a fresh backend on an empty data directory and the
 * Vite server in front of it. Own ports, so a developer's servers on 8000
 * and 5176 are left alone.
 */
import { defineConfig, devices } from '@playwright/test'
import { rmSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(here, '..')

export const BACKEND_PORT = 8799
export const FRONTEND_PORT = 5799
/**
 * ⚠️ The third server: the built frontend served by FastAPI, which is the
 * arrangement the Docker image ships and the only one nobody was testing.
 * The difference is not cosmetic. The Vite server sets no Content-Security-
 * Policy, so anything the real CSP blocks passes here and fails there: 0.31.0
 * went out with Web Push dead for exactly that reason, and every test was
 * green.
 */
export const BUILT_PORT = 8798
const DATA = path.join(here, '.e2e-data')
const BUILT_DATA = path.join(here, '.e2e-built-data')

/** In CI Python is on the path; here it sits in the backend's venv. */
const PYTHON = process.env.NEXDECK_E2E_PYTHON || (process.platform === 'win32' ? path.join(root, 'backend', '.venv', 'Scripts', 'python.exe') : 'python')

// Only the main process clears the data directory; worker processes load this
// file too and must not remove the database under the running server.
if (process.env.TEST_WORKER_INDEX === undefined) {
  rmSync(DATA, { recursive: true, force: true, maxRetries: 3, retryDelay: 200 })
  rmSync(BUILT_DATA, { recursive: true, force: true, maxRetries: 3, retryDelay: 200 })
}

/**
 * ⚠️ One data directory for the whole run, one worker, and Playwright walks
 * the spec files in alphabetical order. So the first file to run is the only
 * one that sees an empty installation, and `first-start.spec.ts` is that file
 * because it tests the setup wizard. A new spec whose name sorts before it
 * takes the wizard away and leaves `first-start` looking at a sign-in page:
 * measured on 08.09.2026 with a spec called `einstellungen.spec.ts`, which is
 * why it is now called `settings-live.spec.ts`. Every other spec signs in
 * instead of assuming which of the two pages it lands on.
 */
export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['list']] : [['list']],
  timeout: 60_000,
  use: {
    baseURL: `http://127.0.0.1:${FRONTEND_PORT}`,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    locale: 'en-US',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] }, testIgnore: /built\./ },
    {
      // The image's own arrangement: one server, real headers, built assets.
      name: 'built',
      use: { ...devices['Desktop Chrome'], baseURL: `http://127.0.0.1:${BUILT_PORT}` },
      testMatch: /built\./,
    },
  ],
  webServer: [
    {
      command: `"${PYTHON}" -m uvicorn app.main:app --host 127.0.0.1 --port ${BACKEND_PORT}`,
      cwd: path.join(root, 'backend'),
      env: { NEXDECK_DATA_DIR: DATA, NEXDECK_SECRET_KEY: 'e2e-only-secret', NEXDECK_LOG_LEVEL: 'WARNING' },
      url: `http://127.0.0.1:${BACKEND_PORT}/api/v1/setup/status`,
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${FRONTEND_PORT} --strictPort`,
      cwd: here,
      env: { NEXDECK_API: `http://127.0.0.1:${BACKEND_PORT}` },
      url: `http://127.0.0.1:${FRONTEND_PORT}`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      // FastAPI serving dist/, the way the container does. Needs a build.
      command: `"${PYTHON}" -m uvicorn app.main:app --host 127.0.0.1 --port ${BUILT_PORT}`,
      cwd: path.join(root, 'backend'),
      env: {
        NEXDECK_DATA_DIR: BUILT_DATA,
        NEXDECK_SECRET_KEY: 'e2e-only-secret',
        NEXDECK_LOG_LEVEL: 'WARNING',
        NEXDECK_STATIC_DIR: path.join(here, 'dist'),
      },
      url: `http://127.0.0.1:${BUILT_PORT}/api/v1/setup/status`,
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
  ],
})
