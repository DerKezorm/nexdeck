/**
 * A change made in a card's settings has to survive the save.
 *
 * ⚠️ Reported twice: "I change something, the card shows it, then it jumps
 * back, and only F5 gives me the result." Every unit test was green, because
 * jsdom never runs the sheet against a real server and never sees the stream
 * push the collector's older answer over the top.
 */
import { expect, test } from '@playwright/test'

const ACCOUNT = { username: 'e2e-admin', password: 'A-long-enough-password-1' }

/** Two colons means seconds are shown: 21:04:37 against 21:04. */
const colons = (text: string) => (text.match(/:/g) ?? []).length

test('a change made in the settings is still there after the save', async ({ page }) => {
  const trouble: string[] = []
  page.on('pageerror', (error) => trouble.push(String(error)))

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

  await page.getByRole('button', { name: 'Edit' }).click()
  const clock = page.locator('section[aria-label="Clock"]').first()
  const time = clock.locator('.num').first()
  await expect(time).toBeVisible()
  expect(colons(await time.textContent() ?? ''), 'the clock starts without seconds').toBe(1)

  await clock.hover()
  await clock.getByRole('button', { name: 'Widget settings' }).click()
  const sheet = page.getByRole('dialog')
  await expect(sheet).toBeVisible()

  // The change: seconds on. The card shows it at once, through the preview.
  await sheet.getByRole('switch', { name: 'Show seconds' }).click()
  await expect
    .poll(async () => colons(await time.textContent() ?? ''), { timeout: 10_000 })
    .toBe(2)

  await sheet.getByRole('button', { name: 'Save' }).click()
  await expect(sheet).toBeHidden()

  // ⚠️ The moment this test exists for. The preview is held until the server
  // has fetched with the new options; without that hold the card fell back to
  // the collector's last answer, which still had the old ones.
  for (const wait of [0, 1000, 3000, 6000]) {
    if (wait) await page.waitForTimeout(wait)
    expect(colons(await time.textContent() ?? ''), `seconds gone ${wait}ms after the save`).toBe(2)
  }

  // And it is really saved, not only on screen.
  await page.reload()
  await expect.poll(async () => colons(await time.textContent() ?? ''), { timeout: 10_000 }).toBe(2)

  expect(trouble, `the browser reported: ${trouble.join(' | ')}`).toEqual([])
})

/**
 * The same fault, forced instead of waited for.
 *
 * ⚠️ The test above catches this about one run in five, because it needs a
 * board request to be in flight at the moment Save is pressed. That is a race
 * a test should not be left to win by luck: the fix went in, five runs came
 * back green with the fix taken out again, and only the long loop found it.
 *
 * So the race is built here. Every board request is answered with the body
 * from before the save, which is exactly what an in-flight request delivers,
 * and react-query hands that one to the `refetch()` a save makes rather than
 * starting a new one. A card released against that answer drops back to its
 * old options, which is what "it jumps back and F5 fixes it" looks like.
 */
test('a board answer from before the save does not undo it', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByLabel('User name')).toBeVisible()
  await page.getByLabel('User name').fill(ACCOUNT.username)
  await page.getByLabel('Password', { exact: true }).fill(ACCOUNT.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/b\//)

  const clock = page.locator('section[aria-label="Clock"]').first()
  const time = clock.locator('.num').first()
  await expect(time).toBeVisible()
  const before = colons(await time.textContent() ?? '')

  // The board exactly as it stands now: this is what a request that started
  // before the save comes back with.
  const stale = await (await page.request.get('/api/v1/boards/home')).text()
  let served = 0
  await page.route('**/api/v1/boards/home*', async (route) => {
    served += 1
    await new Promise((resume) => setTimeout(resume, 300))
    await route.fulfill({ status: 200, contentType: 'application/json', body: stale })
  })

  await page.getByRole('button', { name: 'Edit' }).click()
  await clock.hover()
  await clock.getByRole('button', { name: 'Widget settings' }).click()
  const sheet = page.getByRole('dialog')
  await expect(sheet).toBeVisible()
  await sheet.getByRole('switch', { name: 'Show seconds' }).click()
  await expect.poll(async () => colons(await time.textContent() ?? ''), { timeout: 10_000 }).toBe(before === 2 ? 1 : 2)
  const after = colons(await time.textContent() ?? '')

  await sheet.getByRole('button', { name: 'Save' }).click()
  await expect(sheet).toBeHidden()

  for (const wait of [0, 1000, 3000, 6000]) {
    if (wait) await page.waitForTimeout(wait)
    expect(colons(await time.textContent() ?? ''), `the stale answer won ${wait}ms after the save`).toBe(after)
  }
  expect(served, 'no board request was answered with the older body, so this test proves nothing').toBeGreaterThan(0)

  // And the save really happened, once the board is allowed to answer truthfully.
  await page.unroute('**/api/v1/boards/home*')
  await page.reload()
  await expect.poll(async () => colons(await time.textContent() ?? ''), { timeout: 10_000 }).toBe(after)
})
