/**
 * Every language knows every key, and none is empty. Since only English ships
 * in the bundle and other languages arrive later, a missing key would show up
 * as its path on screen.
 *
 * The files are gathered by their names (`<code>.json`, `<part>.<code>.json`,
 * `oidc.<code>.json`), so a language added to LANGUAGES is held to all of this
 * without a line here. Two rules came with Dutch, Polish, Portuguese and
 * Russian: a language whose numbers have more forms than English (Polish and
 * Russian: one, few, many, other) carries each of them for every plural key,
 * and a file that is mostly English still is caught, since a stand-in passes
 * every other check.
 */
/// <reference types="vite/client" />
import { describe, expect, it } from 'vitest'

import oidcDe from '../vendor/nexoidc/oidc.de.json'
import oidcEn from '../vendor/nexoidc/oidc.en.json'
import { LANGUAGES } from './index'

type Words = Record<string, unknown>

const FILES = import.meta.glob<Words>('./*.json', { eager: true, import: 'default' })

function file(name: string): Words | undefined {
  return FILES[`./${name}.json`]
}

function paths(value: unknown, prefix = ''): string[] {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return prefix ? [prefix] : []
  return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) => paths(child, prefix ? `${prefix}.${key}` : key))
}

function lookup(data: unknown, path: string): unknown {
  return path.split('.').reduce<unknown>((node, key) => (node as Record<string, unknown> | undefined)?.[key], data)
}

const placeholders = (text: string) => (text.match(/\{\{\w+\}\}/g) ?? []).sort().join(',')

/**
 * The plural forms a language must carry beyond English's one and other: few and many where its numbers have a few
 * (Polish, Russian). A language whose many is only for millions (Spanish, French, Italian, Portuguese) may carry it,
 * and falls back to other where it does not.
 */
function plurals(language: string): { needed: string[]; allowed: string[] } {
  const forms = new Intl.PluralRules(language).resolvedOptions().pluralCategories.filter((form) => form !== 'one' && form !== 'other')
  return { needed: forms.includes('few') ? forms : [], allowed: forms }
}

/** Holds a language's file to the English one: the same keys (with the plural forms its numbers need), placeholders, no empty text, no dash. */
function sameAsEnglish(english: Words, data: Words, language: string, name: string): void {
  const { needed, allowed } = plurals(language)
  const englishKeys = new Set(paths(english))
  const known = new Set(paths(data))
  const counted = [...englishKeys].filter((key) => key.endsWith('_other')).map((key) => key.slice(0, -'_other'.length))
  const required = new Set([...englishKeys, ...counted.flatMap((base) => needed.map((form) => `${base}_${form}`))])
  const permitted = new Set([...required, ...counted.flatMap((base) => allowed.map((form) => `${base}_${form}`))])
  expect([...required].filter((key) => !known.has(key)).sort(), `missing from ${name}`).toEqual([])
  expect([...known].filter((key) => !permitted.has(key)).sort(), `only in ${name}`).toEqual([])
  // A plural form says what its key's other says, with the same placeholders.
  const of = (key: string) => (englishKeys.has(key) ? key : key.replace(/_(zero|two|few|many)$/, '_other'))
  const different = [...known].filter((key) => placeholders(String(lookup(english, of(key)))) !== placeholders(String(lookup(data, key))))
  expect(different, `placeholders differ between English and ${name}`).toEqual([])
  const bad = [...known].filter((key) => String(lookup(data, key)).trim() === '' || /[—–]/.test(String(lookup(data, key))))
  expect(bad, `${name}: empty texts or dashes`).toEqual([])
}

/** The share of texts that stand word for word as in English; above this a file was not translated (today's languages: 8 % at most). */
const MOSTLY_ENGLISH = 0.15

function sameWords(english: Words, data: Words): number {
  const keys = paths(english)
  return keys.filter((key) => lookup(data, key) === lookup(english, key)).length / keys.length
}

const OTHERS = Object.keys(LANGUAGES).filter((code) => code !== 'en')
const en = file('en')!

describe('language files', () => {
  it('exist for every language on offer, and only for those', () => {
    const present = Object.keys(FILES)
      .map((path) => path.match(/^\.\/([a-z]{2})\.json$/)?.[1])
      .filter((code): code is string => Boolean(code))
    expect(present.sort()).toEqual(Object.keys(LANGUAGES).sort())
  })

  it('are not empty by accident', () => {
    // Two empty sets are equal too; the floor keeps the test honest.
    expect(paths(en).length).toBeGreaterThan(200)
  })

  for (const language of OTHERS) {
    it(`${language}: knows the same keys, plural forms and placeholders as English, none empty`, () => {
      sameAsEnglish(en, file(language)!, language, `${language}.json`)
    })

    it(`${language}: is translated, not English`, () => {
      expect(sameWords(en, file(language)!)).toBeLessThan(MOSTLY_ENGLISH)
    })
  }

  it('in English use no dashes', () => {
    expect(paths(en).filter((key) => /[—–]/.test(String(lookup(en, key))))).toEqual([])
  })
})

/**
 * The sign-in words: German and English come from the shared module word for word; every other language is
 * nexdeck's own (`oidc.<code>.json`) and must carry every key and placeholder the module's English has, or the page
 * shows a path where a sentence belongs.
 */
describe('sign-in words in every language', () => {
  it('are not empty by accident', () => {
    expect(paths(oidcEn).length).toBeGreaterThan(100)
  })
  for (const language of OTHERS) {
    it(`${language}: knows the same keys and placeholders as English`, () => {
      const data = language === 'de' ? (oidcDe as Words) : file(`oidc.${language}`)
      expect(data, `oidc.${language}.json`).toBeDefined()
      sameAsEnglish(oidcEn as Words, data!, language, `oidc.${language}`)
    })
  }
})

/**
 * The words of the chat (roadmap M3), the inventory (roadmap M5) and the diagnosis (roadmap M6) come in files of their own (`lib/lazyTexts.ts`),
 * and so do those of the card editor (`pages/cardEditor/editorTexts.ts`), the skins and MCP;
 * each language carries every key and placeholder of the English one.
 */
for (const part of ['assistant', 'inventory', 'diagnosis', 'skins', 'editor', 'mcp']) {
  describe(`the ${part} words in every language`, () => {
    const english = file(`${part}.en`)!
    it('are not empty by accident', () => {
      expect(paths(english).length).toBeGreaterThan(20)
    })
    for (const language of OTHERS) {
      it(`${language}: knows the same keys and placeholders as English, none empty, and is translated`, () => {
        const data = file(`${part}.${language}`)
        expect(data, `${part}.${language}.json`).toBeDefined()
        sameAsEnglish(english, data!, language, `${part}.${language}.json`)
        expect(sameWords(english, data!)).toBeLessThan(MOSTLY_ENGLISH)
      })
    }
  })
}
