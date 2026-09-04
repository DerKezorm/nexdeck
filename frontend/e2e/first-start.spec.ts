/**
 * The one journey jsdom cannot prove: first start in a real browser.
 *
 * Setup wizard with the demo, the board with live data over the cookie
 * session, edit mode, a kiosk link that opens the board without a session,
 * and sign-out that really removes access.
 */
import { expect, test } from '@playwright/test'

const ACCOUNT = { username: 'e2e-admin', password: 'A-long-enough-password-1' }

test.describe.configure({ mode: 'serial' })

test('setup wizard, demo board, edit mode, kiosk link, sign-out', async ({ page, browser }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/setup$/)

  // Step 1: account.
  await page.getByLabel('User name').fill(ACCOUNT.username)
  await page.getByLabel('Password').fill(ACCOUNT.password)
  await page.getByRole('button', { name: 'Next' }).click()
  // Step 2: language and look stay as they are.
  await page.getByRole('button', { name: 'Next' }).click()
  // Step 3: the demo is on by default.
  await expect(page.getByRole('switch', { name: 'Start with a demo board' })).toHaveAttribute('aria-checked', 'true')
  await page.getByRole('button', { name: 'Finish' }).click()

  // The demo board opens with its pages and live cards.
  await expect(page).toHaveURL(/\/b\/home/)
  await expect(page.getByRole('button', { name: 'Overview' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Media' })).toBeVisible()
  const containers = page.locator('section[aria-label="Containers"]')
  await expect(containers).toBeVisible()
  await expect(containers.getByText('jellyfin')).toBeVisible({ timeout: 15_000 })

  // Live data arrives through the stream: a value card shows a number soon.
  const requests = page.locator('section[aria-label="Nexview requests"]')
  await expect(requests.locator('.num').first()).not.toHaveText('—', { timeout: 15_000 })

  // Edit mode: the toolbar appears, the library opens and lists adapters.
  await page.getByRole('button', { name: 'Edit board' }).click()
  await page.getByRole('button', { name: 'Add widget' }).first().click()
  await expect(page.getByRole('dialog').getByText('Basics')).toBeVisible()
  await expect(page.getByRole('dialog').getByText('Hosts and containers')).toBeVisible()
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Done' }).click()

  // Reload keeps the session: the cookie survives a navigation.
  await page.reload()
  await expect(page.locator('section[aria-label="Containers"]')).toBeVisible()

  // A kiosk link opens the board in a browser without any session.
  const created = await page.request.post('/api/v1/boards/home/kiosk-tokens', { data: { name: 'e2e wall' }, headers: { 'X-Nexdeck-Request': '1' } })
  expect(created.ok()).toBeTruthy()
  const { url } = (await created.json()) as { url: string }
  const display = await browser.newContext()
  const wall = await display.newPage()
  await wall.goto(url)
  await expect(wall.locator('section[aria-label="Containers"]')).toBeVisible({ timeout: 15_000 })
  await expect(wall.getByRole('button', { name: 'Edit board' })).toHaveCount(0)
  await display.close()

  // Sign-out removes access; the API answers 401 afterwards.
  await page.goto('/settings')
  await page.getByRole('button', { name: 'Sign out here' }).click()
  await expect(page).toHaveURL(/\/login/)
  const me = await page.request.get('/api/v1/auth/me')
  expect(me.status()).toBe(401)
})

test('wrong password is refused with a readable message', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('User name').fill(ACCOUNT.username)
  await page.getByLabel('Password').fill('not-it')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('alert')).toHaveText('User name or password is wrong.')
})
