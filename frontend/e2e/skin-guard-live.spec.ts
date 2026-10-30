/**
 * A skin reaches the boards and nothing that asks for a password or a confirmation.
 *
 * The test skin is hostile on purpose: it paints every button red. On a board
 * it has to, which shows the skin is worn at all; on the profile (a guarded
 * page) and inside a delete confirmation on a page that wears the skin it must
 * not, which is the whole point of the guard (lib/skin/guard.ts).
 */
import { expect, test, type Page } from '@playwright/test'

const ACCOUNT = { username: 'e2e-admin', password: 'A-long-enough-password-1' }
const CSRF = { 'X-Nexdeck-Request': '1' }
const RED = 'rgb(255, 0, 0)'
const LOUD = { nexdeck_skin: 1, key: 'e2e-loud', name: 'Loud', css: '[data-part=button] { color: #ff0000 }' }

async function signIn(page: Page): Promise<void> {
  await page.goto('/')
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

const colour = (page: Page, selector: string) => page.locator(selector).first().evaluate((element) => getComputedStyle(element).color)

test('a skin paints the board and leaves the profile and a confirmation alone', async ({ page }) => {
  await signIn(page)
  await page.request.delete('/api/v1/skins/e2e-loud', { headers: CSRF })
  expect((await page.request.post('/api/v1/skins', { headers: CSRF, data: { text: JSON.stringify(LOUD) } })).status()).toBe(201)
  const look = await (await page.request.get('/api/v1/settings/appearance')).json()
  expect((await page.request.put('/api/v1/settings/appearance', { headers: CSRF, data: { ...look, skin: { key: 'e2e-loud' } } })).ok()).toBeTruthy()
  try {
    await page.goto('/')
    await expect(page.locator('html')).toHaveAttribute('data-skin', 'e2e-loud')
    await expect.poll(() => colour(page, 'header.app-bar .btn')).toBe(RED)

    await page.goto('/settings')
    await expect(page.locator('html')).toHaveAttribute('data-skin-guard', '')
    await expect(page.locator('main[data-shell] .btn').first()).toBeVisible()
    expect(await colour(page, 'main[data-shell] .btn')).not.toBe(RED)

    await page.goto('/settings/boards')
    await expect(page.locator('html')).not.toHaveAttribute('data-skin-guard', '')
    await expect.poll(() => colour(page, 'main[data-shell] .btn')).toBe(RED)
    await page.locator('main[data-shell] .btn-danger').first().click()
    const asked = page.locator('[role=dialog][data-skin-guard]')
    await expect(asked).toBeVisible()
    for (const button of await asked.locator('.btn').all()) expect(await button.evaluate((element) => getComputedStyle(element).color)).not.toBe(RED)
    await page.keyboard.press('Escape')
  } finally {
    await page.request.put('/api/v1/settings/appearance', { headers: CSRF, data: { ...look, skin: {} } })
    await page.request.delete('/api/v1/skins/e2e-loud', { headers: CSRF })
  }
})
