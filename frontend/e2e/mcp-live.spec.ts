/**
 * The way a program takes: a key made on its own settings page, a press asked for over HTTP (``POST /api/mcp``), the
 * question in the bell, which counts it on that settings page without a reload, and the answer there.
 *
 * Named to sort after `first-start.spec.ts`, which needs the empty installation. Whatever this file switches on it
 * switches off again, so the specs after it find MCP off, as it is by default.
 */
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

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
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  }
  await expect(page).toHaveURL(/\/b\//)
}

interface Offered {
  card: number
  action: string
  label: string
  params: Record<string, unknown>
}

/** A button some card of the demo boards offers right now: the press needs one the card really shows. */
async function offered(request: APIRequestContext): Promise<Offered | null> {
  const boards = (await (await request.get('/api/v1/boards')).json()) as { slug: string }[]
  for (const { slug } of boards) {
    const board = (await (await request.get(`/api/v1/boards/${slug}`)).json()) as { live?: Record<string, { actions?: { id: string; label: string; params?: Record<string, unknown>; danger?: boolean }[] }> }
    for (const [card, data] of Object.entries(board.live ?? {})) {
      const action = (data.actions ?? []).find((one) => !one.danger)
      if (action) return { card: Number(card), action: action.id, label: action.label, params: action.params ?? {} }
    }
  }
  return null
}

test('a key from its own settings page, a press over HTTP, the bell counting it there, the answer in the bell', async ({ page, request }) => {
  const trouble: string[] = []
  page.on('pageerror', (error) => trouble.push(String(error)))
  await signIn(page)
  const made = await page.request.post('/api/v1/integrations', { data: { kind: 'portainer', name: 'Portainer for MCP', config: {}, demo: true }, headers: CSRF })
  expect(made.status()).toBe(201)
  const press = await offered(page.request)
  expect(press, 'a demo card that offers a button').not.toBeNull()

  // The administrator switches MCP on (it is off by default) ...
  const on = await page.request.put('/api/v1/mcp/admin', { data: { allowed: true, max_level: 'act', oauth_allowed: false, blocked_tools: [] }, headers: CSRF })
  expect(on.status()).toBe(200)

  // ... and the key is made on its own page, which the API tokens point to: level "Read and act", shown once.
  await page.goto('/settings/tokens')
  await page.getByTestId('mcp-hint').getByRole('link', { name: 'AI from outside (MCP)' }).click()
  await expect(page).toHaveURL(/\/settings\/mcp$/)
  await expect(page.getByRole('heading', { name: 'AI from outside (MCP)' })).toBeVisible()
  // The old address leads there too.
  await page.goto('/settings/tokens#mcp')
  await expect(page).toHaveURL(/\/settings\/mcp$/)
  await page.getByLabel('Name of the key').fill('E2E script')
  await page.getByLabel('Level').selectOption('act')
  await page.getByRole('button', { name: 'Create key' }).click()
  const token = (await page.getByTestId('mcp-token').textContent())?.trim() ?? ''
  expect(token).toMatch(/^ndm_[A-Za-z0-9_-]{43}$/)
  await expect(page.getByTestId('mcp-command')).toContainText(`--header "Authorization: Bearer ${token}"`)
  await page.getByRole('button', { name: 'I have copied it' }).click()
  await expect(page.getByTestId('mcp-token')).toHaveCount(0)

  // A program that holds only the key (no session cookie: this context is not the page's) asks for the press.
  const call = async (name: string, args: Record<string, unknown>) => {
    const answer = await request.post('/api/mcp', {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream' },
      data: { jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name, arguments: args } },
    })
    expect(answer.status()).toBe(200)
    const body = (await answer.json()) as { result: { content: { text: string }[]; isError?: boolean } }
    return { error: body.result.isError ?? false, text: body.result.content.map((part) => part.text).join('\n') }
  }
  // The bell on this settings page, which follows no board, counts the question as it comes, without a reload.
  const bell = page.getByRole('button', { name: 'Notices' })
  const counted = async () => Number((await bell.textContent())?.replace(/\D/g, '') || 0)
  const before = await counted()
  const asked = await call('press_button', { card_id: press!.card, action: press!.action, params: press!.params })
  expect(asked.error).toBe(false)
  expect(asked.text).toContain('waiting')
  await expect.poll(counted).toBe(before + 1)
  await expect(page).toHaveURL(/\/settings\/mcp$/)

  // The question is in the bell, with the buttons right there.
  await bell.click()
  const sheet = page.getByRole('dialog')
  await expect(sheet.getByText(/asks to press/)).toBeVisible()
  await sheet.getByRole('button', { name: 'Allow' }).click()
  await expect(sheet.getByTestId(/^mcp-notice-/)).toContainText('Allowed')
  await expect(sheet.getByRole('button', { name: 'Allow' })).toHaveCount(0)
  // The result comes into the open bell, with the button's name and the program, not the action id.
  await expect(sheet.getByText(/ on .+, by E2E script \(MCP\), approved by /)).toBeVisible()

  // What the server holds: allowed, and the program learns it too.
  const listed = (await (await page.request.get('/api/v1/mcp/requests?status=approved')).json()) as { id: number; label: string }[]
  expect(listed.length).toBeGreaterThan(0)
  const done = await call('request_status', { request: listed[0].id })
  expect(done.text).toContain('approved')

  // Clean up: the key goes, MCP is off again.
  const keys = (await (await page.request.get('/api/v1/mcp/keys')).json()) as { id: number }[]
  for (const row of keys) expect((await page.request.delete(`/api/v1/mcp/keys/${row.id}`, { headers: CSRF })).status()).toBe(204)
  await page.request.put('/api/v1/mcp/admin', { data: { allowed: false, max_level: 'act', oauth_allowed: false, blocked_tools: [] }, headers: CSRF })
  expect(trouble, `the browser reported: ${trouble.join(' | ')}`).toEqual([])
})
