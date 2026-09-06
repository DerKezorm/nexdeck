/**
 * Every literal ``t('…')`` key in the source exists in en.json.
 *
 * Dynamic keys (``t(\`x.${y}\`)``) cannot be checked this way; they pass a
 * ``defaultValue`` or belong to a family whose members are all present.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import en from './en.json'

function files(directory: string): string[] {
  return readdirSync(directory).flatMap((name: string) => {
    const full = path.join(directory, name)
    if (statSync(full).isDirectory()) return files(full)
    return /\.(ts|tsx)$/.test(name) && !name.includes('.test.') ? [full] : []
  })
}

function exists(key: string): boolean {
  return key.split('.').reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], en) !== undefined
}

describe('translation keys used in the source', () => {
  const source = files(path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..'))
  const used = new Set<string>()
  for (const file of source) {
    const text = readFileSync(file, 'utf8')
    for (const match of text.matchAll(/\bt\(\s*'([a-zA-Z0-9_.]+)'/g)) used.add(match[1])
  }

  it('finds keys at all', () => {
    expect(used.size).toBeGreaterThan(100)
  })

  it('all exist in en.json', () => {
    const missing = [...used].filter((key) => !exists(key)).sort()
    expect(missing, 'keys used in components but missing from en.json').toEqual([])
  })

  it('finds keys that are not written inside a t() call', () => {
    // ⚠️ A key does not have to sit inside a t(…) call to be one. The restore
    // dialog picks its warning first and translates it afterwards, so the key
    // lives in a plain string. This guard walked straight past a whole set of
    // them that pointed at a section which does not exist.
    const sections = new Set(Object.keys(en))
    const loose = new Set<string>()
    for (const file of source) {
      const text = readFileSync(file, 'utf8')
      for (const match of text.matchAll(/'([a-z][a-zA-Z0-9]*(?:\.[a-zA-Z0-9_]+){1,4})'/g)) {
        if (sections.has(match[1].split('.')[0])) loose.add(match[1])
      }
    }
    expect(loose.size, 'the scan found nothing at all').toBeGreaterThan(0)
    const missing = [...loose].filter((key) => !exists(key)).sort()
    expect(missing, 'strings shaped like a translation key that point nowhere').toEqual([])
  })
})

