/**
 * The words of the skin editor and the Skins page, English included, fetched
 * with those pages and never with a board: only administrators who build skins
 * read them (lib/lazyTexts.ts carries English with it, which here would put it
 * into the first load through the assistant).
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

const loaders: Record<string, () => Promise<{ default: unknown }>> = {
  en: () => import('../../i18n/skins.en.json'),
  de: () => import('../../i18n/skins.de.json'),
  es: () => import('../../i18n/skins.es.json'),
  fr: () => import('../../i18n/skins.fr.json'),
  it: () => import('../../i18n/skins.it.json'),
}

/** Whether the words are there in the language on screen; English first, so a missing language still reads. */
export function useSkinTexts(): boolean {
  const { i18n } = useTranslation()
  const language = i18n.language
  const [ready, setReady] = useState<string | null>(null)
  useEffect(() => {
    let gone = false
    const wanted = [...new Set(['en', language])].filter((code) => loaders[code])
    void Promise.all(wanted.map((code) => loaders[code]().then((bundle) => i18n.addResourceBundle(code, 'translation', bundle.default, true, true))))
      .catch(() => undefined)
      .finally(() => {
        if (!gone) setReady(language)
      })
    return () => {
      gone = true
    }
  }, [language, i18n])
  return ready === language
}
