/**
 * Pflichttests 33 and 34 of the shared sign-in blueprint (copied once from bauplaene/oidc, then nexdeck's file).
 *
 * The provider is the stand-in of `e2e/fake-provider.mjs` (OpenID Connect over http on 8797 with a key made at its
 * start, sending the browser straight back with a code for whoever POST /oidc/next named). Never a real provider,
 * never the network. The administrator is the `e2e-admin` of first-start.spec.ts; whatever this file adds it takes
 * away again, so the specs after it find the installation as before.
 *
 * With E2E_SHOTS naming a folder, a third test takes the pictures of the review (German, light).
 */
import path from 'node:path'

import { expect, test, type Browser, type Page } from '@playwright/test'

const ADMIN = { username: 'e2e-admin', password: 'A-long-enough-password-1' }
const MEMBER = { username: 'ossie', password: 'e2e provider test password' }
const ISSUER = 'http://127.0.0.1:8797/oidc'
const CSRF = { 'X-Nexdeck-Request': '1' }

type Entry = { id: number; slug: string; label: string }

/** Sign in with the password, or make the administrator when this file runs alone on an empty installation. */
async function signIn(page: Page, account: { username: string; password: string }): Promise<void> {
  await page.goto('/login')
  await expect(page.getByLabel('User name')).toBeVisible()
  await page.getByLabel('User name').fill(account.username)
  await page.getByLabel('Password', { exact: true }).fill(account.password)
  const confirm = page.getByLabel('Confirm password')
  if (await confirm.isVisible()) {
    await confirm.fill(account.password)
    await page.getByRole('button', { name: 'Next' }).click()
    await page.getByRole('button', { name: 'Next' }).click()
    await page.getByRole('button', { name: 'Finish' }).click()
  } else {
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  }
  await page.waitForURL((url) => !url.pathname.startsWith('/login') && !url.pathname.startsWith('/setup'))
}

async function entries(page: Page): Promise<Entry[]> {
  return (await (await page.request.get('/api/v1/oidc/admin/providers')).json()) as Entry[]
}

async function removeEntry(page: Page, slug: string): Promise<void> {
  for (const entry of await entries(page)) {
    if (entry.slug === slug) await page.request.delete(`/api/v1/oidc/admin/providers/${entry.id}`, { headers: CSRF })
  }
}

async function removeAccount(page: Page, username: string): Promise<void> {
  const users = (await (await page.request.get('/api/v1/users')).json()) as { id: number; username: string }[]
  for (const user of users) {
    if (user.username === username) await page.request.delete(`/api/v1/users/${user.id}`, { headers: CSRF })
  }
}

async function addEntry(page: Page, slug: string, label: string): Promise<void> {
  await removeEntry(page, slug)
  const made = await page.request.post('/api/v1/oidc/admin/providers', {
    data: { label, slug, issuer: ISSUER, client_id: 'e2e-client', client_secret: `e2e-${Date.now()}` },
    headers: CSRF,
  })
  expect(made.ok(), await made.text()).toBe(true)
}

/**
 * The public address of the run: the sign-in sends the provider back there. Without it nexdeck would take the
 * address of the request, and behind the Vite server of this run that is the backend's own port, which the browser
 * never opened. Clearing it afterwards asks (a provider may still be listed), so it is confirmed.
 */
async function setAddress(page: Page, address: string): Promise<void> {
  const done = await page.request.patch('/api/v1/settings', { data: { public_url: address, confirm_address: true }, headers: CSRF })
  expect(done.ok(), await done.text()).toBe(true)
}

async function nextPerson(claims: Record<string, string>): Promise<void> {
  await fetch(`${ISSUER}/next`, { method: 'POST', body: JSON.stringify(claims) })
}

function collectProblems(page: Page): string[] {
  const problems: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error' && !/status of 4(01|03|04|09|22)/.test(message.text())) problems.push(message.text())
  })
  page.on('pageerror', (error) => problems.push(error.message))
  return problems
}

async function fresh(browser: Browser): Promise<Page> {
  const context = await browser.newContext({ storageState: { cookies: [], origins: [] } })
  return context.newPage()
}

