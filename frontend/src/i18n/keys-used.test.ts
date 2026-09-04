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
})
