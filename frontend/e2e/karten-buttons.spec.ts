/**
 * The Buttons step of the card editor against a real server (KARTEN-8): a card with buttons is pasted, shown in the
 * step at the width of a phone without anything running over, and worked with from the keyboard.
 */
import { expect, test, type Page } from '@playwright/test'

const ACCOUNT = { username: 'e2e-admin', password: 'A-long-enough-password-1' }

const CARD = `nexdeck-card: 1
slug: e2e-buttons
name: Downloads with buttons for a very narrow phone screen
version: "1.0.0"
requires: [sonarr]
requests:
  - id: queue
    path: /api/v3/queue
form: list
rows: {select: records}
item:
  title: title
demo:
  queue: {records: [{id: 1, title: Example.Show.S01E01}]}
buttons:
  - id: pause
    label: Pause everything that is running
    icon: pause
    where: row
    method: POST
    path: /api/v2/torrents/pause
    send: form
    body: {hashes: "{id}"}
  - id: limit
    label: Limit the speed
    where: card
    method: POST
    path: /api/v2/transfer/setDownloadLimit
    send: form
    body: {limit: "{ask.kib}"}
    confirm: true
    asks:
      - {name: kib, label: KiB per second, type: number, min: 0, max: 100000, step: 1}
`

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

test('karten8: the Buttons step fits a phone and is worked from the keyboard', async ({ page, context }) => {
  const trouble: string[] = []
  page.on('pageerror', (error) => trouble.push(String(error)))
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.setViewportSize({ width: 375, height: 812 })
  await signIn(page)

  await page.goto('/system/custom-cards/new')
  await page.getByRole('button', { name: 'Paste a whole card (YAML)' }).click()
  const field = page.locator('.cm-content')
  await expect(field).toBeVisible()
  await page.evaluate((text) => navigator.clipboard.writeText(text), CARD)
  await field.click()
  await page.keyboard.press('ControlOrMeta+V')
  await expect(page.getByRole('navigation', { name: 'Steps' })).toBeVisible()

  // The card pasted is one the guided way can show; the buttons are in All settings.
  await page.getByRole('button', { name: 'All settings' }).click()
  await page.getByRole('button', { name: '4 Buttons' }).click()
  await expect(page.getByTestId('card-button-0')).toBeVisible()
  await expect(page.getByTestId('card-button-1')).toBeVisible()

  // Nothing runs over the edge of the screen, neither the page nor a button's form.
  const wide = await page.evaluate(() => {
    const over = (element: Element) => element.getBoundingClientRect().right > window.innerWidth + 1
    return {
      page: document.documentElement.scrollWidth > window.innerWidth,
      forms: [...document.querySelectorAll('[data-testid^="card-button-"]')].filter(over).length,
    }
  })
  expect(wide).toEqual({ page: false, forms: 0 })

  // The keyboard: Tab reaches the fields of the first button in order, Enter presses "Add an input".
  const first = page.getByTestId('card-button-1').getByRole('button', { name: 'Add an input' })
  await first.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByTestId('card-button-1-ask-1')).toBeVisible()
  await page.keyboard.press('Tab')
  expect(await page.evaluate(() => document.activeElement?.closest('[data-testid^="card-button-"]') !== null)).toBe(true)

  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByText('Saved. Every board shows the new version.')).toBeVisible()
  expect(trouble).toEqual([])
})
