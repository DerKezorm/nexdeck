/* Screenshots of a running instance for the README and the project page.
 *
 *   node tools/shots.mjs http://localhost:5176 admin password out/
 *
 * Signs in through the API, then captures the board on the desktop, on a
 * phone, in light mode and on a kiosk display.
 */
import { chromium } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import path from 'node:path'

const [base = 'http://localhost:5176', username = 'admin', password = '', out = 'shots'] = process.argv.slice(2)
mkdirSync(out, { recursive: true })

const browser = await chromium.launch()
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, locale: 'en-US' })
const login = await context.request.post(`${base}/api/v1/auth/login`, { data: { username, password } })
if (!login.ok()) {
  console.error('sign-in failed', login.status(), await login.text())
  process.exit(1)
}
await context.request.patch(`${base}/api/v1/auth/me`, { data: { locale: 'en', theme: 'dark' }, headers: { 'X-Nexdeck-Request': '1' } })

const page = await context.newPage()
await page.goto(`${base}/b/home`)
await page.waitForSelector('section[aria-label]', { timeout: 20000 })
await page.waitForTimeout(4000)
await page.screenshot({ path: path.join(out, 'board-desktop-dark.png'), fullPage: true })

await page.goto(`${base}/b/home/media`)
await page.waitForTimeout(4000)
await page.screenshot({ path: path.join(out, 'board-media-dark.png'), fullPage: true })

await page.goto(`${base}/b/home?theme=light`)
await page.waitForTimeout(4000)
await page.screenshot({ path: path.join(out, 'board-desktop-light.png'), fullPage: true })

await page.goto(`${base}/settings/integrations?theme=dark`)
await page.waitForTimeout(2500)
await page.screenshot({ path: path.join(out, 'settings-integrations.png'), fullPage: false })

// Edit mode with the library open.
await page.goto(`${base}/b/home`)
await page.waitForTimeout(3000)
await page.getByRole('button', { name: 'Edit board' }).click()
await page.getByRole('button', { name: 'Add widget' }).first().click()
await page.waitForTimeout(1500)
await page.screenshot({ path: path.join(out, 'board-edit-library.png'), fullPage: false })

// Phone.
const phone = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, locale: 'en-US' })
await phone.request.post(`${base}/api/v1/auth/login`, { data: { username, password } })
const mobile = await phone.newPage()
await mobile.goto(`${base}/b/home`)
await mobile.waitForTimeout(4000)
await mobile.screenshot({ path: path.join(out, 'board-phone.png'), fullPage: false })

// Kiosk.
const created = await context.request.post(`${base}/api/v1/boards/home/kiosk-tokens`, { data: { name: 'shots' }, headers: { 'X-Nexdeck-Request': '1' } })
const { url, id } = await created.json()
const wall = await browser.newContext({ viewport: { width: 1280, height: 800 }, locale: 'en-US' })
const display = await wall.newPage()
await display.goto(`${base}${url}`)
await display.waitForTimeout(4000)
await display.screenshot({ path: path.join(out, 'board-kiosk.png'), fullPage: false })
await context.request.delete(`${base}/api/v1/kiosk-tokens/${id}`, { headers: { 'X-Nexdeck-Request': '1' } })

await browser.close()
console.log('screenshots written to', out)
