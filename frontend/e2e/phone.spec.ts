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

/**
 * Wait until every card lies inside the board's new width.
 *
 * ⚠️ The board is narrower at once; the cards follow a moment later, when the
 * grid has drawn its new layout. Two equal readings 150 ms apart were taken
 * for "settled" while the grid had not started yet, and the phone was measured
 * with the wide arrangement: 3 runs of 28 on 25.09.2026, the cards at left
 * 1050 on a board 390 wide.
 */
async function fitted(page: Page): Promise<void> {
  await expect.poll(() => page.evaluate(() => {
    const grid = document.querySelector('.board')
    if (!grid) return false
    const right = grid.getBoundingClientRect().right
    return [...grid.querySelectorAll(':scope > .react-grid-item')].every((element) => element.getBoundingClientRect().right <= right + 1)
  })).toBe(true)
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
  await fitted(page)
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
  await fitted(page)
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
  await fitted(page)
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

/**
 * ⚠️ Issue #27, 04.10.2026: on an iPad held upright (1032 wide) the bar ran
 * past the right edge, the account menu was cut off and the whole page could
 * be dragged sideways. The search field kept the width of its placeholder,
 * because a flex item does not shrink below its content unless told to.
 */
test('the bar of a board with four pages fits a tablet held upright', async ({ page }) => {
  await signIn(page)
  const write = { headers: { 'X-Nexdeck-Request': '1' } }
  const made = await page.request.post('/api/v1/boards', { ...write, data: { name: 'Upright', slug: 'upright' } })
  expect(made.status()).toBe(201)
  try {
    for (const name of ['Overview', 'LAN', 'Remote', 'IP']) {
      const added = await page.request.post('/api/v1/boards/upright/pages', { ...write, data: { name } })
      expect(added.status()).toBe(201)
    }
    for (const size of [{ width: 1032, height: 1376 }, { width: 820, height: 1180 }, { width: 768, height: 1024 }]) {
      await page.setViewportSize(size)
      await page.goto('/b/upright')
      const account = page.getByRole('button', { name: ACCOUNT.username, exact: true })
      await expect(account).toBeVisible()
      const box = await account.boundingBox()
      expect(box && box.x + box.width, `the account menu leaves the screen at ${size.width}`).toBeLessThanOrEqual(size.width)
      const sideways = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
      expect(sideways, `the page can be dragged sideways at ${size.width}`).toBeLessThanOrEqual(0)
      await expect(page.getByRole('button', { name: 'IP', exact: true })).toBeVisible()
      if (size.width >= 820) {
        // Not only there, but in sight: the pages scroll once they no longer fit, and an iPad fits all of them.
        const last = await page.getByRole('button', { name: 'IP', exact: true }).boundingBox()
        const pages = await page.getByRole('navigation', { name: 'Pages' }).boundingBox()
        expect(last && pages && last.x + last.width, `the last page is scrolled away at ${size.width}`).toBeLessThanOrEqual((pages?.x ?? 0) + (pages?.width ?? 0) + 1)
      }
    }

    // The installed app: iPadOS 26 blurs the top of the page unless the bar there is one solid colour.
    // Chromium cannot pretend to be installed (setEmulatedMedia ignores display-mode), so the rule
    // for it is switched on where it stands, in its own layer, and the bar is measured.
    const bar = () => page.locator('header').first().evaluate((element) => {
      const style = getComputedStyle(element)
      return { background: style.backgroundColor, filter: style.backdropFilter }
    })
    expect((await bar()).filter, 'the bar in a browser tab is no longer glass').not.toBe('none')
    const found = await page.evaluate(() => {
      const walk = (rules: CSSRuleList): boolean => {
        for (const rule of [...rules]) {
          if (rule instanceof CSSMediaRule && rule.conditionText.includes('display-mode: standalone')) {
            const parent = rule.parentRule as CSSGroupingRule | null
            const inner = [...rule.cssRules].map((one) => one.cssText).join('\n')
            if (parent) parent.insertRule(`@media all { ${inner} }`, parent.cssRules.length)
            else rule.parentStyleSheet?.insertRule(`@media all { ${inner} }`, rule.parentStyleSheet.cssRules.length)
            return true
          }
          if ('cssRules' in rule && walk((rule as CSSGroupingRule).cssRules)) return true
        }
        return false
      }
      return [...document.styleSheets].some((sheet) => walk(sheet.cssRules))
    })
    expect(found, 'no rule for the installed app').toBe(true)
    expect((await bar()).filter, 'the bar of the installed app is still glass').toBe('none')
    expect((await bar()).background, 'the bar of the installed app lets the page show through').toMatch(/^rgb\(/)
  } finally {
    await page.request.delete('/api/v1/boards/upright', write)
  }
})
