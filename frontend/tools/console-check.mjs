/* Opens a running instance in a real browser and reports what the console says.
 *
 *   node tools/console-check.mjs http://localhost:8005 admin password
 *
 * Meant for the built frontend served by FastAPI: content security policy,
 * service worker registration and the live stream are only provable there.
 */
import { chromium } from '@playwright/test'

const [base = 'http://localhost:8005', username = 'admin', password = ''] = process.argv.slice(2)
const browser = await chromium.launch()
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'en-US' })
const errors = []
const failed = []
const page = await context.newPage()
page.on('console', (message) => {
  if (message.type() === 'error' || message.type() === 'warning') errors.push(`${message.type()}: ${message.text()}`)
})
page.on('requestfailed', (request) => failed.push(`${request.method()} ${request.url()} ${request.failure()?.errorText ?? ''}`))
page.on('response', (response) => {
  if (response.status() >= 400 && !response.url().includes('/api/v1/auth/me')) failed.push(`${response.status()} ${response.url()}`)
})

const login = await context.request.post(`${base}/api/v1/auth/login`, { data: { username, password } })
console.log('login', login.status())
await page.goto(`${base}/b/home`)
await page.waitForTimeout(7000)
const cards = await page.locator('section[aria-label]').count()
const dashes = await page.locator('section[aria-label] .num', { hasText: '—' }).count()
const registration = await page.evaluate(async () => {
  const reg = await navigator.serviceWorker?.getRegistration()
  return reg ? (reg.active ? 'active' : reg.installing ? 'installing' : 'registered') : 'none'
})
const csp = (await page.request.get(`${base}/b/home`)).headers()['content-security-policy']
console.log(JSON.stringify({ cards, emptyValues: dashes, serviceWorker: registration, csp: Boolean(csp) }, null, 2))
console.log('console errors/warnings:', errors.length ? errors : 'none')
console.log('failed requests:', failed.length ? failed : 'none')
await browser.close()
process.exit(errors.length || failed.length ? 1 : 0)
