/**
 * Every own class the source uses must exist in the stylesheet.
 *
 * ⚠️ Two settings pages reached for `btn-ghost` and `btn-primary`, which were
 * never written. Tailwind silently ignores a class it does not know and CSS
 * silently ignores one that is not defined, so the buttons rendered as bare
 * text and looked broken next to every other page. Nothing failed, nothing
 * warned; it took somebody looking at the screen.
 *
 * Only the project's own prefixes are checked. Tailwind's utilities are its
 * own business and there are thousands of them.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/** Prefixes the project defines itself in `app.css`. */
const OWN = ['btn', 'card', 'chip', 'glass', 'input', 'num', 'kiosk', 'nd-']

const ROOT = join(import.meta.dirname, '..')

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry)
    if (statSync(path).isDirectory()) return sources(path)
    return /\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry) ? [path] : []
  })
}

function defined(): Set<string> {
  const css = readFileSync(join(ROOT, 'styles', 'app.css'), 'utf8')
  const names = new Set<string>()
  for (const match of css.matchAll(/\.([a-zA-Z][\w-]*)/g)) names.add(match[1])
  return names
}

/** Class names out of every `className="..."` and `` className={`...`} ``. */
function used(text: string): string[] {
  const found: string[] = []
  for (const match of text.matchAll(/className=(?:"([^"]*)"|\{`([^`]*)`\})/g)) {
    const raw = (match[1] ?? match[2] ?? '')
      // Drop `${...}` holes; what is inside them is a separate literal.
      .replace(/\$\{[^}]*\}/g, ' ')
      .replace(/[?:'"]/g, ' ')
    found.push(...raw.split(/\s+/).filter(Boolean))
  }
  return found
}

describe('own CSS classes', () => {
  it('are all defined in app.css', () => {
    const known = defined()
    const files = sources(ROOT)
    expect(files.length).toBeGreaterThan(30)

    const missing: string[] = []
    let checked = 0
    for (const file of files) {
      const text = readFileSync(file, 'utf8')
      for (const name of used(text)) {
        // A Tailwind variant such as `hover:btn` is not one of ours.
        if (name.includes(':') || name.includes('[')) continue
        if (!OWN.some((prefix) => (prefix.endsWith('-') ? name.startsWith(prefix) : name === prefix || name.startsWith(`${prefix}-`)))) continue
        checked += 1
        if (!known.has(name)) missing.push(`${file.slice(ROOT.length + 1)}: ${name}`)
      }
    }
    // A floor, so an empty scan cannot pass: the buttons alone are dozens.
    expect(checked).toBeGreaterThan(50)
    expect(missing).toEqual([])
  })

  it('would notice a class that does not exist', () => {
    // The guard above is only worth something if this fails.
    const known = defined()
    expect(known.has('btn')).toBe(true)
    expect(known.has('btn-accent')).toBe(true)
    expect(known.has('btn-ghost')).toBe(false)
    expect(known.has('btn-primary')).toBe(false)
  })
})
