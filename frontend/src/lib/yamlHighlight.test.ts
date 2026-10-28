/**
 * The colours of YAML in the editors (Etappe 8, N8): each is a token of the interface and holds 4.5:1 against both grounds
 * of both themes. The numbers are computed from `app.css`, as `styles/contrast.test.ts` does for the tokens themselves.
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import { YAML_COLORS, yamlHighlight } from './yamlHighlight'

const CSS = readFileSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../styles/app.css'), 'utf8')

function tokensOf(selector: string): Record<string, string> {
  const start = CSS.indexOf(selector)
  const block = CSS.slice(start, CSS.indexOf('}', start))
  const found: Record<string, string> = {}
  for (const match of block.matchAll(/--(nd-[a-z-]+):\s*(#[0-9a-fA-F]{6})/g)) found[match[1]] = match[2]
  return found
}

function luminance(hex: string): number {
  const linear = [1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16) / 255).map((value) => (value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4))
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
}

const contrast = (a: string, b: string) => {
  const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (high + 0.05) / (low + 0.05)
}

describe.each([
  ['light', ":root[data-theme='light']"],
  ['dark', ':root {'],
])('YAML in the %s theme', (_name, selector) => {
  const tokens = tokensOf(selector)

  it.each(Object.entries(YAML_COLORS))('karten8n_n8: %s (%s) reads at 4.5:1 on the page and on the raised surface', (_kind, token) => {
    for (const ground of ['nd-bg', 'nd-bg-elev']) {
      const seen = contrast(tokens[token], tokens[ground])
      expect(seen, `${token} on ${ground} is ${seen.toFixed(2)}:1`).toBeGreaterThanOrEqual(4.5)
    }
  })
})

describe('the style', () => {
  it('karten8n_n8: the key colour is the accent of the interface, not a fixed blue', () => {
    expect(YAML_COLORS.key).toBe('nd-accent')
    const css = (yamlHighlight as unknown as { module: { getRules(): string } }).module.getRules()
    expect(css).toContain('color: var(--nd-accent)')
    expect(css).not.toMatch(/#00[0-9a-f]{2}\b|#256\b/i)
  })
})
