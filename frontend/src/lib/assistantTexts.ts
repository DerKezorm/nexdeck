/**
 * The chat's words (roadmap M3), loaded with the chat and its setting page
 * rather than with every board: only administrators who set up a provider
 * ever read them. The title and the facts about a button stay in the main
 * language files; the button, Ctrl K and the question before a press use them.
 *
 * English comes with this module, so whatever imports it has its words at
 * once; another language follows a moment later.
 */
import i18next from 'i18next'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import english from '../i18n/assistant.en.json'

i18next.addResourceBundle('en', 'translation', english, true, true)

const loaders: Record<string, () => Promise<{ default: unknown }>> = {
  de: () => import('../i18n/assistant.de.json'),
  es: () => import('../i18n/assistant.es.json'),
  fr: () => import('../i18n/assistant.fr.json'),
  it: () => import('../i18n/assistant.it.json'),
}

/** Whether the chat's words are there in the language on screen. */
export function useAssistantTexts(): boolean {
  const { i18n } = useTranslation()
  const language = i18n.language
  const [ready, setReady] = useState<string | null>(language === 'en' || !loaders[language] ? language : null)
  useEffect(() => {
    if (language === 'en' || !loaders[language]) {
      setReady(language)
      return
    }
    let gone = false
    void loaders[language]()
      .then((bundle) => {
        i18n.addResourceBundle(language, 'translation', bundle.default, true, true)
      })
      .catch(() => undefined)
      // In English rather than not at all, when the words of a language cannot be fetched.
      .finally(() => {
        if (!gone) setReady(language)
      })
    return () => {
      gone = true
    }
  }, [language, i18n])
  return ready === language
}
