/**
 * The cover grid in a real browser, in a card too low for its covers
 * (issue #16). jsdom measures no layout, so only here can it show that the
 * rows keep the height of their covers and the card scrolls, instead of the
 * rows being squeezed into the card and every cover lying over the next row.
 *
 * ⚠️ Named to sort after `first-start.spec.ts`, which needs the empty
 * installation.
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

test('covers in a low card keep their rows apart and scroll', async ({ page }) => {
  const trouble: string[] = []
  page.on('pageerror', (error) => trouble.push(String(error)))
  await signIn(page)

  const plex = await page.request.post('/api/v1/integrations', { data: { kind: 'plex', name: 'Plex covers', config: {}, demo: true }, headers: CSRF })
  expect(plex.status()).toBe(201)
  const made = await page.request.post('/api/v1/boards', { data: { name: 'Covers' }, headers: CSRF })
  expect(made.status()).toBe(201)
  const board = await made.json()
  const pageId = board.pages[0].id
  const card = await page.request.post(`/api/v1/pages/${pageId}/widgets`, {
    data: { kind: 'plex.recent', title: 'New covers', integration_id: (await plex.json()).id, options: { kind: 'all', limit: 8 } },
    headers: CSRF,
  })
  expect(card.status()).toBe(201)
  const id = String((await card.json()).widget.id)
  // Four of 24 columns and two rows: room for two covers side by side and
  // not even one of them in full height, while the demo brings six.
  const placed = await page.request.put(`/api/v1/pages/${pageId}/layouts`, { data: { lg: [{ i: id, x: 0, y: 0, w: 4, h: 2 }] }, headers: CSRF })
  expect(placed.ok()).toBe(true)

  await page.goto(`/b/${board.slug}`)
  const grid = page.locator('section[aria-label="New covers"] [data-testid="posters"]')
  await expect(grid.locator('li')).toHaveCount(6)

  const measured = await grid.evaluate((list) => ({
    boxes: [...list.querySelectorAll('li')].map((tile) => {
      const box = tile.getBoundingClientRect()
      return { left: box.left, right: box.right, top: box.top, bottom: box.bottom }
    }),
    scrolls: list.scrollHeight > list.clientHeight,
  }))
  const rows = new Set(measured.boxes.map((box) => Math.round(box.top)))
  expect(rows.size, 'the covers wrap onto several rows').toBeGreaterThan(1)
  for (const [n, a] of measured.boxes.entries()) {
    for (const b of measured.boxes.slice(n + 1)) {
      const side = Math.min(a.right, b.right) - Math.max(a.left, b.left)
      const over = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)
      expect(side > 1 && over > 1, `two covers lie over each other: ${JSON.stringify(a)} and ${JSON.stringify(b)}`).toBe(false)
    }
  }
  expect(measured.scrolls, 'what does not fit is reached by scrolling').toBe(true)
  expect(trouble, `the browser reported: ${trouble.join(' | ')}`).toEqual([])
})
