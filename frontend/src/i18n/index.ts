import i18next from 'i18next'
import { initReactI18next } from 'react-i18next'

import en from './en.json'
import { registerTexts, type TextBundle } from './texts'

/**
 * English ships in the bundle; every other language is fetched when chosen.
 *
 * Adding a language means:
 * - a line in LANGUAGES, and the code in SUPPORTED in backend/app/languages.py
 *   (a guard keeps the two equal);
 * - <code>.json with every key of en.json, and a loader for it below;
 * - texts.<code>.json with every server text texts.de.json knows, translated
 *   from the English key, and a loader for it below;
 * - patterns.<code>.ts, the German patterns in texts.ts in the same order,
 *   registered in PATTERNS there;
 * - the new tables in the lists of complete.test.ts and texts.test.ts.
 * "What's new" stays English and German; every other language shows English.
 */
export const LANGUAGES: Record<string, string> = { en: 'English', de: 'Deutsch', es: 'Español', fr: 'Français', it: 'Italiano' }

const loaders: Record<string, () => Promise<{ default: Record<string, unknown> }>> = {
  de: () => import('./de.json'),
  es: () => import('./es.json'),
  fr: () => import('./fr.json'),
  it: () => import('./it.json'),
}

const textLoaders: Record<string, () => Promise<{ default: unknown }>> = {
  de: () => import('./texts.de.json'),
  es: () => import('./texts.es.json'),
  fr: () => import('./texts.fr.json'),
  it: () => import('./texts.it.json'),
}

void i18next.use(initReactI18next).init({
  lng: 'en',
  fallbackLng: 'en',
  resources: { en: { translation: en } },
  interpolation: { escapeValue: false },
  returnNull: false,
})

export async function setLanguage(code: string): Promise<void> {
  const language = code in LANGUAGES ? code : 'en'
  if (!i18next.hasResourceBundle(language, 'translation') && loaders[language]) {
    const bundle = await loaders[language]()
    i18next.addResourceBundle(language, 'translation', bundle.default, true, true)
    if (textLoaders[language]) {
      const texts = await textLoaders[language]()
      registerTexts(language, texts.default as TextBundle)
    }
  }
  await i18next.changeLanguage(language)
  document.documentElement.lang = language
  try {
    localStorage.setItem('nexdeck.language', language)
  } catch {
    // storage may be unavailable
  }
}

/** The two buttons in the top bar of an account that has not chosen others. */
export const DEFAULT_PAIR: [string, string] = ['en', 'de']

/** The first language the browser asks for that nexdeck speaks, if any. */
export function browserLanguage(): string | null {
  try {
    const asked = navigator.languages?.length ? navigator.languages : [navigator.language]
    for (const tag of asked) {
      const code = (tag || '').toLowerCase().split('-')[0]
      if (code in LANGUAGES) return code
    }
  } catch {
    // no navigator to ask
  }
  return null
}

export function storedLanguage(): string {
  try {
    const kept = localStorage.getItem('nexdeck.language')
    if (kept && kept in LANGUAGES) return kept
  } catch {
    // storage may be unavailable
  }
  return browserLanguage() ?? 'en'
}

/**
 * The two buttons where nobody is signed in: English, and next to it the
 * language on screen, else the browser's, else German. The language on
 * screen is always one of the two, so the way back is never hidden.
 */
export function guestPair(active: string): [string, string] {
  if (active !== 'en' && active in LANGUAGES) return ['en', active]
  const browser = browserLanguage()
  return ['en', browser && browser !== 'en' ? browser : 'de']
}

/** The account's two buttons, as long as they are two languages nexdeck speaks. */
export function accountPair(pair: readonly string[] | undefined): [string, string] {
  if (pair?.length === 2 && pair[0] !== pair[1] && pair.every((code) => code in LANGUAGES)) return [pair[0], pair[1]]
  return DEFAULT_PAIR
}

export default i18next
