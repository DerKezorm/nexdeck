/**
 * What the steps of the guided way read alike: the kind of service, the one request, its answer as a table, the
 * suggestion it follows, and how the card's display is made once a new answer is in.
 */
import i18next from 'i18next'
import { useMemo } from 'react'

import { readAt, readIn, setAt, type CardPath } from '../../../lib/cardDocument'
import { suggestionOf, wordsKey, type CardSuggestion } from '../../../lib/cardSuggestions'
import { runProbe } from '../connections'
import type { ProbeNode } from '../probe'
import { useCardEditor } from '../store'
import { slugFrom } from '../templates'
import { shapeFor, suggestedForm, tableOf, writeShape, writeThresholds, type AnswerTable } from './guided'

export interface GuidedAnswer {
  kind: string | undefined
  requestId: string
  path: string
  suggestion: CardSuggestion | null
  probe: ReturnType<typeof useCardEditor.getState>['probes'][string] | undefined
  /** The answer to the path the card has now, `null` while it is not in. */
  tree: ProbeNode | null
}

export function useGuidedAnswer(): GuidedAnswer {
  const card = useCardEditor((state) => state.card ?? state.lastValid?.card ?? null)
  const kinds = card ? readAt(card, ['requires']) : undefined
  const kind = Array.isArray(kinds) && kinds.length ? String(kinds[0]) : undefined
  const requestId = String((card && readAt(card, ['requests', 0, 'id'])) ?? '')
  const path = String((card && readAt(card, ['requests', 0, 'path'])) ?? '')
  const probe = useCardEditor((state) => (requestId ? state.probes[requestId] : undefined))
  const suggestion = suggestionOf(kind, path)
  const tree = probe?.status === 'done' && probe.path === path ? probe.answer.tree : null
  return { kind, requestId, path, suggestion, probe, tree }
}

/** The answer as a table, of the list `wanted` when the card reads one. */
export function useAnswerTable(wanted?: string): AnswerTable | null {
  const { tree, suggestion } = useGuidedAnswer()
  return useMemo(() => (tree ? tableOf(tree, suggestion, wanted) : null), [tree, suggestion, wanted])
}

/** Ask the service for a path of the guided way; once the answer is in, the display is made from it (`shapeNow`). */
export function askFor(requestId: string, path: string, integrationId: number | null) {
  useCardEditor.setState({ pendingShape: path })
  if (integrationId !== null) void runProbe(requestId, integrationId, path)
}

/** A text the guided way knows in English and in the language on screen: a plain string in English, else both. */
function writeKnown(doc: Parameters<typeof writeShape>[0], path: CardPath, english: string, own: string, language: string) {
  setAt(doc, path, language === 'en' || own === english ? english : { en: english, [language]: own })
}

/**
 * Make the card's display from the answer that is in (U6): the form the content suggests, filled from the columns
 * or the suggestion's own start, and a name when the author has not given one.
 */
export function shapeNow(tree: ProbeNode, suggestion: CardSuggestion | null, kind: string | undefined, serviceName: string) {
  const editor = useCardEditor.getState()
  const language = i18next.language
  const english = i18next.getFixedT('en')
  const table = tableOf(tree, suggestion)
  const form = suggestedForm(table, suggestion)
  const shape = shapeFor(form, table, suggestion)
  const preset = suggestion?.preset?.form === form ? suggestion.preset : null
  const words = (part: 'title' | 'label') => (suggestion && kind ? [english(wordsKey(kind, suggestion, part)), i18next.t(wordsKey(kind, suggestion, part))] : [serviceName, serviceName])
  const [nameEn, nameOwn] = preset?.form === 'value' && preset.label ? words('label') : words('title')
  let named: string | null = null
  editor.change((doc) => {
    writeShape(doc, shape)
    if (preset?.form === 'value') {
      if (preset.label) {
        const [labelEn, labelOwn] = words('label')
        writeKnown(doc, ['value', 'label'], labelEn, labelOwn, language)
      }
      if (preset.warn !== undefined) writeThresholds(doc, ['value'], preset.warn, null)
    }
    const name = readIn(doc, ['name'])
    const current = typeof name === 'string' ? name : name && typeof name === 'object' ? String((name as Record<string, unknown>).en ?? '') : ''
    if (nameEn && (!current.trim() || current === editor.autoName)) {
      writeKnown(doc, ['name'], nameEn, nameOwn, language)
      if (editor.slug === null) setAt(doc, ['slug'], slugFrom(nameEn) || 'new-card')
      named = nameEn
    }
  })
  useCardEditor.setState((state) => ({ shapedPath: state.pendingShape ?? state.shapedPath, pendingShape: null, autoName: named ?? state.autoName }))
}
