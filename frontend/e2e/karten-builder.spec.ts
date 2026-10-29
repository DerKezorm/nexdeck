/**
 * The builder of the card editor against a real server (KARTEN-7 EC-4, EC-5): at the width of a phone a block is
 * added by tapping and moved with the arrows, nothing runs over the edge of the screen; and the whole job, choosing,
 * moving and taking out a block, is done from the keyboard alone. The check of the card and its preview are the
 * server's own: the card brings its demo data, so no service is asked.
 */
import { expect, test, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
/** The words of the editor in one language, to find its buttons by. */
const words = (language: string) => (JSON.parse(readFileSync(path.join(here, '..', 'src', 'i18n', `editor.${language}.json`), 'utf8')) as { editor: Record<string, any> }).editor // eslint-disable-line @typescript-eslint/no-explicit-any

test.use({ hasTouch: true })

const ACCOUNT = { username: 'e2e-admin', password: 'A-long-enough-password-1' }

const CARD = `nexdeck-card: 1
slug: e2e-builder
name: Server at a glance for a very narrow phone screen
version: "1.0.0"
requires: [sonarr]
requests:
  - id: queue
    path: /api/v3/queue
form: builder
demo:
  queue: {records: []}
blocks:
  - {type: text, text: First block with a long text that cannot fit a phone}
  - {type: text, text: Second}
  - type: row
    children:
      - {type: text, text: Third}
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

/** The language of the account, which the page takes at the start. Every later spec signs in to the same account. */
async function setLocale(page: Page, language: string, pair?: string[]) {
  const status = await page.evaluate(
    (body) => fetch('/api/v1/auth/me', { method: 'PATCH', headers: { 'content-type': 'application/json', 'X-Nexdeck-Request': '1' }, body: JSON.stringify(body), credentials: 'same-origin' }).then((response) => response.status),
    pair ? { locale: language, language_pair: pair } : { locale: language },
  )
  expect(status).toBe(200)
}

async function openBuilder(page: Page, language = 'en') {
  const said = words(language)
  await setLocale(page, language)
  await page.goto('/system/custom-cards/new')
  await page.getByRole('button', { name: said.guided.service.paste }).click()
  const field = page.locator('.cm-content')
  await expect(field).toBeVisible()
  await page.evaluate((text) => navigator.clipboard.writeText(text), CARD)
  await field.click()
  await page.keyboard.press('ControlOrMeta+V')
  // A free layout is built in All settings, which is where a pasted builder card opens.
  await expect(page.getByRole('navigation', { name: said.steps.label })).toBeVisible()
  await page.getByRole('button', { name: `2 ${said.steps.look}` }).click()
  await expect(page.getByTestId('card-builder')).toBeVisible()
  // The preview is the server's: the card as the server works it out, with the demo data of the card.
  await expect(page.getByTestId('builder-card')).toContainText('Third')
}

const order = (page: Page) => page.getByTestId('card-builder-tree').getByRole('treeitem').evaluateAll((items) => items.map((item) => item.textContent ?? ''))

test('karten7: a block is added by tapping and moved with the arrows at the width of a phone', async ({ page, context }) => {
  const trouble: string[] = []
  page.on('pageerror', (error) => trouble.push(String(error)))
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.setViewportSize({ width: 375, height: 812 })
  await signIn(page)
  await openBuilder(page)

  // The list of blocks, the tree and the settings stand one below the other, and nothing runs over the edge.
  const wide = () =>
    page.evaluate(() => {
      const over = (element: Element) => element.getBoundingClientRect().right > window.innerWidth + 1
      return { page: document.documentElement.scrollWidth > window.innerWidth, builder: [...document.querySelectorAll('[data-testid="card-builder"] *')].filter(over).length }
    })
  expect(await wide()).toEqual({ page: false, builder: 0 })

  // Tap a block in the tree, then a block in the list: it stands under the one chosen.
  await page.getByTestId('card-builder-tree').getByText('Second').tap()
  await page.getByRole('group', { name: 'Blocks' }).getByRole('button', { name: 'Divider' }).tap()
  expect((await order(page)).map((one) => one.slice(0, 7))).toEqual(['TextFir', 'TextSec', 'Divider', 'Row', 'TextThi'])
  // The arrows move it; no dragging is needed.
  await page.getByRole('button', { name: 'Move up' }).tap()
  expect((await order(page)).map((one) => one.slice(0, 7))).toEqual(['TextFir', 'Divider', 'TextSec', 'Row', 'TextThi'])
  expect(await wide()).toEqual({ page: false, builder: 0 })
  expect(trouble).toEqual([])
})

test('karten7: blocks are chosen with Tab and moved and removed with the keyboard alone', async ({ page, context }) => {
  const trouble: string[] = []
  page.on('pageerror', (error) => trouble.push(String(error)))
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.setViewportSize({ width: 1280, height: 900 })
  await signIn(page)
  await openBuilder(page)

  const second = page.locator('[data-node="blocks[1]"]')
  await page.locator('[data-node="blocks[0]"]').focus()
  await page.keyboard.press('Tab')
  await expect(second).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(second).toHaveAttribute('aria-selected', 'true')
  await page.keyboard.press('ArrowUp')
  expect((await order(page)).map((one) => one.slice(0, 7))).toEqual(['TextSec', 'TextFir', 'Row', 'TextThi'])
  // The focus went with the block, so the next key acts on it.
  await expect(page.locator('[data-node="blocks[0]"]')).toBeFocused()
  await page.keyboard.press('Delete')
  expect((await order(page)).map((one) => one.slice(0, 7))).toEqual(['TextFir', 'Row', 'TextThi'])

  // A row with a block inside asks first, and the question is answered from the keyboard too.
  await page.locator('[data-node="blocks[1]"]').focus()
  await page.keyboard.press('Delete')
  await expect(page.getByRole('dialog')).toContainText('Removes 2 blocks')
  // The dialog keeps the focus inside it; Tab reaches "Remove" in a few steps.
  const remove = page.getByRole('dialog').getByRole('button', { name: 'Remove' })
  for (let step = 0; step < 4 && !(await remove.evaluate((element) => element === document.activeElement)); step += 1) await page.keyboard.press('Tab')
  await expect(remove).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect((await order(page)).map((one) => one.slice(0, 7))).toEqual(['TextFir'])
  expect(trouble).toEqual([])
})

for (const language of ['de', 'fr', 'es', 'it']) {
  test(`karten7: the builder fits a phone in ${language} too`, async ({ page, context }) => {
    const trouble: string[] = []
    page.on('pageerror', (error) => trouble.push(String(error)))
    await context.grantPermissions(['clipboard-read', 'clipboard-write'])
    await page.setViewportSize({ width: 375, height: 812 })
    await signIn(page)
    try {
      await openBuilder(page, language)
      // The palette, the tree and the settings of a chosen block: nothing runs over the edge of the screen.
      await page.getByTestId('card-builder-tree').getByText('Second').tap()
      const over = await page.evaluate(() => {
        const past = (element: Element) => element.getBoundingClientRect().right > window.innerWidth + 1
        return { page: document.documentElement.scrollWidth > window.innerWidth, builder: [...document.querySelectorAll('[data-testid="card-builder"] *')].filter(past).length }
      })
      expect(over).toEqual({ page: false, builder: 0 })
      expect(trouble).toEqual([])
    } finally {
      // Back to English and the pair of a new account, or the specs after this one look for their buttons by words of
      // another language, and the bar offers Italiano where they look for Deutsch.
      await setLocale(page, 'en', ['en', 'de'])
    }
  })
}
