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

function at(key: string): unknown {
  return key.split('.').reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], en)
}

/**
 * ⚠️ A counted string is not stored under the name it is asked for. i18next
 * takes ``t('users.removeKiosk', { count })`` and looks up ``…_one`` or
 * ``…_other``; the bare name is not in the file at all. Without this the guard
 * calls every plural key missing, which is the kind of false alarm that gets a
 * guard switched off.
 */
function exists(key: string): boolean {
  if (at(key) !== undefined) return true
  return ['_one', '_other'].every((suffix) => at(key + suffix) !== undefined)
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
    let ignoredKinds = 0
    for (const file of source) {
      // ⚠️ A widget kind is shaped exactly like a key and is not one:
      // `kind: 'plex.load'` names an adapter and its widget, and `plex`
      // happens to be a section in en.json because signing in to Plex has its
      // own words. Removing only the value of a `kind:` property keeps the
      // guard's reach everywhere else; a section-wide exception would have
      // blinded it to every loose `plex.*` string there is.
      const text = readFileSync(file, 'utf8').replace(/\bkind:\s*'[^']*'/g, () => {
        ignoredKinds += 1
        return "kind: ''"
      })
      for (const match of text.matchAll(/'([a-z][a-zA-Z0-9]*(?:\.[a-zA-Z0-9_]+){1,4})'/g)) {
        if (sections.has(match[1].split('.')[0])) loose.add(match[1])
      }
    }
    expect(loose.size, 'the scan found nothing at all').toBeGreaterThan(0)
    // A floor under the exception too: the day `kind:` stops being written
    // this way, the line above quietly stops excluding anything, and nobody
    // would notice because the guard would simply keep passing.
    expect(ignoredKinds, 'no widget kind was skipped, so that exception is dead code').toBeGreaterThan(20)
    const missing = [...loose].filter((key) => !exists(key)).sort()
    expect(missing, 'strings shaped like a translation key that point nowhere').toEqual([])
  })
})

