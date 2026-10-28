/**
 * The card style of Appearance reaches the boxes, sheets, dialogs, menus, the
 * search and the assistant (`:root[data-chrome]` in app.css), without touching
 * a card, and what stands over other content keeps a ground that covers.
 *
 * ⚠️ A card is also `.glass`. A chrome rule that reached it would draw a card
 * of a board with a style of its own in the installation's style, and a rule
 * that gave a dialog the thin fill of liquid glass would let the cards behind
 * it show through the words. Nothing fails at build time for either; the page
 * only looks wrong.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

import { CARD_STYLES } from '../lib/appearance'

const css = readFileSync(join(process.cwd(), 'src/styles/app.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')

interface Rule {
  selectors: string[]
  body: string
}

/** Every rule that names `data-chrome`, its selectors split at top-level commas. */
function chromeRules(): Rule[] {
  const found: Rule[] = []
  const heads: string[] = []
  let start = 0
  for (let index = 0; index < css.length; index++) {
    const char = css[index]
    if (char === '{') {
      heads.push(css.slice(start, index).trim())
      start = index + 1
    } else if (char === '}') {
      const head = heads.pop() ?? ''
      if (head.includes('[data-chrome=')) {
        const selectors: string[] = []
        let depth = 0
        let from = 0
        for (let at = 0; at < head.length; at++) {
          if (head[at] === '(') depth += 1
          else if (head[at] === ')') depth -= 1
          else if (head[at] === ',' && depth === 0) {
            selectors.push(head.slice(from, at).replace(/\s+/g, ' ').trim())
            from = at + 1
          }
        }
        selectors.push(head.slice(from).replace(/\s+/g, ' ').trim())
        found.push({ selectors, body: css.slice(start, index) })
      }
      start = index + 1
    } else if (char === ';' && heads.length === 0) {
      start = index + 1
    }
  }
  return found
}

/** The parts of a value between its commas outside parentheses. */
function topLevel(value: string): string[] {
  const parts: string[] = []
  let depth = 0
  let from = 0
  for (let at = 0; at < value.length; at++) {
    if (value[at] === '(') depth += 1
    else if (value[at] === ')') depth -= 1
    else if (value[at] === ',' && depth === 0) {
      parts.push(value.slice(from, at).trim())
      from = at + 1
    }
  }
  parts.push(value.slice(from).trim())
  return parts
}

const rules = chromeRules()
const STYLES = CARD_STYLES.filter((style) => style !== 'glass' && style !== 'window')
const background = (rule: Rule) => /(?:^|[;\s])background:\s*([^;]+);/.exec(rule.body)?.[1].replace(/\s+/g, ' ').trim()

describe('the card style on everything that is not a card', () => {
  it('has rules for every style but glass, which needs none, and 1984, which draws its own', () => {
    expect(rules.length).toBeGreaterThan(10)
    for (const style of STYLES) {
      expect(rules.some((rule) => rule.selectors.some((one) => one.startsWith(`:root[data-chrome='${style}']`))), style).toBe(true)
    }
    const named = new Set(rules.flatMap((rule) => rule.selectors).map((one) => /^:root\[data-chrome='(\w+)'\]/.exec(one)?.[1]))
    expect([...named].sort()).toEqual([...STYLES].sort())
  })

  it('never reaches a card, a button or the bar on a card, and leaves the empty bar of sign-in empty', () => {
    // The nested well (a box inside a sheet) lists them as well; every surface rule does.
    for (const rule of rules) {
      for (const one of rule.selectors) {
        expect(one, one).toMatch(/:where\(:not\(\.card, \.btn, \.card-controls[,)]/)
      }
    }
    // Only the bar is ever bare, and it is `.glass-strong`; liquid leaves every bar out.
    const strong = rules.flatMap((rule) => rule.selectors).filter((one) => /\.glass-strong(?![\w-]| \.glass)/.test(one))
    expect(strong.length).toBeGreaterThan(4)
    for (const one of strong) expect(one, one).toMatch(/\[data-look='bare'\]|\.app-bar/)
  })

  it('gives whatever stands over other content a ground that covers, in every style', () => {
    const over = rules.filter((rule) => rule.selectors.some((one) => /\.glass-strong(?![\w-]| \.glass)/.test(one) && !one.includes('.glass-strong .glass')))
    const covering = /^(?:var\(--nd-bg\)|var\(--nd-bg-elev\)|var\(--nd-surface-strong\)|color-mix\(in srgb, var\(--nd-bg-elev\) 82%, var\(--nd-bg\)\))$/
    const grounds: Record<string, string[]> = {}
    for (const rule of over) {
      const value = background(rule)
      if (!value) continue
      // A glare may lie over the ground; the ground is what is left.
      const ground = topLevel(value).at(-1) ?? ''
      expect(ground, rule.selectors.join(' | ')).toMatch(covering)
      for (const one of rule.selectors) {
        const style = /data-chrome='(\w+)'/.exec(one)?.[1]
        if (style) (grounds[style] ??= []).push(ground)
      }
    }
    // Neon keeps the strong glass, which is the ground every other style starts from.
    for (const style of STYLES.filter((each) => each !== 'neon')) expect(grounds[style]?.length, style).toBeGreaterThan(0)
  })

  it('draws liquid without the thin fill of a card over anything that covers', () => {
    const strong = rules.filter((rule) => rule.selectors.every((one) => one.includes("data-chrome='liquid'") && /\.glass-strong:where/.test(one)))
    expect(strong.length).toBeGreaterThan(0)
    for (const rule of strong) expect(rule.body).not.toContain('--nd-lg-fill')
  })
})
