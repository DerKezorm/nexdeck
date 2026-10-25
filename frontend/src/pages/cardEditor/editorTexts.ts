/**
 * The words of the card editor come with the editor, not with every board: only administrators who build a card
 * read them. English is part of this chunk; another language follows a moment later, the way `lib/lazyTexts.ts`
 * does it for the chat.
 */
import i18next from 'i18next'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import editorEn from '../../i18n/editor.en.json'

i18next.addResourceBundle('en', 'translation', editorEn, true, true)

const loaders: Partial<Record<string, () => Promise<{ default: unknown }>>> = {
  de: () => import('../../i18n/editor.de.json'),
  es: () => import('../../i18n/editor.es.json'),
  fr: () => import('../../i18n/editor.fr.json'),
  it: () => import('../../i18n/editor.it.json'),
}

/** Whether the editor's words are there in the language on screen. */
export function useEditorTexts(): boolean {
  const { i18n } = useTranslation()
  const language = i18n.language
  const load = loaders[language]
  const [ready, setReady] = useState<string | null>(load ? null : language)
  useEffect(() => {
    if (!load) {
      setReady(language)
      return
    }
    let gone = false
    void load()
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
  }, [language, load, i18n])
  return ready === language
}
