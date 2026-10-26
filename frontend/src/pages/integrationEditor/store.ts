/**
 * What the integration editor holds while it is open (KARTEN-3): the text of the definition, the document read from
 * it, what was saved last and what the server's check found. The text is the truth: a field of the form changes it by
 * path, the YAML view replaces it, and either side reads the result.
 */
import type { Document } from 'yaml'
import { create } from 'zustand'

import { changeCard, parseCard, type CardDoc, type LocalProblem } from '../../lib/cardDocument'
import type { CardProblem } from '../../lib/customCards'

export type IntegrationView = 'form' | 'yaml'

export interface IntegrationEditorState {
  /** The short name the definition is saved under; `null` until a new one is saved. */
  short: string | null
  /** The `updated_at` read on opening; goes back with a save so that a change meanwhile is noticed. */
  base: string | null
  text: string
  /** The text as saved (or as the template began), to tell whether anything is unsaved. */
  saved: string | null
  card: CardDoc | null
  problems: LocalProblem[]
  /** The last document that was valid. */
  lastValid: CardDoc | null
  /** What the server's check or a rejected save found, for the text it checked. */
  server: { problems: CardProblem[]; text: string } | null
  view: IntegrationView
  /** A line the YAML view is asked to show. */
  focusLine: number | null
  open: (start: { short: string | null; text: string; base: string | null; saved: string | null }) => void
  setText: (text: string) => void
  change: (change: (doc: Document) => void) => void
  setView: (view: IntegrationView) => void
  goToLine: (line: number) => void
  lineShown: () => void
  setServerProblems: (problems: CardProblem[], text: string) => void
  markSaved: (short: string, text: string, base: string | null) => void
  /** Hands over what is typed in the YAML view and has not settled yet. */
  flusher: (() => void) | null
}

function read(text: string): Pick<IntegrationEditorState, 'card' | 'problems'> {
  const parsed = parseCard(text)
  return parsed.ok ? { card: parsed.card, problems: [] } : { card: null, problems: parsed.problems }
}

export const useIntegrationEditor = create<IntegrationEditorState>((set, get) => ({
  short: null,
  base: null,
  text: '',
  saved: null,
  card: null,
  problems: [],
  lastValid: null,
  server: null,
  view: 'form',
  focusLine: null,
  flusher: null,
  open: ({ short, text, base, saved }) => {
    const now = read(text)
    set({ short, base, text, saved, ...now, lastValid: now.card, server: null, view: now.card ? get().view : 'yaml', focusLine: null })
  },
  setText: (text) => {
    if (text === get().text) return
    const now = read(text)
    set((state) => ({ text, ...now, lastValid: now.card ?? state.lastValid }))
  },
  change: (change) => {
    const { card } = get()
    if (!card) return
    const next = changeCard(card, change)
    set({ text: next.text, card: next, problems: [], lastValid: next })
  },
  setView: (view) => {
    get().flusher?.()
    set({ view })
  },
  goToLine: (line) => {
    set({ view: 'yaml', focusLine: line })
  },
  lineShown: () => set({ focusLine: null }),
  setServerProblems: (problems, text) => set({ server: { problems, text } }),
  markSaved: (short, text, base) => set({ short, saved: text, base, server: null }),
}))

export const isDirty = (state: Pick<IntegrationEditorState, 'text' | 'saved'>) => state.saved === null || state.text !== state.saved

/** The server's problems, while they are still about the text on screen. */
export function currentServerProblems(state: IntegrationEditorState): CardProblem[] {
  return state.server && state.server.text === state.text ? state.server.problems : []
}
