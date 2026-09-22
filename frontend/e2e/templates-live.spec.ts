/**
 * A board made from a template, in a real browser: the picker offers the
 * installation's own connections for a slot, and the board comes out in the
 * language of whoever made it.
 *
 * ⚠️ Named to sort after `first-start.spec.ts`, which needs the empty
 * installation.
 */
import { expect, test, type Page } from '@playwright/test'

const ACCOUNT = { username: 'e2e-admin', password: 'A-long-enough-password-1' }
const CSRF = { 'X-Nexdeck-Request': '1' }

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

test('a board from a template, with the connections this installation has', async ({ page }) => {
  const trouble: string[] = []
  page.on('pageerror', (error) => trouble.push(String(error)))
  await signIn(page)
  const made = await page.request.post('/api/v1/integrations', { data: { kind: 'portainer', name: 'Portainer here', config: {}, demo: true }, headers: CSRF })
  expect(made.status()).toBe(201)

  // In German, so the words of the template have to arrive translated.
  await page.goto('/settings/boards#templates')
  await page.getByRole('button', { name: 'Deutsch' }).click()
  await expect(page.getByRole('heading', { name: 'Mit einer Vorlage beginnen' })).toBeVisible()
  await page.getByRole('button', { name: /Homelab-Übersicht/ }).click()
  // Other specs may have left connections behind; say what fills which slot.
  const id = String((await made.json()).id)
  await page.getByLabel(/^Container/).selectOption(id)
  for (const slot of [/^Erreichbarkeit/, /^DNS-Filter/, /^Speedtest/]) await page.getByLabel(slot).selectOption('')
  // The clock, the problems, the bookmarks, the notes and both container cards.
  await expect(page.getByText('6 Karten auf 24 Spalten.')).toBeVisible()

  await page.getByLabel('Name des neuen Boards').fill('Mein Lab')
  await page.getByRole('button', { name: 'Board anlegen' }).click()
  await expect(page).toHaveURL(/\/b\/mein-lab/)
  await expect(page.locator('section[aria-label="Laufende Container"]')).toBeVisible()
  await expect(page.locator('section[aria-label="Notizen"]')).toBeVisible()
  await expect(page.locator('section[aria-label="Monitore"]')).toHaveCount(0)

  // Back to English for the specs that come after this one.
  await page.getByRole('button', { name: 'English' }).click()
  expect(trouble, `the browser reported: ${trouble.join(' | ')}`).toEqual([])
})
