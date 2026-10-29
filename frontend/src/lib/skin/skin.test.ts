/**
 * Skins in the page: whose skin is worn, the look it makes, the marks its sheet
 * answers to, the pages it never reaches, and the parts it names, which must
 * still be in the code (backend/app/skins/parts.json is the one list).
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'

import { applyAppearance, type Appearance } from '../appearance'
import { GUARDED, guarded } from './guard'
import { chosenSkin, NATIVE_1984, wear, type CompiledSkin } from './wear'

const BASE: Appearance = { preset: 'cyan', accent: '#22d3ee', css: '', colour: '#22d3ee', card_style: 'flat', radius: 16, gap: 12, font: 'inter', theme: null }

const COMPILED: CompiledSkin = {
  key: 'console',
  css: ":root[data-skin='console'] .btn { color: red }",
  native: null,
  options: [{ key: 'desk', label: 'Desk', default: 'bricks', choices: [{ key: 'bricks', label: 'Bricks' }, { key: 'plain', label: 'Plain' }] }],
  tokens: { radius: 10, font: 'pixel', dark: { bg: '#000000' } },
  fonts: ['pixel'],
  sounds: {},
  presses: [],
}

afterEach(() => {
  applyAppearance(null)
  document.documentElement.removeAttribute('data-skin-guard')
})

describe('whose skin', () => {
  it('is the account’s own when it chose one, else the installation’s with the account’s sounds', () => {
    expect(chosenSkin({ key: 'mine' }, { key: 'theirs' }).key).toBe('mine')
    expect(chosenSkin({ sounds: true }, { key: 'theirs' })).toEqual({ key: 'theirs', sounds: true })
    expect(chosenSkin({}, {})).toEqual({})
  })
})

describe('the look a skin makes', () => {
  it('1984 is the card style window with its choices, as it was before skins', () => {
    const worn = wear(BASE, { key: NATIVE_1984, options: { desk: 'weave' } }, null)
    expect(worn.card_style).toBe('window')
    expect(worn.retro?.desk).toBe('weave')
    expect(worn.skin_key).toBeUndefined()
  })

  it('another skin lays its first layer over the installation’s look and brings its sheet', () => {
    const worn = wear(BASE, { key: 'console', options: { desk: 'plain' } }, COMPILED)
    expect(worn).toMatchObject({ radius: 10, font: 'pixel', gap: 12, card_style: 'flat', skin_key: 'console', skin_options: { desk: 'plain' } })
    expect(worn.theme).toEqual({ name: 'console', dark: { bg: '#000000' }, light: undefined })
    // A palette of its own brings the accent of its own: the installation's would not fit.
    expect(worn.accent).toBe('')
    expect(wear(BASE, { key: 'console' }, COMPILED).skin_options).toEqual({ desk: 'bricks' })
  })

  it('takes the window away when any other skin is worn, or none could be had', () => {
    const window = { ...BASE, card_style: 'window' as const }
    expect(wear(window, { key: 'console' }, COMPILED).card_style).toBe('glass')
    expect(wear(window, { key: 'gone' }, null)).toMatchObject({ card_style: 'glass', skin_key: undefined, skin_css: '' })
  })
})

describe('the marks in the page', () => {
  it('sets the skin and each option on the root and puts its sheet before the operator’s own', () => {
    applyAppearance({ ...wear(BASE, { key: 'console' }, COMPILED), css: '.x { color: blue }' })
    const root = document.documentElement
    expect(root.getAttribute('data-skin')).toBe('console')
    expect(root.getAttribute('data-skin-o-desk')).toBe('bricks')
    const skin = document.getElementById('nexdeck-skin')
    expect(skin?.textContent).toContain(".btn { color: red }")
    expect(skin?.nextElementSibling?.id).toBe('nexdeck-appearance')
  })

  it('takes every mark and the sheet away again', () => {
    applyAppearance(wear(BASE, { key: 'console' }, COMPILED))
    applyAppearance(wear(BASE, {}, null))
    const root = document.documentElement
    expect(root.hasAttribute('data-skin')).toBe(false)
    expect(root.getAttributeNames().filter((name) => name.startsWith('data-skin-o-'))).toEqual([])
    expect(document.getElementById('nexdeck-skin')).toBeNull()
  })

  it('keeps the sheet for the next start, so the skin does not arrive a moment late', () => {
    applyAppearance(wear(BASE, { key: 'console' }, COMPILED))
    expect(JSON.parse(localStorage.getItem('nexdeck.look') ?? '{}').skin_css).toBe(COMPILED.css)
  })
})

describe('where no skin reaches', () => {
  it.each(['/login', '/setup', '/reset/abc', '/connect', '/mcp/requests/4', '/settings', '/settings/tokens', '/settings/mcp', '/system/users', '/system/sign-in', '/system/integrations', '/system/mail', '/system/assistant', '/system/backups', '/system/appearance', '/system/mcp'])(
    '%s is guarded',
    (path) => expect(guarded(path)).toBe(true),
  )

  it.each(['/b/home', '/b/home/network', '/settings/boards', '/system/about', '/notices', '/settings/tokensx'])('%s wears the skin', (path) => expect(guarded(path)).toBe(false))

  it('every pattern is anchored, so it guards a page and not a word inside another address', () => {
    for (const pattern of GUARDED) expect(pattern.source.startsWith('^')).toBe(true)
  })
})

describe('the parts a skin names', () => {
  const registry = JSON.parse(readFileSync(join(process.cwd(), '..', 'backend', 'app', 'skins', 'parts.json'), 'utf8')) as {
    parts: Record<string, { selectors: string[]; pseudo: string[]; pseudo_unless?: string; states?: Record<string, string[]> }>
  }
  const files: string[] = []
  const walk = (folder: string) => {
    for (const name of readdirSync(folder)) {
      const path = join(folder, name)
      if (statSync(path).isDirectory()) walk(path)
      else if (/\.(tsx|ts|css)$/.test(name) && !/\.test\.tsx?$/.test(name)) files.push(readFileSync(path, 'utf8'))
    }
  }
  walk(join(process.cwd(), 'src'))
  const code = files.join('\n')

  it('are still in the code: every class and attribute their selectors use', () => {
    const missing: string[] = []
    for (const [name, part] of Object.entries(registry.parts)) {
      const selectors = [...part.selectors, ...Object.values(part.states ?? {}).flat()]
      for (const selector of selectors) {
        for (const [, word] of selector.matchAll(/\.([a-z][\w-]*)/g)) if (!new RegExp(`['"\` ]${word}['"\` ]|\\.${word}\\b`).test(code)) missing.push(`${name}: .${word}`)
        for (const [, word] of selector.matchAll(/\[([a-z][\w-]*)/g)) if (!code.includes(word)) missing.push(`${name}: [${word}]`)
      }
    }
    expect(missing).toEqual([])
  })

  it('leave free the pseudo elements they offer: no rule of nexdeck draws one there, outside the style named', () => {
    const sheet = readFileSync(join(process.cwd(), 'src', 'styles', 'app.css'), 'utf8')
    const taken: string[] = []
    for (const [name, part] of Object.entries(registry.parts)) {
      for (const selector of part.selectors) {
        for (const slot of part.pseudo) {
          const lines = sheet.split('\n').filter((line) => line.includes(`${selector}${slot}`) && !(part.pseudo_unless && line.includes(part.pseudo_unless)))
          if (lines.length) taken.push(`${name} ${slot}: ${lines[0].trim()}`)
        }
      }
    }
    expect(taken).toEqual([])
  })
})
