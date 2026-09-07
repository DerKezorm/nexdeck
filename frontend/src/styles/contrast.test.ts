/**
 * The colours are read out of the stylesheet and the contrast is recomputed.
 *
 * ⚠️ Six tokens of the light theme were below 4.5:1 as text, measured against
 * the page ground: text-faint at 2.67 and unknown at 2.26, which is roughly a
 * watermark. Nobody noticed because a colour looks fine to whoever picked it
 * on the screen they picked it on. This test does the arithmetic instead.
 *
 * The dark theme is checked the same way, so that a future adjustment cannot
 * fix one and break the other.
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const CSS = readFileSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), 'app.css'), 'utf8')

/** The tokens of one theme block, as `{name: '#rrggbb'}`. */
function tokensOf(selector: string): Record<string, string> {
  const start = CSS.indexOf(selector)
  expect(start, `${selector} is not in the stylesheet`).toBeGreaterThan(-1)
  const block = CSS.slice(start, CSS.indexOf('}', start))
  const found: Record<string, string> = {}
  for (const match of block.matchAll(/--(nd-[a-z-]+):\s*(#[0-9a-fA-F]{6})/g)) found[match[1]] = match[2]
  return found
}

function luminance(hex: string): number {
  const parts = [1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16) / 255)
  const linear = parts.map((value) => (value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4))
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
}

function contrast(a: string, b: string): number {
  const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (high + 0.05) / (low + 0.05)
}

/** Tokens that appear as text somewhere, and must be readable as text. */
const AS_TEXT = ['nd-text', 'nd-text-muted', 'nd-text-faint', 'nd-accent', 'nd-ok', 'nd-warn', 'nd-bad', 'nd-unknown']
/**
 * Tokens drawn as a shape rather than as text: the status dots and the bars.
 *
 * ⚠️ 3:1, not 4.5. That is the rule for a graphic somebody has to make out
 * (WCAG 1.4.11), and holding a dot to the text rule would push the dark
 * theme's status colours towards white until they stopped meaning anything.
 */
const AS_SHAPE = ['nd-ok', 'nd-warn', 'nd-bad', 'nd-unknown']

describe.each([
  ['light', ":root[data-theme='light']", 'nd-bg-elev'],
  ['dark', ':root {', 'nd-bg-elev'],
])('the %s theme', (_name, selector, elevated) => {
  const tokens = tokensOf(selector)

  it('has the tokens this test is about', () => {
    for (const token of [...AS_TEXT, ...AS_SHAPE, 'nd-on-accent', 'nd-bg', elevated]) {
      expect(tokens[token], `${token} is missing, so this test proves nothing`).toBeTruthy()
    }
  })

  it.each(AS_TEXT)('reads as text: %s', (token) => {
    // Both grounds: the page itself and the raised surface a card sits on.
    for (const ground of ['nd-bg', elevated]) {
      const seen = contrast(tokens[token], tokens[ground])
      expect(seen, `${token} on ${ground} is ${seen.toFixed(2)}:1`).toBeGreaterThanOrEqual(4.5)
    }
  })

  it.each(AS_SHAPE)('can be made out as a shape: %s', (token) => {
    for (const ground of ['nd-bg', elevated]) {
      const seen = contrast(tokens[token], tokens[ground])
      expect(seen, `${token} on ${ground} is ${seen.toFixed(2)}:1`).toBeGreaterThanOrEqual(3)
    }
  })

  it('carries the text that actually sits on the accent', () => {
    // ⚠️ Not white. The button hard-coded #041016, which is right on the dark
    // theme's bright cyan and 3.59:1 on the light theme's deep teal. The
    // colour is a token now, and this checks the pair that is really drawn.
    const seen = contrast(tokens['nd-on-accent'], tokens['nd-accent'])
    expect(seen, `on-accent over accent is ${seen.toFixed(2)}:1`).toBeGreaterThanOrEqual(4.5)
  })
})
