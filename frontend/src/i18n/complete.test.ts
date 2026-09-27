/**
 * Every language knows every key, and none is empty. Since only English ships
 * in the bundle and other languages arrive later, a missing key would show up
 * as its path on screen.
 */
import de from './de.json'
import en from './en.json'
import es from './es.json'
import { LANGUAGES } from './index'

function paths(value: unknown, prefix = ''): string[] {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return prefix ? [prefix] : []
  return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) => paths(child, prefix ? `${prefix}.${key}` : key))
}

function lookup(data: unknown, path: string): unknown {
  return path.split('.').reduce<unknown>((node, key) => (node as Record<string, unknown> | undefined)?.[key], data)
}

/** Every language besides English, each with its interface texts. */
const TRANSLATIONS: Record<string, unknown> = { de, es }
const english = new Set(paths(en))

describe('language files', () => {
  it('exist for every language on offer, and only for those', () => {
    expect(['en', ...Object.keys(TRANSLATIONS)].sort()).toEqual(Object.keys(LANGUAGES).sort())
  })

  it('are not empty by accident', () => {
    // Two empty sets are equal too; the floor keeps the test honest.
    expect(english.size).toBeGreaterThan(200)
  })

  for (const [language, data] of Object.entries(TRANSLATIONS)) {
    const known = new Set(paths(data))

    it(`${language}: knows the same keys as English`, () => {
      expect([...known].filter((p) => !english.has(p)).sort(), `only in ${language}.json`).toEqual([])
      expect([...english].filter((p) => !known.has(p)).sort(), `missing from ${language}.json`).toEqual([])
    })

    it(`${language}: carries the same placeholders`, () => {
      const placeholders = (text: string) => (text.match(/\{\{\w+\}\}/g) ?? []).sort().join(',')
      const different = [...english].filter((p) => placeholders(String(lookup(en, p))) !== placeholders(String(lookup(data, p))))
      expect(different, `placeholders differ between en and ${language}`).toEqual([])
    })
  }

  it('have no empty texts', () => {
    for (const [language, data] of Object.entries({ en, ...TRANSLATIONS })) {
      const empty = paths(data).filter((p) => String(lookup(data, p)).trim() === '')
      expect(empty, `${language}: empty texts`).toEqual([])
    }
  })

  it('use no em dashes', () => {
    for (const [language, data] of Object.entries({ en, ...TRANSLATIONS })) {
      const offenders = paths(data).filter((p) => String(lookup(data, p)).includes('—'))
      expect(offenders, `${language}: em dash`).toEqual([])
    }
  })
})
