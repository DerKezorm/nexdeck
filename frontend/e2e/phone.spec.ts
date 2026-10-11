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

test('the bar stays on the page while another board loads', async ({ page }) => {
  // ⚠️ Issue #27, 06.10.2026: in the app installed on iPadOS 26 the blur came back over the bar
  // after a switch to another board, and stayed until the app was started again. Switching
  // pages did no harm. The board that was not loaded yet showed a spinner and no bar at all,
  // and WebKit looks for a solid bar at the top edge; this is the one moment it found none.
  await signIn(page)
  const write = { headers: { 'X-Nexdeck-Request': '1' } }
  for (const [name, slug] of [['Switch from', 'switch-first'], ['Switch to', 'switch-second']]) {
    const made = await page.request.post('/api/v1/boards', { ...write, data: { name, slug, in_menu: true } })
    expect(made.status()).toBe(201)
  }
  try {
    await page.setViewportSize({ width: 1032, height: 1376 })
    await page.goto('/b/switch-first')
    await expect(page.getByRole('button', { name: 'Switch from', exact: true })).toBeVisible()
    // Every moment without a bar is counted, and the bar itself is kept to compare.
    await page.evaluate(() => {
      const state = window as unknown as { barGone: number; bar: Element | null }
      state.barGone = 0
      state.bar = document.querySelector('header.app-bar')
      new MutationObserver(() => {
        if (!document.querySelector('header.app-bar')) state.barGone += 1
      }).observe(document.body, { childList: true, subtree: true })
    })
    // The second board answers late, as it does over a slow line.
    let held = false
    await page.route('**/api/v1/boards/switch-second', async (route) => {
      held = true
      await new Promise((resolve) => setTimeout(resolve, 1500))
      await route.continue()
    })
    await page.getByRole('button', { name: 'Switch from', exact: true }).click()
    await page.getByRole('menuitem', { name: 'Switch to', exact: true }).click()
    await expect.poll(() => held).toBe(true)
    // Read once while the answer is held back, not polled: a poll waits until the board is there.
    expect(await page.evaluate(() => document.querySelectorAll('header.app-bar').length), 'no bar while the board loads').toBe(1)
    await expect(page.getByRole('button', { name: 'Switch to', exact: true })).toBeVisible()
    const after = await page.evaluate(() => {
      const state = window as unknown as { barGone: number; bar: Element | null }
      return { gone: state.barGone, same: state.bar === document.querySelector('header.app-bar') }
    })
    expect(after.gone, 'the bar left the page during the switch').toBe(0)
    expect(after.same, 'the bar was taken down and built anew').toBe(true)
  } finally {
    await page.unroute('**/api/v1/boards/switch-second')
    await page.request.delete('/api/v1/boards/switch-first', write)
    await page.request.delete('/api/v1/boards/switch-second', write)
  }
})

/**
 * The rules of the installed app switched on where they stand. Chromium cannot pretend to be installed
 * (setEmulatedMedia ignores display-mode), so they are copied into a layer that always applies.
 */
async function asInstalled(page: Page): Promise<void> {
  // Every such rule, not the first: they stand in more than one layer.
  const found = await page.evaluate(() => {
    const rules: CSSMediaRule[] = []
    const walk = (list: CSSRuleList) => {
      for (const rule of [...list]) {
        if (rule instanceof CSSMediaRule && rule.conditionText.includes('display-mode: standalone')) rules.push(rule)
        else if ('cssRules' in rule) walk((rule as CSSGroupingRule).cssRules)
      }
    }
    for (const sheet of [...document.styleSheets]) walk(sheet.cssRules)
    for (const rule of rules) {
      const parent = rule.parentRule as CSSGroupingRule | null
      const inner = [...rule.cssRules].map((one) => one.cssText).join('\n')
      if (parent) parent.insertRule(`@media all { ${inner} }`, parent.cssRules.length)
      else rule.parentStyleSheet?.insertRule(`@media all { ${inner} }`, rule.parentStyleSheet.cssRules.length)
    }
    return rules.length
  })
  expect(found, 'the rules for the installed app, near the glass and over the utilities').toBeGreaterThanOrEqual(2)
}

/** What lies on top in the middle of the bar: the bar itself, or something laid over it. */
function onTopOfTheBar(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    const bar = document.querySelector('header.app-bar')
    const hit = document.elementFromPoint(window.innerWidth / 2, 24)
    return Boolean(bar && hit && bar.contains(hit))
  })
}

