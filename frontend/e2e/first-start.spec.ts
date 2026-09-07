/**
 * The one journey jsdom cannot prove: first start in a real browser.
 *
 * Setup wizard with the demo, the board with live data over the cookie
 * session, edit mode, a kiosk link that opens the board without a session,
 * and sign-out that really removes access.
 */
import { expect, test } from '@playwright/test'

const ACCOUNT = { username: 'e2e-admin', password: 'A-long-enough-password-1' }

test.describe.configure({ mode: 'serial' })

test('setup wizard, demo board, edit mode, kiosk link, sign-out', async ({ page, browser }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/setup$/)

  // Step 1: account.
  await page.getByLabel('User name').fill(ACCOUNT.username)
  await page.getByLabel('Password', { exact: true }).fill(ACCOUNT.password)
  await page.getByLabel('Confirm password').fill(ACCOUNT.password)
  await page.getByRole('button', { name: 'Next' }).click()
  // Step 2: language and look stay as they are.
  await page.getByRole('button', { name: 'Next' }).click()
  // Step 3: the demo is on by default.
  await expect(page.getByRole('switch', { name: 'Start with a demo board' })).toHaveAttribute('aria-checked', 'true')
  await page.getByRole('button', { name: 'Finish' }).click()

  // The demo board opens with its pages and live cards.
  await expect(page).toHaveURL(/\/b\/home/)
  await expect(page.getByRole('button', { name: 'Overview' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Media' })).toBeVisible()
  const containers = page.locator('section[aria-label="Containers"]')
  await expect(containers).toBeVisible()
  await expect(containers.getByText('jellyfin')).toBeVisible({ timeout: 15_000 })

  // Live data arrives through the stream: a value card shows a number soon.
  const requests = page.locator('section[aria-label="Nexview requests"]')
  await expect(requests.locator('.num').first()).not.toHaveText('—', { timeout: 15_000 })

  // Edit mode: the toolbar appears, the library opens and lists adapters.
  await page.getByRole('button', { name: 'Edit board' }).click()
  await page.getByRole('button', { name: 'Add widget' }).first().click()
  await expect(page.getByRole('dialog').getByText('Basics')).toBeVisible()
  await expect(page.getByRole('dialog').getByText('Hosts and containers')).toBeVisible()
  await page.keyboard.press('Escape')

  // The settings button on a card opens the sheet with a real mouse click,
  // even though the card is draggable in edit mode.
  await containers.hover()
  const settingsButton = containers.getByRole('button', { name: 'Widget settings' })
  const box = await settingsButton.boundingBox()
  if (!box) throw new Error('settings button has no box')
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down()
  await page.mouse.up()
  await expect(page.getByRole('dialog').getByRole('heading', { name: 'Widget settings' })).toBeVisible()
  await expect(page.getByRole('dialog').getByLabel('Title')).toHaveValue('Containers')
  await page.keyboard.press('Escape')

  // ⚠️ The middle of a card, not its edge. The drag machinery leaves buttons
  // and links alone so that a press on one is a press, and a card whose body
  // is a link or a strip of bars had nothing to take hold of but the couple of
  // millimetres of padding at its rim. This test grabbed the bottom edge for
  // exactly that reason, which is how the fault got past it.
  // An app tile: its whole face is one anchor, so there is nothing else to
  // aim at. This is the card the fault was reported on.
  const grabbing = page.locator('section[aria-label="Radarr"]').first()
  await expect(grabbing).toBeVisible()
  const grabbed = (await grabbing.boundingBox())!
  await page.mouse.move(grabbed.x + grabbed.width / 2, grabbed.y + grabbed.height / 2)
  await page.mouse.down()
  await page.mouse.move(grabbed.x + grabbed.width / 2 + 40, grabbed.y + grabbed.height / 2 + 20)
  await expect(page.locator('.react-grid-item.react-draggable-dragging')).toHaveCount(1)
  await page.mouse.move(grabbed.x + grabbed.width / 2, grabbed.y + grabbed.height / 2)
  await page.mouse.up()

  // Free placement: dragging a card across the others moves nothing but that
  // card, and a drop on an occupied spot snaps back to where it came from.
  const clock = page.locator('section[aria-label="Clock"]').first()
  const positions = async () => Promise.all((await page.locator('section.card').all()).map(async (card) => `${await card.getAttribute('aria-label')}:${JSON.stringify(await card.boundingBox())}`))
  const before = await positions()
  const from = (await clock.boundingBox())!
  const to = (await containers.boundingBox())!
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2)
  await page.mouse.down()
  for (let step = 1; step <= 12; step += 1) {
    await page.mouse.move(from.x + ((to.x - from.x) * step) / 12 + from.width / 2, from.y + ((to.y - from.y) * step) / 12 + from.height / 2)
  }
  await page.mouse.up()
  await page.waitForTimeout(500)
  expect(await positions()).toEqual(before)
  await page.getByRole('button', { name: 'Done' }).click()

  // Reload keeps the session: the cookie survives a navigation.
  await page.reload()
  // A cold reload on a busy machine can take longer than the default five seconds.
  await expect(page.locator('section[aria-label="Containers"]')).toBeVisible({ timeout: 15_000 })

  // ⚠️ Sorting the board list by dragging its handle, in a real browser.
  // This one cannot be proved anywhere else: jsdom has no layout, so the
  // handler that asks where the rows are gets zeroes from every one of them
  // and the drag looks like it worked no matter what.
  const second = await page.request.post('/api/v1/boards', { data: { name: 'Second board' }, headers: { 'X-Nexdeck-Request': '1' } })
  expect(second.ok()).toBeTruthy()
  await page.goto('/settings/boards')
  const names = () => page.locator('ul > li a[href^="/b/"]').allTextContents()
  await expect.poll(names).toHaveLength(2)
  const wasOrdered = await names()

  const handles = page.getByRole('button', { name: /Drag to move/ })
  const lower = (await handles.nth(1).boundingBox())!
  const upper = (await handles.nth(0).boundingBox())!
  await page.mouse.move(lower.x + lower.width / 2, lower.y + lower.height / 2)
  await page.mouse.down()
  // In steps, because one jump can land outside every row and move nothing.
  for (let step = 1; step <= 6; step += 1) {
    await page.mouse.move(lower.x + lower.width / 2, lower.y + ((upper.y - lower.y) * step) / 6)
  }
  await page.mouse.up()

  await expect.poll(names).toEqual([wasOrdered[1], wasOrdered[0]])
  // And it survives a reload, so it really went to the server.
  await page.reload()
  await expect.poll(names).toEqual([wasOrdered[1], wasOrdered[0]])

  // A kiosk link opens the board in a browser without any session.
  const created = await page.request.post('/api/v1/boards/home/kiosk-tokens', { data: { name: 'e2e wall' }, headers: { 'X-Nexdeck-Request': '1' } })
  expect(created.ok()).toBeTruthy()
  const { url } = (await created.json()) as { url: string }
  const display = await browser.newContext()
  const wall = await display.newPage()
  await wall.goto(url)
  await expect(wall.locator('section[aria-label="Containers"]')).toBeVisible({ timeout: 15_000 })
  await expect(wall.getByRole('button', { name: 'Edit board' })).toHaveCount(0)
  await display.close()

  // Sign-out removes access; the API answers 401 afterwards.
  await page.goto('/settings')
  await page.getByRole('button', { name: 'Sign out here' }).click()
  await expect(page).toHaveURL(/\/login/)
  const me = await page.request.get('/api/v1/auth/me')
  expect(me.status()).toBe(401)
})

test('wrong password is refused with a readable message', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('User name').fill(ACCOUNT.username)
  await page.getByLabel('Password', { exact: true }).fill('not-it')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('alert')).toHaveText('User name or password is wrong.')
})
