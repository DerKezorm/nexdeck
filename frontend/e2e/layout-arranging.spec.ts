/**
 * Arranging a board in a real browser: gaps closed, taken back and done
 * again, a selection moved as one, a size from the card's menu, a card sent
 * to another page, and the board put on other columns.
 *
 * ⚠️ Named to sort after `first-start.spec.ts`: the first file of the run is
 * the only one that sees the setup wizard, and that file tests the wizard.
 *
 * What the board shows is checked against what the server saved, because
 * the grid can draw an arrangement that never arrives: the page keeps what it
 * draws and saves it 700 ms later.
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

interface Spot { i: string; x: number; y: number; w: number; h: number }
interface BoardView { slug: string; settings: Record<string, unknown>; pages: { id: number; name: string; layouts: { lg: Spot[] }; widgets: { id: number; title: string }[] }[] }

async function saved(page: Page, slug: string): Promise<BoardView> {
  const answer = await page.request.get(`/api/v1/boards/${slug}`)
  expect(answer.ok()).toBe(true)
  return answer.json()
}

/** Where each card of the first page stands on the server, by title. */
async function places(page: Page, slug: string): Promise<Record<string, [number, number, number, number]>> {
  const view = await saved(page, slug)
  const first = view.pages[0]
  const title = Object.fromEntries(first.widgets.map((w) => [String(w.id), w.title]))
  return Object.fromEntries(first.layouts.lg.map((s) => [title[s.i], [s.x, s.y, s.w, s.h]]))
}

test('a board is arranged by the handful, and every step reaches the server', async ({ page }) => {
  const trouble: string[] = []
  page.on('pageerror', (error) => trouble.push(String(error)))
  await signIn(page)

  // A board of its own, on 24 columns like every new one, with three cards
  // and a hole under the first.
  const made = await page.request.post('/api/v1/boards', { data: { name: 'Arranging' }, headers: CSRF })
  expect(made.status()).toBe(201)
  const board = (await made.json()) as BoardView
  expect(board.settings.columns).toBe(24)
  const pageId = board.pages[0].id
  const ids: Record<string, number> = {}
  for (const title of ['A', 'B', 'C']) {
    const card = await page.request.post(`/api/v1/pages/${pageId}/widgets`, { data: { kind: 'core.markdown', title, options: { content: title } }, headers: CSRF })
    expect(card.status()).toBe(201)
    ids[title] = (await card.json()).widget.id
  }
  const arranged = await page.request.put(`/api/v1/pages/${pageId}/layouts`, {
    data: { lg: [
      { i: String(ids.A), x: 0, y: 0, w: 6, h: 2 },
      { i: String(ids.B), x: 0, y: 5, w: 6, h: 2 },
      { i: String(ids.C), x: 12, y: 0, w: 6, h: 2 },
    ] },
    headers: CSRF,
  })
  expect(arranged.ok()).toBe(true)
  expect((await page.request.post(`/api/v1/boards/${board.slug}/pages`, { data: { name: 'Second' }, headers: CSRF })).status()).toBe(201)

  await page.goto(`/b/${board.slug}`)
  await page.getByRole('button', { name: 'Edit board' }).click()
  const card = (title: string) => page.locator('.react-grid-item', { has: page.locator(`section[aria-label="${title}"]`) })
  await expect(card('B')).toBeVisible()

  // Close the gaps: B comes up under A, C stays in its column.
  await page.getByRole('button', { name: 'Close gaps' }).click()
  await expect.poll(() => places(page, board.slug)).toMatchObject({ A: [0, 0, 6, 2], B: [0, 2, 6, 2], C: [12, 0, 6, 2] })

  // Taken back with the keyboard, and done again.
  await page.keyboard.press('Control+z')
  await expect.poll(() => places(page, board.slug)).toMatchObject({ B: [0, 5, 6, 2] })
  await page.keyboard.press('Control+Shift+z')
  await expect.poll(() => places(page, board.slug)).toMatchObject({ B: [0, 2, 6, 2] })

  // A and B selected, then moved one column to the right as one.
  await card('A').click({ modifiers: ['Shift'] })
  await card('B').click({ modifiers: ['Shift'] })
  await expect(page.getByRole('status').filter({ hasText: '2 cards selected' })).toBeVisible()
  await card('B').focus()
  await page.keyboard.press('ArrowRight')
  await expect.poll(() => places(page, board.slug)).toMatchObject({ A: [1, 0, 6, 2], B: [1, 2, 6, 2], C: [12, 0, 6, 2] })
  await page.keyboard.press('Escape')

  // C to its largest size from the menu: twice the size it is made at.
  await card('C').locator('section').hover()
  await card('C').getByRole('button', { name: 'Size and place' }).click()
  await page.getByRole('menuitemradio', { name: /XL/ }).click()
  await expect.poll(async () => (await places(page, board.slug)).C?.slice(2)).toEqual([12, 4])

  // And C to the other page.
  await card('C').locator('section').hover()
  await card('C').getByRole('button', { name: 'Size and place' }).click()
  await page.getByRole('menuitem', { name: 'Second' }).click()
  await expect(page.getByText('Moved to Second.')).toBeVisible()
  await expect.poll(async () => (await saved(page, board.slug)).pages[1].widgets.map((w) => w.title)).toEqual(['C'])
  await expect(card('C')).toHaveCount(0)

  // Last, the board on 36 columns: everything a half wider again.
  await page.getByRole('button', { name: 'Board settings' }).first().click()
  await page.getByRole('button', { name: 'Look' }).click()
  await page.getByLabel('Columns').selectOption('36')
  await page.getByRole('button', { name: 'Save' }).click()
  await expect.poll(async () => (await saved(page, board.slug)).settings.columns).toBe(36)
  expect(await places(page, board.slug)).toMatchObject({ A: [2, 0, 9, 2], B: [2, 2, 9, 2] })

  expect(trouble, `the browser reported: ${trouble.join(' | ')}`).toEqual([])
})

