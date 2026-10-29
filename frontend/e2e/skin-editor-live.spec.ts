/**
 * The skin editor from the list to a saved skin: start from the console
 * example, click a title bar on the stage, give it a frame, save under a name
 * of its own. The stage wears every change; the editor around it wears none.
 */
import { expect, test, type Page } from '@playwright/test'

const ACCOUNT = { username: 'e2e-admin', password: 'A-long-enough-password-1' }
const CSRF = { 'X-Nexdeck-Request': '1' }

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

test('a skin is built on the stage and saved', async ({ page }) => {
  await signIn(page)
  await page.request.delete('/api/v1/skins/e2e-console', { headers: CSRF })
  try {
    await page.goto('/system/skins')
    await page.getByRole('button', { name: 'New skin' }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Retro console' }).click()
    await expect(page).toHaveURL(/\/system\/skins\/new\?from=console/)

    const stage = page.frameLocator('[data-testid=skin-stage]')
    await expect(stage.locator("html[data-skin='console']")).toHaveCount(1)
    await expect(page.getByText('The skin can be worn as it is.')).toBeVisible()

    // On the bar's own edge: its middle is the title, which is a part of its own.
    await stage.locator('.card.glass:not(.card-plain) > header').first().click({ position: { x: 3, y: 3 } })
    const inspector = page.getByTestId('skin-inspector')
    await expect(inspector.getByText('card-titlebar')).toBeVisible()
    await inspector.getByLabel('Frame').selectOption('block')
    await expect
      .poll(() => stage.locator('.card.glass:not(.card-plain) > header').first().evaluate((element) => getComputedStyle(element).borderImageSource))
      .toContain('data:image/svg+xml')
    // The editor around the stage wears nothing of it.
    expect(await page.locator('header.app-bar').first().evaluate((element) => getComputedStyle(element).borderImageSource)).toBe('none')

    await page.getByLabel('Short name').first().fill('e2e-console')
    await page.getByRole('button', { name: 'Save' }).click()
    await expect(page).toHaveURL(/\/system\/skins\/e2e-console\/edit$/)
    await expect(page.getByText('The skin is saved.')).toBeVisible()
    const saved = await (await page.request.get('/api/v1/skins/e2e-console/file')).json()
    expect(saved.parts['card-titlebar']).toEqual({ frame: 'block' })
  } finally {
    await page.request.delete('/api/v1/skins/e2e-console', { headers: CSRF })
  }
})
