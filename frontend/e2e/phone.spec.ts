/**
 * A phone shows the board in the order it was arranged on the monitor, and a
 * tablet shows the arrangement itself.
 *
 * ⚠️ Reported on 10.09.2026: on the phone the cards stood in no order at all.
 * The phone and the tablet kept layouts of their own, written once when a
 * card was added and never again. jsdom has no widths, so only a real browser
 * can say where a card ends up.
 *
 * The name sorts after `first-start`, which needs the empty installation.
 */
import { expect, test, type Page } from '@playwright/test'

const ACCOUNT = { username: 'e2e-admin', password: 'A-long-enough-password-1' }

type Seen = { name: string; top: number; left: number; width: number }
type Board = { width: number; cards: Seen[] }

async function signIn(page: Page): Promise<void> {
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
  await page.goto('/b/home')
  await expect(page.locator('section[aria-label="Containers"]')).toBeVisible()
}

function gridWidth(page: Page): Promise<number> {
  return page.evaluate(() => document.querySelector('.board')?.getBoundingClientRect().width ?? 0)
}

/** Every card in the order a reader meets them, read once nothing moves any more. */
async function cards(page: Page): Promise<Board> {
  const measure = () =>
    page.evaluate(() => {
      const grid = document.querySelector('.board')
      if (!grid) return { width: 0, cards: [] }
      const origin = grid.getBoundingClientRect()
      const seen = [...grid.querySelectorAll(':scope > .react-grid-item')].map((element) => {
        const box = element.getBoundingClientRect()
        return {
          name: element.querySelector('section[aria-label]')?.getAttribute('aria-label') ?? '',
          top: Math.round(box.top - origin.top),
          left: Math.round(box.left - origin.left),
          width: Math.round(box.width),
        }
      })
      seen.sort((a, b) => a.top - b.top || a.left - b.left)
      return { width: Math.round(origin.width), cards: seen }
    })
  // The grid animates a change of width; read until two readings agree.
  let last = JSON.stringify(await measure())
  for (let attempt = 0; attempt < 40; attempt += 1) {
    await page.waitForTimeout(150)
    const now = JSON.stringify(await measure())
    if (now === last) return JSON.parse(now) as Board
    last = now
  }
  throw new Error('the board never stopped moving')
}

test('a phone stacks the board in the order of the wide one, a tablet shows it as arranged', async ({ page }) => {
  await signIn(page)

  const wide = await cards(page)
  expect(wide.cards.length, 'too few cards on the board to say anything').toBeGreaterThan(8)
  const order = wide.cards.map((card) => card.name)

  await page.setViewportSize({ width: 390, height: 844 })
  await expect.poll(() => gridWidth(page)).toBeLessThan(400)
  const phone = await cards(page)
  expect(phone.cards.map((card) => card.name), 'the phone does not follow the order of the wide board').toEqual(order)
  // The full width or half of it, nothing narrower: a list at a third of a
  // phone was what the report was about.
  for (const card of phone.cards) {
    expect(card.width / phone.width, `${card.name} is squeezed on the phone`).toBeGreaterThan(0.45)
  }
  const perRow = new Map<number, number>()
  for (const card of phone.cards) perRow.set(card.top, (perRow.get(card.top) ?? 0) + 1)
  expect([...perRow.values()].some((count) => count === 2), 'no two small cards share a row').toBe(true)
  expect([...perRow.values()].every((count) => count <= 2), 'more than two cards in a row on a phone').toBe(true)

  await page.setViewportSize({ width: 820, height: 1180 })
  await expect.poll(() => gridWidth(page)).toBeGreaterThan(700)
  const tablet = await cards(page)
  expect(tablet.cards.map((card) => card.name), 'the tablet does not show the wide arrangement').toEqual(order)
  // The same arrangement, only narrower: every card starts at the same share of the width.
  tablet.cards.forEach((card, index) => {
    const there = wide.cards[index].left / wide.width
    expect(Math.abs(card.left / tablet.width - there), `${card.name} stands somewhere else on the tablet`).toBeLessThan(0.03)
  })
})

test('on a phone, edit mode moves nothing and saves nothing', async ({ page }) => {
  const saves: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'PUT' && request.url().includes('/layouts')) saves.push(request.url())
  })
  await page.setViewportSize({ width: 390, height: 844 })
  await signIn(page)
  await expect.poll(() => gridWidth(page)).toBeLessThan(400)
  const before = await cards(page)

  await page.getByRole('button', { name: 'Edit board' }).first().click()
  await expect(page.getByRole('note')).toContainText('wider screen')

  // A drag down the screen, the way a finger would try it.
  const first = page.locator('.board > .react-grid-item').first()
  const box = await first.boundingBox()
  if (!box) throw new Error('the first card has no box')
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2 + 300, { steps: 10 })
  await page.mouse.up()

  const after = await cards(page)
  expect(after.cards.map((card) => card.name)).toEqual(before.cards.map((card) => card.name))
  // The board saves 700 ms after the last change; give it more than that.
  await page.waitForTimeout(1500)
  expect(saves, 'a phone sent its stack to the server').toEqual([])
})