test('the lowest card can still be resized with the edit bar in front of it', async ({ page }) => {
  // Issue #12: the edit bar floats over the foot of the page, and the page
  // left less room below the board than the bar is high. Scrolled all the way
  // down, the resize corner of the lowest card sat under the bar.
  await signIn(page)
  const made = await page.request.post('/api/v1/boards', { data: { name: 'Tall card' }, headers: CSRF })
  const board = (await made.json()) as BoardView
  const pageId = board.pages[0].id
  const card = await page.request.post(`/api/v1/pages/${pageId}/widgets`, { data: { kind: 'core.markdown', title: 'Tall', options: { content: 'Tall' } }, headers: CSRF })
  const id = String((await card.json()).widget.id)
  // Under the middle of the bar, and taller than the window.
  await page.request.put(`/api/v1/pages/${pageId}/layouts`, { data: { lg: [{ i: id, x: 6, y: 0, w: 8, h: 30 }] }, headers: CSRF })

  await page.goto(`/b/${board.slug}`)
  await page.getByRole('button', { name: 'Edit board' }).click()
  const handle = page.locator('.react-grid-item', { has: page.locator('section[aria-label="Tall"]') }).locator('.react-resizable-handle')
  await expect(handle).toBeVisible()
  await page.evaluate(() => {
    for (const element of [document.scrollingElement, ...document.querySelectorAll('*')]) {
      if (element && element.scrollHeight > element.clientHeight) element.scrollTop = element.scrollHeight
    }
  })

  const box = (await handle.boundingBox())!
  const x = box.x + box.width / 2
  const y = box.y + box.height / 2
  const reachable = await handle.evaluate((corner, [px, py]) => corner.contains(document.elementFromPoint(px, py)), [x, y])
  expect(reachable, 'something lies over the resize corner').toBe(true)

  await page.mouse.move(x, y)
  await page.mouse.down()
  await page.mouse.move(x, y - 200, { steps: 8 })
  await page.mouse.up()
  await expect.poll(async () => (await places(page, board.slug)).Tall?.[3]).toBeLessThan(30)
})
