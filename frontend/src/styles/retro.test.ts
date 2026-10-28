/**
 * The sheet of 1984 (retro.css) touches nothing but 1984, and draws the
 * state of a window in its shape, not in its colour alone.
 *
 * ⚠️ It sits in a layer after every layer of app.css and so wins over the
 * utilities as well. A rule in it without the mark of 1984 in front would
 * redraw every other look. The first test is the fence.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const read = (name: string) => readFileSync(join(process.cwd(), name), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')
const sheet = read('src/styles/retro.css')
const MARK = ":root[data-cards='window']"

/** Every rule with its selector and the at-rules around it. The sheet nests only in at-rules. */
function rules(text: string): { selector: string; around: string[]; body: string }[] {
  const found: { selector: string; around: string[]; body: string }[] = []
  const heads: string[] = []
  let start = 0
  for (let index = 0; index < text.length; index++) {
    const char = text[index]
    if (char === '{') {
      heads.push(text.slice(start, index).trim())
      start = index + 1
    } else if (char === '}') {
      const head = heads.pop() ?? ''
      if (head && !head.startsWith('@') && !/^(from|to|\d+%)$/.test(head)) {
        found.push({ selector: head.replace(/\s+/g, ' '), around: heads.filter((one) => one.startsWith('@')), body: text.slice(start, index) })
      }
      start = index + 1
    }
  }
  return found
}

const all = rules(sheet)
const bodyOf = (selector: string) => all.filter((rule) => rule.selector === selector).map((rule) => rule.body).join('\n')

describe('the sheet of 1984', () => {
  it('has every rule in its own layer, behind the mark of 1984', () => {
    expect(all.length).toBeGreaterThan(100)
    const outside = all.filter((rule) => !rule.around.includes('@layer retro')).map((rule) => rule.selector)
    expect(outside).toEqual([])
    const unmarked = all.flatMap((rule) => rule.selector.split(/,(?![^(]*\))/).map((one) => one.trim())).filter((one) => !one.startsWith(MARK))
    expect(unmarked).toEqual([])
  })

  it('is fetched only when chosen: nothing that always loads imports it, and app.css knows nothing of it', () => {
    expect(read('src/main.tsx')).not.toMatch(/retro\.css/)
    expect(read('src/App.tsx')).not.toMatch(/retro\.css/)
    expect(read('src/styles/app.css')).not.toMatch(/retro|data-cards='window'/)
    expect(read('src/lib/retro.ts')).toMatch(/import\('\.\.\/styles\/retro\.css'\)/)
  })

  it('draws a yellow window with a hatched title bar and a red one black with a double frame', () => {
    expect(bodyOf(`${MARK} .card.glass[data-status='warn']:not(.card-plain) > header`)).toMatch(/var\(--r-hatch\)/)
    expect(bodyOf(`${MARK} .card.glass[data-status='bad']:not(.card-plain) > header`)).toMatch(/background: var\(--r-ink\)/)
    expect(bodyOf(`${MARK} .card.glass[data-status='bad']:not(.card-plain)`)).toMatch(/border-width: 2px/)
    expect(bodyOf(`${MARK} .card.glass > header`)).toMatch(/var\(--r-stripes\)/)
  })

  it('turns the words in a pressed or open button of the bar with the button, so the account name does not vanish', () => {
    const pressed = `${MARK} .app-bar :is(.btn, a, button):is(:hover, :active, [aria-expanded='true'], [aria-pressed='true'], [aria-current='page']):not(:has(kbd)) :is(.text-muted, .text-faint, .text-accent, .text-ink)`
    expect(bodyOf(pressed)).toMatch(/color: var\(--r-paper\)/)
    // After the rule that makes those words black, or it loses on order.
    expect(sheet.indexOf(pressed)).toBeGreaterThan(sheet.indexOf(`${MARK} .app-bar :is(.text-muted, .text-faint)`))
  })

  it('draws the music player as a window: a striped title bar, no soft picture behind it, tabs inverted when open', () => {
    expect(bodyOf(`${MARK} .player-titlebar`)).toMatch(/var\(--r-stripes\)/)
    expect(bodyOf(`${MARK} .player-titlebar`)).not.toMatch(/display: none/)
    expect(bodyOf(`${MARK} :is(.player-backdrop, .player-veil)`)).toMatch(/display: none/)
    expect(bodyOf(`${MARK} :is(.player, .player-volume-pop)`)).toMatch(/--pa: var\(--r-ink\) !important/)
    expect(bodyOf(`${MARK} .player-tab.is-active`)).toMatch(/background: var\(--r-ink\)/)
    expect(bodyOf(`${MARK} .player-caption`)).toMatch(/background: var\(--r-paper\)/)
  })

  it('gives green, yellow and red a symbol of their own shape, and no colour at all in pattern only', () => {
    const shapes = ['ok', 'warn', 'bad'].map((status) => /--r-mark: url\(([^)]*)\)/.exec(bodyOf(`${MARK} .dot[data-status='${status}']`))?.[1])
    expect(shapes.every(Boolean)).toBe(true)
    expect(new Set(shapes).size).toBe(3)
    const pattern = bodyOf(`${MARK}[data-r-status='pattern']`)
    for (const token of ['--r-ok', '--r-warn', '--r-bad']) expect(pattern).toMatch(new RegExp(`${token}: var\\(--r-paper\\)`))
  })

  it('draws a link of the plan as a solid black line with a border of paper, wider as it fills, on a grey ground', () => {
    const line = `${MARK} [data-link-id] :is(path, polyline):not([data-link], .nd-link-halo)`
    expect(bodyOf(line)).toMatch(/stroke-width: 2px !important/)
    expect(bodyOf(`${MARK} [data-link-id] path[data-level='full']`)).toMatch(/stroke-width: 4px/)
    expect(bodyOf(`${MARK} [data-link-id] path[data-level='down']`)).toMatch(/stroke-dasharray/)
    expect(bodyOf(`${MARK} [data-link-id] .nd-link-halo`)).toMatch(/stroke: var\(--r-paper\)/)
    expect(bodyOf(`${MARK} [data-link-id]:has(path[data-level='full']) .nd-link-halo`)).toMatch(/stroke-width: 8px/)
    expect(bodyOf(`${MARK} [data-topology-label] rect`)).toMatch(/rx: 0/)
    expect(bodyOf(`${MARK} [data-topology-canvas]`)).toMatch(/background: color-mix/)
  })

  it('keeps glass, blur and shadows out, and the corners square except on buttons', () => {
    expect(bodyOf(`${MARK} *, ${MARK} *::before, ${MARK} *::after`)).toMatch(/backdrop-filter: none !important/)
    expect(bodyOf(`${MARK} .btn`)).toMatch(/border-radius: 6px/)
  })
})