test('in the installed app nothing lays its veil over the bar', async ({ page }) => {
  // ⚠️ Issue #36, 11.10.2026: after every update the window with what is new brought the blur of iPadOS 26
  // back over the bar, and it stayed. Its dark veil covered the whole page, the bar with it, as did every
  // dialog, sheet and the search. Below the bar they now leave it in sight; in a browser tab nothing changes.
  await signIn(page)
  await page.setViewportSize({ width: 1032, height: 1376 })
  const write = { headers: { 'X-Nexdeck-Request': '1' } }
  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as { seen_version: string | null }
  try {
    expect((await page.request.patch('/api/v1/auth/me', { ...write, data: { seen_version: '0.0.1' } })).status()).toBe(200)
    await page.goto('/b/home')
    const news = page.getByRole('dialog')
    await expect(news).toBeVisible()
    expect(await onTopOfTheBar(page), 'in a browser tab the veil covers the bar as it always did').toBe(false)
    await asInstalled(page)
    expect(await onTopOfTheBar(page), 'the window with what is new covers the bar').toBe(true)
    await news.getByRole('button', { name: 'Close' }).first().click()
    await expect(news).toBeHidden()

    await page.getByRole('button', { name: 'Notices', exact: true }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    expect(await onTopOfTheBar(page), 'the notices cover the bar').toBe(true)
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toBeHidden()

    await page.keyboard.press('Control+k')
    await expect(page.getByRole('dialog', { name: 'Search' })).toBeVisible()
    expect(await onTopOfTheBar(page), 'the search covers the bar').toBe(true)
    await page.keyboard.press('Escape')
  } finally {
    await page.request.patch('/api/v1/auth/me', { ...write, data: { seen_version: me.seen_version } })
  }
})

test('the bar stays on the page while a page that loads on demand arrives', async ({ page }) => {
  // Issue #36, 11.10.2026, looking for the second way the blur came back: the first visit to a page that is
  // loaded on demand. It never had a moment without a bar, because the router keeps the old page on screen
  // until the new one is there (a mutation probe that took a bar out of the spinner stayed green). This keeps
  // it that way; a fallback without a bar would be the board switch of issue #27 over again.
  await signIn(page)
  await page.setViewportSize({ width: 1032, height: 1376 })
  await page.evaluate(() => {
    const state = window as unknown as { barGone: number }
    state.barGone = 0
    new MutationObserver(() => {
      if (!document.querySelector('header.app-bar')) state.barGone += 1
    }).observe(document.body, { childList: true, subtree: true })
  })
  let held = false
  await page.route(/NoticesPage/, async (route) => {
    held = true
    await new Promise((resolve) => setTimeout(resolve, 1500))
    await route.continue()
  })
  try {
    await page.getByRole('button', { name: 'Notices', exact: true }).click()
    await page.getByRole('link', { name: 'All notices' }).click()
    await expect.poll(() => held).toBe(true)
    expect(await page.evaluate(() => document.querySelectorAll('header.app-bar').length), 'no bar while the page loads').toBe(1)
    await expect(page).toHaveURL(/\/notices$/)
    await expect(page.getByRole('heading', { name: 'Notices' })).toBeVisible()
    expect(await page.evaluate(() => (window as unknown as { barGone: number }).barGone), 'the bar left the page on the way').toBe(0)
  } finally {
    await page.unroute(/NoticesPage/)
  }
})

test('the weather chips stay clear of the temperature on a narrow card', async ({ page }) => {
  // Issue #27: on an upright iPad the chip "Feels like" lay over "19 °C". The chips came with the
  // width of the screen, and an iPad Pro held upright is as wide as a laptop, while the card is not.
  await signIn(page)
  const write = { headers: { 'X-Nexdeck-Request': '1' } }
  const made = await page.request.post('/api/v1/boards', { ...write, data: { name: 'Weather', slug: 'weather-narrow' } })
  expect(made.status()).toBe(201)
  try {
    const pageId = (await made.json()).pages[0].id
    const ids: string[] = []
    for (const title of ['Weather narrow', 'Weather wide']) {
      const card = await page.request.post(`/api/v1/pages/${pageId}/widgets`, { ...write, data: { kind: 'weather.current', title, options: { place: 'Springfield' } } })
      expect(card.status()).toBe(201)
      ids.push(String((await card.json()).widget.id))
    }
    // Six of 24 columns, as on the iPad in the report, and one with room to spare.
    const placed = await page.request.put(`/api/v1/pages/${pageId}/layouts`, {
      ...write,
      data: { lg: [{ i: ids[0], x: 0, y: 0, w: 6, h: 2 }, { i: ids[1], x: 6, y: 0, w: 12, h: 2 }] },
    })
    expect(placed.ok()).toBe(true)

    const measure = (title: string) =>
      page.locator(`section[aria-label="${title}"]`).evaluate((card) => {
        const box = (element: Element) => element.getBoundingClientRect()
        const temperature = card.querySelector('.num[class*="text-[28px]"]')
        const chips = [...card.querySelectorAll('.chip')].filter((chip) => box(chip).width > 0)
        const outer = box(card)
        // The text, not its box: the box shrinks with the column and the number runs out of it.
        const range = document.createRange()
        if (temperature) range.selectNodeContents(temperature)
        const number = temperature ? range.getBoundingClientRect() : null
        return {
          chips: chips.length,
          over: chips.some((chip) => {
            const c = box(chip)
            return !!number && c.left < number.right && c.right > number.left && c.top < number.bottom && c.bottom > number.top
          }),
          outside: chips.some((chip) => box(chip).right > outer.right + 1),
        }
      })
    for (const size of [{ width: 1032, height: 1376 }, { width: 1376, height: 1032 }, { width: 820, height: 1180 }]) {
      await page.setViewportSize(size)
      await page.goto('/b/weather-narrow')
      // Both cards with their numbers: a card without data yet has no chips to lie anywhere.
      for (const title of ['Weather narrow', 'Weather wide']) {
        await expect(page.locator(`section[aria-label="${title}"] .num[class*="text-[28px]"]`)).toContainText(/\d/)
      }
      await fitted(page)
      for (const title of ['Weather narrow', 'Weather wide']) {
        const seen = await measure(title)
        expect(seen.over, `a chip lies over the temperature on "${title}" at ${size.width}`).toBe(false)
        expect(seen.outside, `a chip runs out of "${title}" at ${size.width}`).toBe(false)
      }
      // Where there is room the chips are still there.
      expect((await measure('Weather wide')).chips, `the wide card lost its chips at ${size.width}`).toBe(2)
    }
  } finally {
    await page.request.delete('/api/v1/boards/weather-narrow', write)
  }
})
