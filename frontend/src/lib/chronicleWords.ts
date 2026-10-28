/**
 * The words for lines of the chronicle that only some installations have: a press over MCP.
 *
 * They live in the MCP texts (``mcp.<language>.json``), which are not in the first load. A page that shows such
 * a line fetches them once, here, and draws again; the fetch is its own piece, so the page that does not show
 * one never pays for it.
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { ChronicleLine } from './chronicle'

const fetching = new Map<string, Promise<void>>()

/** The MCP texts in ``language``, fetched once. */
export function loadChronicleWords(language: string): Promise<void> {
  let pending = fetching.get(language)
  if (!pending) {
    pending = import('./mcpTexts').then((module) => module.loadMcpTexts(language))
    fetching.set(language, pending)
  }
  return pending
}

/** Makes sure the words are there when any of these lines needs them, and draws the page again when they arrive. */
export function useChronicleWords(lines: Pick<ChronicleLine, 'kind'>[]): void {
  const { i18n } = useTranslation()
  const needed = lines.some((line) => line.kind === 'mcp_call')
  const [, arrived] = useState('')
  useEffect(() => {
    if (!needed) return
    let gone = false
    void loadChronicleWords(i18n.language).then(() => {
      if (!gone) arrived(i18n.language)
    })
    return () => {
      gone = true
    }
  }, [needed, i18n.language])
}
