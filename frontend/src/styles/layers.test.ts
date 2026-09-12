/**
 * The style sheet keeps its own classes in a layer, so a utility on an element wins.
 *
 * ⚠️ Measured on 12.09.2026: with every rule of app.css outside a layer, ninety
 * elements ignored a utility written on them. Tailwind 4 puts utilities in
 * `@layer utilities`, and a rule outside any layer beats every layer however
 * specific it is. The card buttons were 32 pixels with a frame instead of flat
 * 24, the password field kept its text under the eye button, and a warning chip
 * was grey. tsc, eslint and every test were green; only a browser showed it.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

// From the frontend folder, where the test run starts; jsdom's URL cannot name a file.
const css = readFileSync(join(process.cwd(), 'src/styles/app.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')

interface Rule {
  selector: string
  layers: string[]
}

/** Every style rule with the layers around it. The sheet has no nesting, so braces are enough. */
function rules(text: string): Rule[] {
  const found: Rule[] = []
  const heads: string[] = []
  let start = 0
  for (let index = 0; index < text.length; index++) {
    const char = text[index]
    if (char === '{') {
      heads.push(text.slice(start, index).trim())
      start = index + 1
    } else if (char === '}') {
      const head = heads.pop() ?? ''
      if (head && !head.startsWith('@')) {
        found.push({
          selector: head.replace(/\s+/g, ' '),
          layers: heads.filter((one) => one.startsWith('@layer')).map((one) => one.slice('@layer'.length).trim()),
        })
      }
      start = index + 1
    } else if (char === ';' && heads.length === 0) {
      start = index + 1
    }
  }
  return found
}

const all = rules(css)
const withClass = all.filter((rule) => /\.[a-zA-Z]/.test(rule.selector))

describe('the style sheet', () => {
  it('keeps its own classes in a layer, so a utility on the same element wins', () => {
    const outside = withClass.filter((rule) => rule.layers.length === 0).map((rule) => rule.selector)
    // Only corrections to the grid library, whose own sheet has no layer: inside one they would lose to it.
    expect(outside).toEqual([
      '.react-grid-item.react-grid-placeholder',
      '.react-grid-item > .react-resizable-handle',
      '.react-grid-item:hover > .react-resizable-handle',
      '.react-grid-item > .react-resizable-handle::after',
      '.board-editing .react-grid-item > .react-resizable-handle',
      '.board-editing .react-grid-item > .react-resizable-handle::after',
    ])
  })

  it('lets only the named rules win over utilities, and puts them after the utilities', () => {
    const overrides = all.filter((rule) => rule.layers.includes('overrides')).map((rule) => rule.selector)
    expect(overrides).toEqual(['.card.is-editing > *:not(.card-controls)', 'body.has-player-bar main'])
    expect(css).toMatch(/@layer theme, base, components, utilities, overrides;/)
  })

  it('has its classes in the components layer, not an empty one', () => {
    // A layer that holds nothing would pass the first test as well.
    expect(withClass.filter((rule) => rule.layers.includes('components')).length).toBeGreaterThan(120)
  })
})
