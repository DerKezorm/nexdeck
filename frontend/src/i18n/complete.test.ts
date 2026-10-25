/**
 * Every language knows every key, and none is empty. Since only English ships
 * in the bundle and other languages arrive later, a missing key would show up
 * as its path on screen.
 */
import assistantDe from './assistant.de.json'
import assistantEn from './assistant.en.json'
import assistantEs from './assistant.es.json'
import assistantFr from './assistant.fr.json'
import assistantIt from './assistant.it.json'
import de from './de.json'
import diagnosisDe from './diagnosis.de.json'
import diagnosisEn from './diagnosis.en.json'
import diagnosisEs from './diagnosis.es.json'
import diagnosisFr from './diagnosis.fr.json'
import diagnosisIt from './diagnosis.it.json'
import editorDe from './editor.de.json'
import editorEn from './editor.en.json'
import editorEs from './editor.es.json'
import editorFr from './editor.fr.json'
import editorIt from './editor.it.json'
import inventoryDe from './inventory.de.json'
import inventoryEn from './inventory.en.json'
import inventoryEs from './inventory.es.json'
import inventoryFr from './inventory.fr.json'
import inventoryIt from './inventory.it.json'
import en from './en.json'
import es from './es.json'
import fr from './fr.json'
import it_ from './it.json'
import { LANGUAGES } from './index'
import oidcEs from './oidc.es.json'
import oidcFr from './oidc.fr.json'
import oidcIt from './oidc.it.json'
import oidcDe from '../vendor/nexoidc/oidc.de.json'
import oidcEn from '../vendor/nexoidc/oidc.en.json'

function paths(value: unknown, prefix = ''): string[] {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return prefix ? [prefix] : []
  return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) => paths(child, prefix ? `${prefix}.${key}` : key))
}

function lookup(data: unknown, path: string): unknown {
  return path.split('.').reduce<unknown>((node, key) => (node as Record<string, unknown> | undefined)?.[key], data)
}

/** Every language besides English, each with its interface texts. */
const TRANSLATIONS: Record<string, unknown> = { de, es, fr, it: it_ }
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
      const offenders = paths(data).filter((p) => String(lookup(data, p)).match(/[—–]/))
      expect(offenders, `${language}: em dash`).toEqual([])
    }
  })
})

/**
 * The sign-in words: German and English come from the shared module word for word; Spanish, French and Italian are
 * nexdeck's own (`oidc.<code>.json`) and must carry every key and placeholder the module's English has, or the page
 * shows a path where a sentence belongs.
 */
describe('sign-in words in every language', () => {
  const english = new Set(paths(oidcEn))
  it('are not empty by accident', () => {
    expect(english.size).toBeGreaterThan(100)
  })
  for (const [language, data] of Object.entries({ de: oidcDe, es: oidcEs, fr: oidcFr, it: oidcIt })) {
    it(`${language}: knows the same keys and placeholders as English`, () => {
      const known = new Set(paths(data))
      expect([...known].filter((p) => !english.has(p)).sort(), `only in oidc.${language}`).toEqual([])
      expect([...english].filter((p) => !known.has(p)).sort(), `missing from oidc.${language}`).toEqual([])
      const placeholders = (text: string) => (text.match(/\{\{\w+\}\}/g) ?? []).sort().join(',')
      const different = [...english].filter((p) => placeholders(String(lookup(oidcEn, p))) !== placeholders(String(lookup(data, p))))
      expect(different, `placeholders differ between en and ${language}`).toEqual([])
      const empty = [...known].filter((p) => String(lookup(data, p)).trim() === '' || String(lookup(data, p)).match(/[—–]/))
      expect(empty, `${language}: empty texts or em dashes`).toEqual([])
    })
  }
})

/**
 * The words of the chat (roadmap M3), the inventory (roadmap M5) and the diagnosis (roadmap M6) come in files of their own (`lib/lazyTexts.ts`),
 * and so do those of the card editor (`pages/cardEditor/editorTexts.ts`);
 * each language carries every key and placeholder of the English one.
 */
const LAZY = {
  assistant: { en: assistantEn, de: assistantDe, es: assistantEs, fr: assistantFr, it: assistantIt },
  inventory: { en: inventoryEn, de: inventoryDe, es: inventoryEs, fr: inventoryFr, it: inventoryIt },
  diagnosis: { en: diagnosisEn, de: diagnosisDe, es: diagnosisEs, fr: diagnosisFr, it: diagnosisIt },
  editor: { en: editorEn, de: editorDe, es: editorEs, fr: editorFr, it: editorIt },
}
for (const [part, bundles] of Object.entries(LAZY)) {
  describe(`the ${part} words in every language`, () => {
    const english = new Set(paths(bundles.en))
    it('are not empty by accident', () => {
      expect(english.size).toBeGreaterThan(20)
    })
    for (const [language, data] of Object.entries(bundles).filter(([code]) => code !== 'en')) {
      it(`${language}: knows the same keys and placeholders as English, none empty`, () => {
        const known = new Set(paths(data))
        expect([...english].filter((p) => !known.has(p)).sort(), `missing from ${part}.${language}.json`).toEqual([])
        expect([...known].filter((p) => !english.has(p)).sort(), `only in ${part}.${language}.json`).toEqual([])
        const placeholders = (text: string) => (text.match(/\{\{\w+\}\}/g) ?? []).sort().join(',')
        expect([...english].filter((p) => placeholders(String(lookup(bundles.en, p))) !== placeholders(String(lookup(data, p))))).toEqual([])
        expect(paths(data).filter((p) => !String(lookup(data, p)).trim() || String(lookup(data, p)).match(/[—–]/))).toEqual([])
      })
    }
  })
}
