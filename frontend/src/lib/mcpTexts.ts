/**
 * The words of the MCP pages, the settings and the approval question, loaded
 * with the part that needs them and not with every board (same idea as
 * ``lazyTexts.ts``). English comes with this module, so whatever imports it has
 * its words at once; another language follows a moment later.
 *
 * ⚠️ Kept apart from ``lazyTexts.ts`` on purpose: that module sits in the first
 * load because the chat button needs it, and these words must not.
 */
import i18next from 'i18next'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import mcpEn from '../i18n/mcp.en.json'

i18next.addResourceBundle('en', 'translation', mcpEn, true, true)

const loaders: Record<string, () => Promise<{ default: unknown }>> = {
  de: () => import('../i18n/mcp.de.json'),
  es: () => import('../i18n/mcp.es.json'),
  fr: () => import('../i18n/mcp.fr.json'),
  it: () => import('../i18n/mcp.it.json'),
}

/** Puts the words of ``language`` in place. A language that cannot be fetched stays English rather than blank. */
export async function loadMcpTexts(language: string): Promise<void> {
  const load = loaders[language]
  if (!load) return
  try {
    const bundle = await load()
    i18next.addResourceBundle(language, 'translation', bundle.default, true, true)
  } catch {
    // English stands in.
  }
}

/** Whether the MCP words are there in the language on screen. */
export function useMcpTexts(): boolean {
  const { i18n } = useTranslation()
  const language = i18n.language
  const [ready, setReady] = useState<string | null>(language === 'en' || !loaders[language] ? language : null)
  useEffect(() => {
    let gone = false
    void loadMcpTexts(language).then(() => {
      if (!gone) setReady(language)
    })
    return () => {
      gone = true
    }
  }, [language])
  return ready === language
}
