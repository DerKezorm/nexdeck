/**
 * Every language knows every key, and none is empty. Since only English ships
 * in the bundle and other languages arrive later, a missing key would show up
 * as its path on screen.
 */
import de from './de.json'
import en from './en.json'

function paths(value: unknown, prefix = ''): string[] {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return prefix ? [prefix] : []
  return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) => paths(child, prefix ? `${prefix}.${key}` : key))
}

function lookup(data: unknown, path: string): unknown {
  return path.split('.').reduce<unknown>((node, key) => (node as Record<string, unknown> | undefined)?.[key], data)
}

const english = new Set(paths(en))
const german = new Set(paths(de))

describe('language files', () => {
  it('know the same keys', () => {
    expect([...german].filter((p) => !english.has(p)).sort(), 'only in de.json').toEqual([])
    expect([...english].filter((p) => !german.has(p)).sort(), 'only in en.json').toEqual([])
  })

  it('are not empty by accident', () => {
    // Two empty sets are equal too; the floor keeps the test honest.
    expect(english.size).toBeGreaterThan(200)
  })

  it('have no empty texts', () => {
    for (const [language, data] of [['en', en], ['de', de]] as const) {
      const empty = paths(data).filter((p) => String(lookup(data, p)).trim() === '')
      expect(empty, `${language}: empty texts`).toEqual([])
    }
  })

  it('carry the same placeholders', () => {
    const placeholders = (text: string) => (text.match(/\{\{\w+\}\}/g) ?? []).sort().join(',')
    const different = [...english].filter((p) => placeholders(String(lookup(en, p))) !== placeholders(String(lookup(de, p))))
    expect(different, 'placeholders differ between en and de').toEqual([])
  })

  it('use no em dashes', () => {
    for (const [language, data] of [['en', en], ['de', de]] as const) {
      const offenders = paths(data).filter((p) => String(lookup(data, p)).includes('—'))
      expect(offenders, `${language}: em dash`).toEqual([])
    }
  })
})
