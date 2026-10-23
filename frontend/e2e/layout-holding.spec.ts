/**
 * Cards dragged with the mouse between the board, a group and the side bar.
 *
 * The grid knows nothing of groups and side bars: a card dragged from the
 * board is caught over them, and a card inside one is dragged by a hand of
 * our own. Both are checked against what the server saved.
 *
 * ⚠️ Named to sort after `first-start.spec.ts`, which sets up the account.
 */
import { expect, test, type Locator, type Page } from '@playwright/test'

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
interface PageView { id: number; layouts: { lg: Spot[] }; side: { place: string; cards: number[] }; widgets: { id: number; title: string; options: Record<string, unknown> }[] }

async function first(page: Page, slug: string): Promise<PageView> {
  const answer = await page.request.get(`/api/v1/boards/${slug}`)
  expect(answer.ok()).toBe(true)
  return (await answer.json()).pages[0]
}

/** A drag in small steps, the way a hand moves, so both the grid and our own drag see it. */
async function drag(page: Page, from: Locator, to: { x: number; y: number }) {
  const box = (await from.boundingBox())!
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down()
  await page.mouse.move(to.x, to.y, { steps: 20 })
  await page.mouse.up()
}

async function centre(locator: Locator): Promise<{ x: number; y: number }> {
  const box = (await locator.boundingBox())!
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 }
}

test('a card goes into a group, out onto the board and into the side bar', async ({ page }) => {
  const trouble: string[] = []
  page.on('pageerror', (error) => trouble.push(String(error)))
  await page.setViewportSize({ width: 1400, height: 900 })
  await signIn(page)

  const made = await page.request.post('/api/v1/boards', { data: { name: 'Holding' }, headers: CSRF })
  expect(made.status()).toBe(201)
  const board = await made.json()
  const pageId = board.pages[0].id
  const ids: Record<string, number> = {}
  for (const title of ['A', 'B']) {
    const card = await page.request.post(`/api/v1/pages/${pageId}/widgets`, { data: { kind: 'core.markdown', title, options: { content: title } }, headers: CSRF })
    ids[title] = (await card.json()).widget.id
  }
  const group = await page.request.post(`/api/v1/pages/${pageId}/widgets`, { data: { kind: 'core.group', title: 'Box' }, headers: CSRF })
  ids.Box = (await group.json()).widget.id
  await page.request.put(`/api/v1/pages/${pageId}/layouts`, {
    data: { lg: [
      { i: String(ids.A), x: 0, y: 0, w: 6, h: 2 },
      { i: String(ids.B), x: 6, y: 0, w: 6, h: 2 },
      { i: String(ids.Box), x: 0, y: 2, w: 24, h: 3 },
    ] },
    headers: CSRF,
  })

  await page.goto(`/b/${board.slug}`)
  await page.getByRole('button', { name: 'Edit board' }).click()
  const card = (title: string) => page.locator('.react-grid-item', { has: page.locator(`section[aria-label="${title}"]`) })
  const inside = page.locator(`[data-drop="group:${ids.Box}"]`)
  await expect(inside).toBeVisible()

  // From the board into the group: it lights up on the way, and the card is in it.
  await drag(page, card('A').locator('section'), await centre(inside))
  await expect.poll(async () => (await first(page, board.slug)).widgets.find((w) => w.id === ids.Box)?.options.cards).toEqual([ids.A])
  const held = page.locator(`[data-held="${ids.A}"]`)
  await expect(held).toBeVisible()
  const sized = (await first(page, board.slug)).widgets.find((w) => w.id === ids.A)?.options.held_size
  expect(sized).toEqual({ w: 3, h: 2 })

  // Its width from the button at its foot: a quarter becomes a third.
  await held.getByRole('button', { name: /Change the width/ }).click()
  await expect.poll(async () => (await first(page, board.slug)).widgets.find((w) => w.id === ids.A)?.options.held_size).toEqual({ w: 4, h: 2 })

  // Out again, under the board: it comes back as a card of the board.
  const under = (await page.locator('[data-drop="board"]').boundingBox())!
  await drag(page, held, { x: under.x + 40, y: under.y + under.height + 30 })
  await expect.poll(async () => {
    const view = await first(page, board.slug)
    return [view.widgets.find((w) => w.id === ids.Box)?.options.cards, view.layouts.lg.some((spot) => spot.i === String(ids.A))]
  }).toEqual([[], true])

  // The side bar switched on, and B dragged into it.
  await page.getByRole('group', { name: 'Side bar' }).getByRole('button', { name: 'Left' }).click()
  const side = page.locator('[data-drop="side"]')
  await expect(side).toBeVisible()
  await drag(page, card('B').locator('section'), await centre(side))
  await expect.poll(async () => (await first(page, board.slug)).side).toMatchObject({ place: 'left', cards: [ids.B] })
  await expect(side.locator(`[data-held="${ids.B}"]`)).toBeVisible()

  // Outside edit mode the side bar keeps its card, without the frame.
  await page.getByRole('button', { name: 'Done' }).click()
  await expect(page.locator('[data-drop]')).toHaveCount(0)
  await expect(page.locator(`[data-held="${ids.B}"]`)).toBeVisible()
  expect(trouble).toEqual([])
})
