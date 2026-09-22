/**
 * A board from Homepage's files, in a real browser: pasted, looked at, a
 * missing key typed in, and made, with the connections behind it.
 *
 * ⚠️ Named to sort after `first-start.spec.ts`, which needs the empty
 * installation.
 */
import { expect, test, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ACCOUNT = { username: 'e2e-admin', password: 'A-long-enough-password-1' }
const here = path.dirname(fileURLToPath(import.meta.url))
const SERVICES = readFileSync(path.resolve(here, '../../backend/tests/fixtures/imports/homepage-services.yaml'), 'utf8')

async function signIn(page: Page) {
  await page.goto('/')
  await expect(page.getByLabel('User name')).toBeVisible()
  await page.getByLabel('User name').fill(ACCOUNT.username)
  await page.getByLabel('Password', { exact: true }).fill(ACCOUNT.password)
  const confirm = page.getByLabel('Confirm password')
  if (await confirm.isVisible()) {
    await confirm.fill(ACCOUNT.password)
    await page.getByRole('button', { name: 'Next' }).click()
    await page.getByRole('button', { name: 'Next' }).click()
    await page.getByRole('button', { name: 'Finish' }).click()
  } else {
    await page.getByRole('button', { name: 'Sign in' }).click()
  }
  await expect(page).toHaveURL(/\/b\//)
}

test("a board from Homepage's services.yaml", async ({ page }) => {
  const trouble: string[] = []
  page.on('pageerror', (error) => trouble.push(String(error)))
  await signIn(page)
  await page.goto('/settings/boards')
  await page.getByLabel('services.yaml').fill(SERVICES)
  await page.getByRole('button', { name: 'Show what would be made' }).click()

  // Radarr's key was a Homepage placeholder: the plan says so and asks for it.
  await expect(page.getByText(/api_key is a Homepage placeholder/)).toBeVisible()
  const make = page.getByRole('button', { name: 'Make the board' })
  await expect(make).toBeDisabled()
  await page.getByLabel('API key').fill('radarr-key-typed-in')
  await expect(make).toBeEnabled()
  await page.getByLabel('Name of the new board').fill('Imported lab')
  await make.click()

  await expect(page).toHaveURL(/\/b\/imported-lab/)
  await expect(page.getByRole('button', { name: 'Media' })).toBeVisible()
  await expect(page.locator('section[aria-label="Sonarr"]')).toBeVisible()
  const connections = await (await page.request.get('/api/v1/integrations')).json()
  expect(connections.map((c: { name: string }) => c.name)).toEqual(expect.arrayContaining(['Sonarr', 'Radarr', 'Proxmox', 'AdGuard']))
  expect(trouble, `the browser reported: ${trouble.join(' | ')}`).toEqual([])
})