/** A member linked to the stand-in's person through the profile page, the way a person does it. */
async function linkedMember(page: Page, browser: Browser, slug: string, label: string, subject: string): Promise<void> {
  await removeAccount(page, MEMBER.username)
  const made = await page.request.post('/api/v1/users', { data: { ...MEMBER, role: 'user' }, headers: CSRF })
  expect(made.ok(), await made.text()).toBe(true)
  await nextPerson({ sub: subject, preferred_username: 'someone-else' })
  const member = await fresh(browser)
  await signIn(member, MEMBER)
  await member.goto('/settings')
  const row = member.getByTestId('account-providers').locator('li').filter({ has: member.getByText(label, { exact: true }) })
  await expect(row).toContainText('Not linked')
  await row.getByRole('button', { name: 'Link' }).click()
  const dialog = member.getByRole('dialog')
  await dialog.getByLabel('Your password').fill(MEMBER.password)
  await dialog.getByRole('button', { name: 'Link' }).click()
  await expect(member).toHaveURL(/\/settings/)
  await expect(row).toContainText('Linked')
  await member.context().close()
  void slug
}

test('33: sign-in through the provider button ends in a session', async ({ page, browser, baseURL }) => {
  await signIn(page, ADMIN)
  await setAddress(page, baseURL!)
  try {
    await addEntry(page, 'standin33', 'Stand-in 33')
    await linkedMember(page, browser, 'standin33', 'Stand-in 33', 'ossie-33')
    await signInThroughTheButton(browser)
  } finally {
    await removeEntry(page, 'standin33')
    await removeAccount(page, MEMBER.username)
    await setAddress(page, '')
  }
})

async function signInThroughTheButton(browser: Browser): Promise<void> {
  // A browser without a session: the button on the sign-in page, and in.
  const visitor = await fresh(browser)
  const problems = collectProblems(visitor)
  await visitor.goto('/login')
  await expect(visitor.getByText('or', { exact: true })).toBeVisible()
  await visitor.getByRole('link', { name: 'Sign in with Stand-in 33' }).click()
  await visitor.waitForURL((url) => !url.pathname.startsWith('/login') && !url.pathname.startsWith('/api/'))
  await expect(visitor).not.toHaveURL(/error=/)
  expect((await (await visitor.request.get('/api/v1/auth/me')).json()).username).toBe(MEMBER.username)
  expect(problems).toEqual([])
  await visitor.context().close()

  // A stranger at the provider comes in with nothing: the sign-in page says why, in words.
  await nextPerson({ sub: 'stranger-33', email: 'ossie@example.com', email_verified: 'true' })
  const stranger = await fresh(browser)
  await stranger.goto('/login')
  await stranger.getByRole('link', { name: 'Sign in with Stand-in 33' }).click()
  await expect(stranger).toHaveURL(/\/login\?error=oidc_no_account/)
  await expect(stranger.getByText('There is no account for you here.')).toBeVisible()
  await stranger.context().close()
}

