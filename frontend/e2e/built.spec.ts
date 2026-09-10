/**
 * The arrangement the Docker image ships: one server, built assets, and the
 * real response headers. Nothing was testing it.
 *
 * ⚠️ The Vite dev server sets no Content-Security-Policy. Everything the real
 * policy blocks passes in front of it and fails behind it, silently, because a
 * blocked resource is not a failed request: the browser refuses it and the
 * page carries on. Nexview 0.31.0 went out with Web Push dead for exactly that
 * reason, and every test was green.
 *
 * So this file asserts on the headers themselves and on what the browser did
 * with them, not on the app's behaviour, which the other spec covers.
 */
import { expect, test } from '@playwright/test'

// Only the port. The config clears the data directories when it loads, but
// only in the main process, and a spec runs in a worker.
import { FRONTEND_PORT } from '../playwright.config'

const ACCOUNT = { username: 'built-admin', password: 'A-long-enough-password-1' }

type Violation = { directive: string; blocked: string }

declare global {
  interface Window {
    nexdeckViolations?: Violation[]
  }
}

/** Collect every refusal the policy makes, from the first byte of the page. */
async function watchForRefusals(page: import('@playwright/test').Page): Promise<void> {
  await page.addInitScript(() => {
    const collected: Violation[] = []
    window.nexdeckViolations = collected
    document.addEventListener('securitypolicyviolation', (event) => {
      collected.push({ directive: event.effectiveDirective, blocked: event.blockedURI })
    })
  })
}

async function refusals(page: import('@playwright/test').Page): Promise<Violation[]> {
  return page.evaluate(() => window.nexdeckViolations ?? [])
}

test.describe.configure({ mode: 'serial' })

test('the page comes with its policy, and the policy refuses nothing it ships', async ({ page }) => {
  await watchForRefusals(page)
  const answer = await page.goto('/')
  expect(answer, 'the built frontend did not answer; is dist/ built?').not.toBeNull()
  expect(answer?.status()).toBe(200)

  const headers = answer?.headers() ?? {}
  const policy = headers['content-security-policy'] ?? ''
  expect(policy, 'the document came without a Content-Security-Policy').not.toBe('')
  expect(headers['x-content-type-options']).toBe('nosniff')
  expect(headers['x-frame-options']).toBe('SAMEORIGIN')

  // The four the app cannot live without. A policy that names none of them
  // falls back to default-src, and the service worker, the manifest and the
  // video blob are the three things that go quietly dead when it does.
  expect(policy).toContain("worker-src 'self'")
  expect(policy).toContain("manifest-src 'self'")
  expect(policy).toContain('blob:')
  expect(policy).toContain("script-src 'self'")
  // It is the page policy, not the sandboxed one the API gets.
  expect(policy).not.toContain('sandbox')

  await page.waitForLoadState('networkidle')
  expect(await refusals(page), 'the policy refused something the page itself ships').toEqual([])
})

test('the service worker is allowed to install, which is what 0.31.0 was not', async ({ page }) => {
  await watchForRefusals(page)
  await page.goto('/')
  // The app registers it itself; waiting on the registration is waiting on
  // the whole chain: worker-src, the script's content type, and the scope.
  const state = await page.evaluate(async () => {
    const registration = await navigator.serviceWorker.getRegistration('/')
    const ready = await Promise.race([
      navigator.serviceWorker.ready,
      new Promise<null>((resolve) => setTimeout(() => resolve(null), 20_000)),
    ])
    return {
      registered: registration !== undefined,
      active: ready !== null,
      script: ready?.active?.scriptURL ?? '',
    }
  })
  expect(state.registered, 'the app did not register its service worker at all').toBe(true)
  expect(state.active, 'the service worker never became active').toBe(true)
  expect(state.script).toContain('/sw.js')
  expect(await refusals(page)).toEqual([])

  // And the worker file is served as a script, which nosniff makes binding.
  const worker = await page.request.get('/sw.js')
  expect(worker.status()).toBe(200)
  expect(worker.headers()['content-type']).toContain('javascript')
  expect(worker.headers()['x-content-type-options']).toBe('nosniff')
})

