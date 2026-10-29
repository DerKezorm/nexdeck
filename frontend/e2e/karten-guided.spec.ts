/**
 * The guided way of the card editor against a real server: a stand-in Home Assistant answers `/api/states`, the
 * server probes it, previews the card from it, saves it and puts it on a board. The first way of the accepted
 * mock-up, "Lights on", from the tile to the board, and the same steps on a phone.
 *
 * ⚠️ The stand-in runs inside this test on a port of its own; it knows one token and invented rooms only.
 */
import { createServer, type Server } from 'node:http'
import type { AddressInfo } from 'node:net'

import { expect, test, type Page } from '@playwright/test'

const ACCOUNT = { username: 'e2e-admin', password: 'A-long-enough-password-1' }
const TOKEN = 'stand-in'
const ROOMS = ['kitchen', 'hall', 'living_room', 'bath', 'office', 'bedroom']
const STATES = ROOMS.flatMap((room, index) => [
  { entity_id: `light.${room}`, state: index % 2 ? 'off' : 'on', attributes: { friendly_name: `Light ${room}` }, last_changed: '2026-10-26T06:00:00+00:00' },
  { entity_id: `sensor.temperature_${room}`, state: String(19 + index), attributes: { friendly_name: `Temperature ${room}` }, last_changed: '2026-10-26T06:00:00+00:00' },
])

let home: Server
let address = ''

test.beforeAll(async () => {
  home = createServer((request, response) => {
    if (request.headers.authorization !== `Bearer ${TOKEN}`) {
      response.writeHead(401).end()
      return
    }
    const body = request.url === '/api/states' ? STATES : request.url === '/api/' ? { message: 'API running.' } : null
    response.writeHead(body ? 200 : 404, { 'content-type': 'application/json' }).end(JSON.stringify(body ?? {}))
  })
  await new Promise<void>((resolve) => home.listen(0, '127.0.0.1', resolve))
  address = `http://127.0.0.1:${(home.address() as AddressInfo).port}`
})

test.afterAll(async () => {
  await new Promise((resolve) => home.close(resolve))
})

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

test('umbau: Home Assistant, devices and sensors counted as "Lights on", saved and put on a board', async ({ page }) => {
  const trouble: string[] = []
  page.on('pageerror', (error) => trouble.push(String(error)))
  await signIn(page)
  // The wizard starts the installation in demo mode, where no card asks a real service; this test needs one that asks.
  const settings = async (demo: boolean) => expect((await page.request.patch('/api/v1/settings', { headers: { 'X-Nexdeck-Request': '1' }, data: { demo } })).ok()).toBe(true)
  await settings(false)
  const added = await page.request.post('/api/v1/integrations', {
    headers: { 'X-Nexdeck-Request': '1' },
    data: { kind: 'homeassistant', name: 'Stand-in home', config: { url: address, token: TOKEN } },
  })
  expect(added.status()).toBe(201)

  await page.goto('/system/custom-cards/new')
  await expect(page.getByRole('heading', { name: 'Which service is the card for?', level: 2 })).toBeVisible()
  // One tile for each kind of service; the connection to try the card with is chosen on the next step.
  await page.getByRole('button', { name: /^Home Assistant/ }).click()
  await expect(page.getByRole('heading', { name: 'What should the card show?', level: 2 })).toBeVisible()
  // The demo's Home Assistant comes first; the answers have to come from the stand-in.
  await page.getByLabel('Trying it out with').selectOption({ label: 'Stand-in home' })
  await page.getByRole('button', { name: /^Devices and sensors/ }).click()
  const table = page.getByTestId('card-answer-table')
  await expect(table).toContainText('12 entries')
  await expect(table.getByRole('columnheader', { name: 'attributes.friendly_name' })).toBeVisible()

  await page.getByRole('button', { name: 'Next' }).click()
  await expect(page.getByRole('button', { name: /^A number/ })).toHaveAttribute('aria-pressed', 'true')
  // Three of the six lights are on: the server counts, the preview shows it on the card the board draws.
  await expect(page.getByTestId('card-guided-result')).toContainText('Result: 3 of 12 entries')
  const preview = page.getByTestId('card-preview-card')
  await expect(preview).toContainText('3')
  await expect(preview).toContainText('Lights on')
  await page.screenshot({ path: test.info().outputPath('display.png'), fullPage: true })

  await page.getByRole('button', { name: 'Next' }).click()
  await expect(page.getByRole('textbox', { name: 'Name of the card' })).toHaveValue('Lights on')
  await page.getByRole('region', { name: 'Finish' }).getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByText('Saved. Every board shows the new version.')).toBeVisible()
  await expect(page).toHaveURL(/\/system\/custom-cards\/lights-on\/edit$/)
  const saved = page.getByTestId('card-guided-saved')
  await expect(saved).toContainText('Put it on a board right away?')
  await saved.getByRole('button', { name: 'Put on the board' }).click()
  await expect(saved).toContainText('The card is on')
  await saved.getByRole('link', { name: 'Open the board' }).click()
  await expect(page.getByRole('region', { name: 'Lights on' })).toContainText('3')

  // On a phone the steps stand below each other, the table scrolls in its own box, and the page does not.
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/system/custom-cards/lights-on/edit')
  await expect(page.getByRole('heading', { name: 'Lights on', level: 1 })).toBeVisible()
  // The connection is not part of the card: a fresh visit takes the first that fits (the demo's), until one is picked.
  await page.getByRole('button', { name: /^2 Data/ }).click()
  await page.getByLabel('Trying it out with').selectOption({ label: 'Stand-in home' })
  await expect(page.getByTestId('card-answer-table')).toContainText('12 entries')
  await page.getByRole('button', { name: 'Next' }).click()
  await expect(page.getByTestId('card-guided-result')).toContainText('of 12 entries')
  const wide = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(wide).toBeLessThanOrEqual(0)
  await page.screenshot({ path: test.info().outputPath('display-phone.png'), fullPage: true })
  expect(trouble).toEqual([])
  // The specs after this one find the installation as the wizard left it.
  await settings(true)
})