test('34: add, edit and remove a provider; the authentik card lists its steps', async ({ page }) => {
  const problems = collectProblems(page)
  await signIn(page, ADMIN)
  await removeEntry(page, 'stand-in')
  await page.goto('/system/sign-in')
  await expect(page.getByRole('heading', { name: 'Sign-in', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Sign-in providers' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'authentik in one step' })).toBeVisible()
  await page.getByRole('button', { name: 'Add a provider' }).click()
  const form = page.getByTestId('provider-form')
  await form.getByLabel('Name on the button').fill('Stand-in')
  // The short name follows the name; the redirect address follows the short name.
  await expect(form.getByLabel('Short name')).toHaveValue('stand-in')
  await expect(form.getByTestId('provider-redirect')).toContainText('/api/v1/oidc/stand-in/callback')
  await form.getByLabel('Issuer').fill(ISSUER)
  await form.getByLabel('Client ID').fill('e2e-client')
  await form.getByLabel('Client secret').fill(`e2e-${Date.now()}`)
  await page.getByRole('dialog').getByRole('button', { name: 'Save' }).click()
  const list = page.getByTestId('provider-list')
  await expect(list).toContainText('Stand-in')
  await expect(list).toContainText('on')
  const row = (name: string) => list.locator('li').filter({ has: page.getByText(name, { exact: true }) })
  await row('Stand-in').getByRole('button', { name: 'Edit' }).click()
  await page.getByTestId('provider-form').getByLabel('Name on the button').fill('Stand-in 2')
  await page.getByRole('dialog').getByRole('button', { name: 'Save' }).click()
  await expect(list).toContainText('Stand-in 2')
  await row('Stand-in 2').getByRole('button', { name: 'Remove' }).click()
  await expect(page.getByRole('dialog')).toContainText('0 accounts lose the link')
  await page.getByRole('dialog').getByRole('button', { name: 'Remove' }).click()
  await expect(page.getByText('Stand-in 2')).toHaveCount(0)
  await expect(page.getByText('No provider yet.')).toBeVisible()

  // The authentik card: an address nobody answers at gives the step list with the first step failed. Without a
  // public address the card suggests the browser's own and the button reads "Use it and set up".
  await page.getByLabel('Address of authentik').fill('http://127.0.0.1:9')
  await page.getByLabel('API token').fill(`e2e-${Date.now()}`)
  await page.getByRole('button', { name: /^Set up$|^Use it and set up$/ }).click()
  await expect(page.getByText('Connection to authentik')).toBeVisible()
  await expect(page.getByText(/cannot be reached at this address/)).toBeVisible()
  expect(problems).toEqual([])
  // The card stored the suggestion as the public address; the specs after this one find none, as before.
  const cleared = await page.request.patch('/api/v1/settings', { data: { public_url: '', confirm_address: true }, headers: CSRF })
  expect(cleared.ok(), await cleared.text()).toBe(true)
})

test('pictures for the review: German, light', async ({ page, browser, baseURL }) => {
  test.skip(!process.env.E2E_SHOTS, 'only when E2E_SHOTS names a folder')
  const folder = process.env.E2E_SHOTS!
  const shot = (target: Page, name: string) => target.screenshot({ path: path.join(folder, `${name}.png`), fullPage: true })
  await signIn(page, ADMIN)
  await page.request.patch('/api/v1/auth/me', { data: { locale: 'de', theme: 'light' }, headers: CSRF })
  await setAddress(page, baseURL!)
  await addEntry(page, 'standin', 'Stand-in')
  await linkedMember(page, browser, 'standin', 'Stand-in', 'ossie-shots')
  await page.goto('/system/sign-in')
  await expect(page.getByRole('heading', { name: 'Anmeldeanbieter' })).toBeVisible()
  await shot(page, 'karten-de-hell')
  await page.getByTestId('provider-list').getByRole('button', { name: 'Bearbeiten' }).first().click()
  await shot(page, 'formular-de-hell')
  await page.keyboard.press('Escape')
  await page.getByLabel('Adresse von authentik').fill('http://127.0.0.1:9')
  await page.getByLabel('API-Token').fill(`e2e-${Date.now()}`)
  await page.getByRole('button', { name: /^Einrichten$|^Übernehmen und einrichten$/ }).click()
  await expect(page.getByText('Verbindung zu authentik')).toBeVisible()
  await shot(page, 'authentik-schritte-de-hell')
  await page.goto('/system/users')
  await expect(page.getByTestId('account-providers').first()).toBeVisible()
  await shot(page, 'konten-de-hell')
  const visitor = await browser.newPage({ locale: 'de-DE', colorScheme: 'light' })
  await visitor.goto('/login')
  await expect(visitor.getByRole('link', { name: 'Mit Stand-in anmelden' })).toBeVisible()
  await shot(visitor, 'anmeldung-de-hell')
  await visitor.close()
  const member = await fresh(browser)
  await signIn(member, MEMBER)
  await member.request.patch('/api/v1/auth/me', { data: { locale: 'de', theme: 'light' }, headers: CSRF })
  await member.goto('/settings')
  await expect(member.getByTestId('account-providers')).toBeVisible()
  await shot(member, 'konto-de-hell')
  await member.context().close()
  await removeEntry(page, 'standin')
  await removeAccount(page, MEMBER.username)
  await page.request.patch('/api/v1/settings', { data: { public_url: '', confirm_address: true }, headers: CSRF })
  await page.request.patch('/api/v1/auth/me', { data: { locale: 'en', theme: 'dark' }, headers: CSRF })
})
