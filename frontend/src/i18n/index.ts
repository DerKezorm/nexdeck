import i18next from 'i18next'
import { initReactI18next } from 'react-i18next'

import en from './en.json'

/**
 * English ships in the bundle; every other language is fetched when chosen.
 * Adding a language means adding one JSON file here and one line in LANGUAGES.
 */
export const LANGUAGES: Record<string, string> = { en: 'English', de: 'Deutsch' }

const loaders: Record<string, () => Promise<{ default: Record<string, unknown> }>> = {
  de: () => import('./de.json'),
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
  }
  await i18next.changeLanguage(language)
  document.documentElement.lang = language
  try {
    localStorage.setItem('nexdeck.language', language)
  } catch {
    // storage may be unavailable
  }
}

export function storedLanguage(): string {
  try {
    return localStorage.getItem('nexdeck.language') || (navigator.language.startsWith('de') ? 'de' : 'en')
  } catch {
    return 'en'
  }
}

export default i18next
