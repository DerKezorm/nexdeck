/**
 * 1984 has to look the same after it became a skin as it did as the card
 * style `window`.
 *
 * Not by screenshots: the demo board has clocks and live values, and no two
 * runs draw it alike. What 1984 changes is the computed style of a dozen
 * parts, and that is deterministic. So the styles of those parts, in four
 * combinations of its choices, dark and light, on a board, in a dialog, on a
 * settings page and on the sign-in page, were recorded on the last commit
 * before the frontend knew skins (`SKIN_BASELINE=write`), and every run since
 * compares against that record.
 */
import { readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect, test, type Page } from '@playwright/test'

const ACCOUNT = { username: 'e2e-admin', password: 'A-long-enough-password-1' }
const CSRF = { 'X-Nexdeck-Request': '1' }
const RECORD = path.join(path.dirname(fileURLToPath(import.meta.url)), 'fixtures', 'skin-1984-styles.json')

const COMBINATIONS: Record<string, string>[] = [
  { status: 'symbol', icons: 'colour', desk: 'dither', type: 'titles' },
  { status: 'pattern', icons: 'mono', desk: 'weave', type: 'titles' },
  { status: 'tint', icons: 'colour', desk: 'grey', type: 'all' },
  { status: 'symbol', icons: 'mono', desk: 'dither', type: 'all' },
]

const PROPERTIES = [
  'background-color', 'background-image', 'background-size', 'color', 'font-family', 'font-size',
  'border-top-width', 'border-top-style', 'border-top-color', 'border-radius', 'box-shadow', 'backdrop-filter', 'filter',
]

const BOARD_PARTS: Record<string, string> = {
  desk: '[data-background]',
  appBar: 'header.app-bar',
  card: '.card.glass:not(.card-plain)',
  titlebar: '.card.glass:not(.card-plain) > header',
  title: '.card.glass:not(.card-plain) > header > h3',
  dot: '.card.glass:not(.card-plain) > header > .dot',
  button: 'header.app-bar .btn',
}
const DIALOG_PARTS: Record<string, string> = { dialog: '.overlay > .glass-strong', input: '.overlay input' }
const PAGE_PARTS: Record<string, string> = { window: 'main[data-shell]', nav: 'main[data-shell] nav a', panel: 'main[data-shell] .glass.p-5' }
const SIGN_IN_PARTS: Record<string, string> = { window: '.glass.p-6', input: 'input', button: 'button[type=submit]' }

type Styles = Record<string, Record<string, string> | null>

async function sample(page: Page, parts: Record<string, string>): Promise<Styles> {
  return page.evaluate(
    ({ parts, properties }) => {
      const out: Record<string, Record<string, string> | null> = {}
      for (const [name, selector] of Object.entries(parts)) {
        const element = document.querySelector(selector)
        if (!element) {
          out[name] = null
          continue
        }
        const style = getComputedStyle(element)
        out[name] = Object.fromEntries(properties.map((property) => [property, style.getPropertyValue(property)]))
      }
      return out
    },
    { parts, properties: PROPERTIES },
  )
}

async function signIn(page: Page): Promise<void> {
  await page.goto('/')
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

/** Until 1984's own sheet has arrived: it is fetched the first time the style is shown. */
async function windowDrawn(page: Page): Promise<void> {
  await expect(page.locator('html')).toHaveAttribute('data-cards', 'window')
  const sheetIn = () =>
    page.evaluate(() =>
      [...document.styleSheets].some((sheet) => {
        try {
          return [...sheet.cssRules].some((rule) => rule.cssText.includes('data-cards="window"'))
        } catch {
          return false
        }
      }),
    )
  await expect.poll(sheetIn, { timeout: 15_000 }).toBe(true)
  await page.evaluate(() => document.fonts.ready)
  await page.mouse.move(0, 0)
}

test('1984 draws every part as it did before it was a skin', async ({ page, browser }) => {
  test.setTimeout(240_000)
  await signIn(page)
  const look = await (await page.request.get('/api/v1/settings/appearance')).json()
  const theme = Object.values(look.themes as Record<string, { name: string }>).find((each) => each.name === '1984')
  expect(theme).toBeTruthy()
  const seen: Record<string, Styles> = {}
  try {
    for (const retro of COMBINATIONS) {
      const saved = await page.request.put('/api/v1/settings/appearance', {
        headers: CSRF,
        data: { preset: 'cyan', accent: '', css: '', theme, card_style: 'window', retro, radius: 0, gap: 14, font: 'inter', refraction: true },
      })
      expect(saved.ok()).toBeTruthy()
      for (const mode of ['dark', 'light']) {
        expect((await page.request.patch('/api/v1/auth/me', { headers: CSRF, data: { theme: mode } })).ok()).toBeTruthy()
        const name = `${Object.values(retro).join('-')}-${mode}`
        await page.goto('/')
        await windowDrawn(page)
        await expect(page.locator('.card.glass:not(.card-plain)').first()).toBeVisible()
        seen[`${name} board`] = await sample(page, BOARD_PARTS)
        await page.keyboard.press('Control+k')
        await expect(page.locator('.overlay')).toBeVisible()
        seen[`${name} dialog`] = await sample(page, DIALOG_PARTS)
        await page.keyboard.press('Escape')
        await page.goto('/settings')
        await windowDrawn(page)
        await expect(page.locator('main[data-shell]')).toBeVisible()
        seen[`${name} settings`] = await sample(page, PAGE_PARTS)
      }
    }
    const stranger = await browser.newPage()
    await stranger.goto('/')
    await windowDrawn(stranger)
    await expect(stranger.getByLabel('User name')).toBeVisible()
    seen['sign-in'] = await sample(stranger, SIGN_IN_PARTS)
    await stranger.close()
  } finally {
    // Every spec after this one expects nexdeck's own look and a dark page.
    await page.request.put('/api/v1/settings/appearance', { headers: CSRF, data: { preset: 'cyan', accent: '', css: '', theme: null, card_style: 'glass', skin: {} } })
    await page.request.patch('/api/v1/auth/me', { headers: CSRF, data: { theme: 'dark' } })
  }
  if (process.env.SKIN_BASELINE === 'write') {
    writeFileSync(RECORD, JSON.stringify(seen, null, 2) + '\n')
    return
  }
  const recorded = JSON.parse(readFileSync(RECORD, 'utf-8')) as Record<string, Styles>
  for (const [view, parts] of Object.entries(recorded)) {
    expect(seen[view], view).toEqual(parts)
  }
})
