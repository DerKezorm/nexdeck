/**
 * The AI tab of the skin editor, with the provider played by this test: the
 * request to /api/v1/skins/ai never leaves the browser (page.route), so nothing
 * reaches Anthropic. What is checked is nexdeck's part: what the editor sends
 * (the request, the skin, the locks; on the second round a picture of the
 * stage in dark and in light mode), that the stage wears each answer, and that each answer is one step
 * back with undo.
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect, test, type Page } from '@playwright/test'

const ACCOUNT = { username: 'e2e-admin', password: 'A-long-enough-password-1' }
const CSRF = { 'X-Nexdeck-Request': '1' }
const here = path.dirname(fileURLToPath(import.meta.url))
const CONSOLE = JSON.parse(readFileSync(path.join(here, '..', '..', 'backend', 'app', 'skins', 'examples', 'console.json'), 'utf8'))

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

test('the AI makes a skin, looks at the stage once and improves it, and each answer is a step back', async ({ page }) => {
  await signIn(page)
  // A made-up key: the provider is this test, and the route below answers in its place.
  expect((await page.request.put('/api/v1/settings/assistant', { headers: CSRF, data: { provider: 'anthropic', model: '', key: 'sk-ant-e2e-only' } })).ok()).toBeTruthy()
  const asked: Record<string, unknown>[] = []
  await page.route('**/api/v1/skins/ai', async (route) => {
    const body = route.request().postDataJSON() as Record<string, unknown>
    asked.push(body)
    const skin = { ...CONSOLE, key: (body.skin as { key: string }).key, name: 'From the AI' }
    const answer = body.review ? { ok: true, skin: { ...skin, switches: { corners: 'square' } }, text: 'Squared the corners.', problems: [] } : { ok: true, skin, text: 'Made a console.', problems: [] }
    await route.fulfill({ json: answer })
  })
  try {
    await page.goto('/system/skins/new?from=empty')
    await page.getByRole('tab', { name: 'AI' }).click()
    await page.getByRole('button', { name: 'Colours' }).click()
    await page.getByLabel('What the skin should look like').fill('Like a game console')
    await page.getByRole('button', { name: 'Make it' }).click()

    await expect(page.getByText('Made a console.')).toBeVisible()
    const stage = page.frameLocator('[data-testid=skin-stage]')
    await expect(stage.locator("html[data-skin='my-skin']")).toHaveCount(1)
    await expect.poll(() => stage.locator('[data-desk-tile]').evaluate((element) => getComputedStyle(element).backgroundImage), { timeout: 10_000 }).toContain('data:image/svg+xml')
    await expect(page.getByText('Squared the corners.')).toBeVisible({ timeout: 20_000 })

    expect(asked[0]).toMatchObject({ prompt: 'Like a game console', locked: ['tokens'] })
    expect(asked[0].review).toBeFalsy()
    // Claude sees: the second round carries a picture of the stage in each mode, drawn in this browser, and the stage is left in its own.
    expect(asked[1]).toMatchObject({ review: true })
    const pictures = asked[1].pictures as { mode: string; data: string; media_type: string }[]
    expect(pictures.map(({ mode, media_type }) => [mode, media_type])).toEqual([['dark', 'image/jpeg'], ['light', 'image/jpeg']])
    expect(pictures.every(({ data }) => data.length > 1000)).toBe(true)
    expect(pictures[0].data).not.toBe(pictures[1].data)
    await expect(stage.locator('html')).toHaveAttribute('data-theme', 'dark')

    await page.getByRole('button', { name: 'Undo' }).click()
    await page.getByRole('tab', { name: 'The skin' }).click()
    await page.getByText('Switches', { exact: true }).click()
    await expect(page.getByRole('switch', { name: 'Square corners everywhere' })).not.toBeChecked()
    await page.getByRole('button', { name: 'Undo' }).click()
    await expect(page.getByLabel('Name', { exact: true }).first()).toHaveValue('My skin')
  } finally {
    await page.request.put('/api/v1/settings/assistant', { headers: CSRF, data: { provider: 'off', model: '', key: '' } })
  }
})
