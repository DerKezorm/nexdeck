/**
 * The card editor against a real server (KARTEN-9, KARTEN-10): a whole card pasted into the YAML view is checked,
 * shown in the editor and saved; two windows saving the same card meet "Changed by … meanwhile".
 *
 * ⚠️ The paste goes through the browser's clipboard and Ctrl V, not through a filled field: the code editor tells a
 * paste from typing by the event, and only a paste of the whole card switches to the editor.
 */
import { expect, test, type Page } from '@playwright/test'

const ACCOUNT = { username: 'e2e-admin', password: 'A-long-enough-password-1' }

const CARD = `# From a forum post
nexdeck-card: 1
slug: e2e-pasted
name: Pasted from a forum
version: "1.0.0"
requires: [sonarr]
requests:
  - id: queue
    path: /api/v3/queue
form: value
value: totalRecords
demo:
  queue: {totalRecords: 4}
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

test('karten10 AC-6: a whole card pasted into the YAML view is checked, shown in the editor and saved', async ({ page, context }) => {
  const trouble: string[] = []
  page.on('pageerror', (error) => trouble.push(String(error)))
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await signIn(page)

  await page.goto('/system/cards')
  await page.getByRole('button', { name: 'Build a card' }).first().click()
  await expect(page).toHaveURL(/\/system\/custom-cards\/new$/)
  await page.getByRole('button', { name: 'Paste a whole card (YAML)' }).click()

  const field = page.locator('.cm-content')
  await expect(field).toBeVisible()
  await page.evaluate((text) => navigator.clipboard.writeText(text), CARD)
  await field.click()
  await page.keyboard.press('ControlOrMeta+V')

  await expect(page.getByText('The pasted card is valid and shows in the editor now.')).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Steps' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Pasted from a forum', level: 1 })).toBeVisible()

  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByText('Saved. Every board shows the new version.')).toBeVisible()
  await expect(page).toHaveURL(/\/system\/custom-cards\/e2e-pasted\/edit$/)

  // Saved word for word, the comment included.
  const saved = await page.evaluate(async () => (await (await fetch('/api/v1/cards/e2e-pasted')).json()).yaml as string)
  expect(saved).toBe(CARD)

  await page.getByRole('link', { name: 'Back to Custom cards' }).click()
  await expect(page.getByRole('heading', { name: 'Custom cards', level: 2 })).toBeVisible()
  await expect(page.getByText('Pasted from a forum')).toBeVisible()
  expect(trouble).toEqual([])
})

test('karten9 EC-3: two windows save the same card; the second hears who saved meanwhile and may overwrite', async ({ page, context }) => {
  await signIn(page)
  const other = await context.newPage()

  for (const one of [page, other]) {
    await one.goto('/system/custom-cards/e2e-pasted/edit')
    await expect(one.getByRole('heading', { name: 'Pasted from a forum', level: 1 })).toBeVisible()
    // The guided way can show this card, so it opens there; the texts are under All settings.
    await one.getByRole('button', { name: 'All settings' }).click()
    await one.getByRole('button', { name: '4 Texts' }).click()
  }

  await page.getByRole('textbox', { name: 'Name, English (required)' }).fill('Saved first')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByText('Saved. Every board shows the new version.')).toBeVisible()

  await other.getByRole('textbox', { name: 'Name, English (required)' }).fill('Saved second')
  await other.getByRole('button', { name: 'Save', exact: true }).click()
  const question = other.getByRole('dialog', { name: `Changed by ${ACCOUNT.username} meanwhile` })
  await expect(question).toBeVisible()
  await question.getByRole('button', { name: 'Overwrite' }).click()
  await expect(other.getByText('Saved. Every board shows the new version.')).toBeVisible()

  await page.reload()
  await expect(page.getByRole('heading', { name: 'Saved second', level: 1 })).toBeVisible()
  await page.getByRole('button', { name: 'All settings' }).click()

  // And the other way out: the first window saves again, hears of the overwrite, and reloads.
  await page.getByRole('button', { name: '4 Texts' }).click()
  await page.getByRole('textbox', { name: 'Name, English (required)' }).fill('Saved third')
  await other.getByRole('textbox', { name: 'Name, English (required)' }).fill('Saved fourth')
  await other.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(other.getByText('Saved. Every board shows the new version.')).toBeVisible()
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  const again = page.getByRole('dialog', { name: `Changed by ${ACCOUNT.username} meanwhile` })
  await again.getByRole('button', { name: 'Reload' }).click()
  // Own changes would go with the reload, so it asks once more.
  await page.getByRole('dialog', { name: 'Drop your changes and reload?' }).getByRole('button', { name: 'Drop and reload' }).click()
  await expect(page.getByRole('heading', { name: 'Saved fourth', level: 1 })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeDisabled()
})