test('a picture from another address still loads once the service worker is in charge', async ({ page }) => {
  // ⚠️ Nexview's covers broke in 0.6.0, and only on a page the worker
  // controls. Measured against the built image: the same TMDB poster loaded
  // with the worker blocked (500 px) and failed with it active (0 px). The
  // worker answered every request that was not /api/ by fetching it itself,
  // foreign pictures included, and that fetch failed where the page's own
  // <img> would have been allowed. It went unnoticed because Nexview was the
  // first adapter to hand the browser a picture from somewhere else; every
  // other one goes through nexdeck's own image proxy.
  //
  // The foreign address here is the dev server of this very run: another
  // port is another origin, it serves /icon-192.png from public/, and it
  // keeps the test off the internet.
  await page.goto('/')
  await page.evaluate(async () => {
    await Promise.race([navigator.serviceWorker.ready, new Promise((resolve) => setTimeout(resolve, 20_000))])
  })
  // A worker takes over the pages opened after it became active.
  await page.reload()
  const controlled = await page.evaluate(() => Boolean(navigator.serviceWorker.controller))
  expect(controlled, 'the service worker never took charge of the page, so this test proves nothing').toBe(true)

  const width = await page.evaluate(async (source) => {
    const picture = new Image()
    await new Promise((resolve) => {
      picture.onload = resolve
      picture.onerror = resolve
      setTimeout(resolve, 10_000)
      picture.src = `${source}?at=${Date.now()}`
    })
    return picture.naturalWidth
  }, `http://127.0.0.1:${FRONTEND_PORT}/icon-192.png`)
  expect(width, 'a picture from another address did not load on a page the service worker controls').toBeGreaterThan(0)
})

test('the manifest and its icons are served, so the app can be installed', async ({ page }) => {
  const manifest = await page.request.get('/manifest.webmanifest')
  expect(manifest.status()).toBe(200)
  const described = (await manifest.json()) as { icons: { src: string }[]; start_url: string }
  expect(described.start_url).toBe('/')
  expect(described.icons.length).toBeGreaterThan(0)
  for (const icon of described.icons) {
    const fetched = await page.request.get(icon.src)
    expect(fetched.status(), `${icon.src} is named in the manifest and not served`).toBe(200)
  }
})

test('an address under /api/ that does not exist answers JSON, not the app', async ({ page }) => {
  // ⚠️ The catch-all route that serves the app matched /api/ too, so a
  // withdrawn address answered 200 with the whole dashboard page. Only this
  // arrangement can show it: in front of the Vite server the proxy decides.
  const answer = await page.request.get('/api/v1/there-is-no-such-thing')
  expect(answer.status()).toBe(404)
  expect(answer.headers()['content-type']).toContain('json')
  expect((await answer.json()).code).toBe('not_found')

  const post = await page.request.post('/api/v1/there-is-no-such-thing', { data: {} })
  expect(post.status(), 'GET and POST disagree about whether the address exists').toBeGreaterThanOrEqual(400)
})

test('the whole first start works behind the real headers', async ({ page }) => {
  await watchForRefusals(page)
  await page.goto('/')
  await expect(page).toHaveURL(/\/setup$/)

  await page.getByLabel('User name').fill(ACCOUNT.username)
  await page.getByLabel('Password', { exact: true }).fill(ACCOUNT.password)
  await page.getByLabel('Confirm password').fill(ACCOUNT.password)
  await page.getByRole('button', { name: 'Next' }).click()
  await page.getByRole('button', { name: 'Next' }).click()
  await page.getByRole('button', { name: 'Finish' }).click()

  await expect(page).toHaveURL(/\/b\/home/)
  const containers = page.locator('section[aria-label="Containers"]')
  await expect(containers).toBeVisible()
  // Live data over the stream: connect-src has to allow the same origin.
  await expect(containers.getByText('jellyfin')).toBeVisible({ timeout: 20_000 })

  expect(await refusals(page), 'the policy refused something on the way through setup').toEqual([])
})
