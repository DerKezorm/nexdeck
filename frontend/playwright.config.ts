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
const DATA = path.join(here, '.e2e-data')

/** In CI Python is on the path; here it sits in the backend's venv. */
const PYTHON = process.env.NEXDECK_E2E_PYTHON || (process.platform === 'win32' ? path.join(root, 'backend', '.venv', 'Scripts', 'python.exe') : 'python')

// Only the main process clears the data directory; worker processes load this
// file too and must not remove the database under the running server.
if (process.env.TEST_WORKER_INDEX === undefined) {
  rmSync(DATA, { recursive: true, force: true, maxRetries: 3, retryDelay: 200 })
}

export default defineConfig({
  testDir: './e2e',
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
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
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
  ],
})
