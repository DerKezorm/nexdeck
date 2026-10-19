/**
 * A topology page from the add-page dialog to the plan, against a UniFi
 * connection in demo mode (``topology.demo_console``).
 *
 * ⚠️ Reported on 19.10.2026: the create button of the dialog was off with the
 * name field empty, and nothing said why. Choosing Topology now writes a name
 * in, and an empty field says what it waits for.
 */
import { expect, test } from '@playwright/test'

const ACCOUNT = { username: 'e2e-admin', password: 'A-long-enough-password-1' }

test('a topology page is offered with a UniFi connection, named for you, and shows the network', async ({ page }) => {
  const trouble: string[] = []
  page.on('pageerror', (error) => trouble.push(String(error)))

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

  const made = await page.request.post('/api/v1/integrations', {
    headers: { 'X-Nexdeck-Request': '1' },
    data: { kind: 'unifi', name: 'Demo UniFi', config: { url: 'https://unifi.example.com', api_key: 'demo' }, demo: true },
  })
  expect(made.ok()).toBeTruthy()

  await page.getByRole('button', { name: 'Edit' }).click()
  await page.getByRole('button', { name: 'Add page' }).click()
  const dialog = page.getByRole('dialog')
  const create = dialog.getByRole('button', { name: 'Create' })
  await expect(dialog.getByText('Give the page a name first.')).toBeVisible()
  await expect(create).toBeDisabled()

  await dialog.getByRole('radio', { name: /Topology/ }).click()
  await expect(dialog.getByLabel('Page name')).toHaveValue('Network')
  await expect(dialog.getByText('Give the page a name first.')).toBeHidden()
  await create.click()

  // The demo board has a card page called "Network" already; the new page gets an address of its own.
  await expect(page).toHaveURL(/\/network-2$/)
  const plan = page.locator('[data-topology-canvas]')
  await expect(plan.locator('[data-node] text', { hasText: 'Core switch' })).toBeVisible({ timeout: 15_000 })
  await expect(plan.locator('[data-node]')).toHaveCount(8)
  await expect(page.getByRole('button', { name: /Found/ })).toHaveCount(1)
  expect(trouble).toEqual([])
})
