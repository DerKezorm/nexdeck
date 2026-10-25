/**
 * What the card editor holds while it is open (KARTEN-9, KARTEN-10): the text, the document read from it, the last
 * version that was valid, whether anything is unsaved, and every step back and forward since the editor opened.
 *
 * The text is the truth. A field of the editor changes the document by path (`set`, `remove`, `change`), the YAML view
 * replaces the text (`setText`); either way the other side reads the result. While the text is not a valid document,
 * `card` is `null`, the editor's fields are closed and `lastValid` is what the preview and the fields last saw.
 */
import { useCallback } from 'react'
import type { Document } from 'yaml'
import { create } from 'zustand'

import { changeCard, deleteAt, parseCard, pathText, readAt, setAt, type CardDoc, type CardPath, type LocalProblem } from '../../lib/cardDocument'
import type { CardProblem } from '../../lib/customCards'
import type { ProbeState } from './probe'

export type EditorView = 'editor' | 'yaml'
/** The steps of this version; Buttons (KARTEN-8) comes with a later one. */
export type EditorStep = 'source' | 'look' | 'rules' | 'texts'
export const STEPS: EditorStep[] = ['source', 'look', 'rules', 'texts']

/** How many steps back the editor keeps. A card is at most 60,000 characters, so this stays a few megabytes. */
const HISTORY = 200
/** Typing in one field, or in the YAML view, within this long is one step back (KARTEN-9 EC-10). */
export const TYPING_MS = 1000

export interface CardEditorState {
  /** The short name the card is saved under; `null` until a new card is saved for the first time. */
  slug: string | null
  /** When the saved card was last changed, as read on opening (`updated_at`); goes back with a save (decision 7). */
  base: string | null
  text: string
  /** The document of `text`, `null` while the text is not one. */
  card: CardDoc | null
  /** Why `text` is not a document, each at its line (KARTEN-10 AC-2, AC-5). */
  problems: LocalProblem[]
  /** The last document that was valid, and when (KARTEN-10 AC-5, EC-5). */
  lastValid: { card: CardDoc; at: number } | null
  /** The text as it was last saved; `null` for a card that has never been saved. */
  savedText: string | null
  past: string[]
  future: string[]
  /** The field typed in last and when, so that typing on in it makes no new step back. */
  typing: { group: string; at: number } | null
  view: EditorView
  step: EditorStep
  /** What the server found in `serverFor` (on saving, or the check of the YAML view); stale once the text changes. */
  serverProblems: CardProblem[]
  serverFor: string | null
  /** Hands what was typed in the YAML view to the store at once; the view sets it while it is open. */
  flusher: (() => void) | null
  /** A line the YAML view is asked to show and put the cursor on, once. */
  focusLine: number | null
  /** The clock; tests set their own. */
  now: () => number
  /**
   * The connection the Source step probes with and the preview reads from (decision 4): never part of the card,
   * which names kinds only. `null` until somebody picks one; the first fitting one is used until then.
   */
  integrationId: number | null
  /** The probes of this visit by request id. ⚠️ The service's own data: kept in memory only, never in a draft (EC-4). */
  probes: Record<string, ProbeState>

  /** Start over with a card: a saved one (`saved`), a new one, or a draft brought back. */
  open: (input: { slug: string | null; text: string; base: string | null; saved: string | null; view?: EditorView }) => void
  /** Replace the whole text, as the YAML view does. */
  setText: (text: string, group?: string) => void
  /** Change the document; the text follows with every untouched line as it was. Nothing happens while it is invalid. */
  change: (edit: (doc: Document) => void, group?: string) => void
  set: (path: CardPath, value: unknown, group?: string) => void
  remove: (path: CardPath, group?: string) => void
  undo: () => void
  redo: () => void
  /** Switch between editor and YAML; the editor stays closed while the text is invalid. Says whether it switched. */
  setView: (view: EditorView) => boolean
  setStep: (step: EditorStep) => void
  /** The card was saved as `text` under `slug`. */
  saved: (slug: string, text: string, base: string | null) => void
  setServerProblems: (problems: CardProblem[], forText: string) => void
  /** Switch to the YAML view at this line ("Open in YAML", a problem clicked). */
  goToLine: (line: number) => void
  lineShown: () => void
  setIntegration: (id: number | null) => void
  setProbe: (requestId: string, probe: ProbeState | null) => void
}

/**
 * A text with Windows or old Mac line ends (a card saved through the API from another editor) becomes LF on entering
 * the store: the document writer works on LF lines, and with a trailing carriage return on every line none of them
 * would count as untouched. The YAML view hands over LF in any case.
 */
export const lineFeeds = (text: string): string => text.replace(/\r\n?/g, '\n')

function reading(text: string, previous: CardEditorState['lastValid'], at: number) {
  const parsed = parseCard(text)
  if (parsed.ok) return { text, card: parsed.card, problems: [] as LocalProblem[], lastValid: { card: parsed.card, at } }
  return { text, card: null, problems: parsed.problems, lastValid: previous }
}

export const useCardEditor = create<CardEditorState>((set, get) => {
  /** One step: the text before goes on the stack, unless this is more typing in the same field. */
  const step = (next: Partial<CardEditorState> & { text: string }, group?: string) => {
    const state = get()
    if (next.text === state.text) return
    const at = state.now()
    const more = group !== undefined && state.typing?.group === group && at - state.typing.at < TYPING_MS
    set({
      ...next,
      past: more ? state.past : [...state.past, state.text].slice(-HISTORY),
      future: [],
      typing: group === undefined ? null : { group, at },
    })
  }

  return {
    slug: null,
    base: null,
    text: '',
    card: null,
    problems: [],
    lastValid: null,
    savedText: null,
    past: [],
    future: [],
    typing: null,
    view: 'editor',
    step: 'source',
    serverProblems: [],
    serverFor: null,
    focusLine: null,
    flusher: null,
    now: () => Date.now(),
    integrationId: null,
    probes: {},

    open: ({ slug, text: given, base, saved: savedGiven, view }) => {
      const text = lineFeeds(given)
      const saved = savedGiven === null ? null : lineFeeds(savedGiven)
      const read = reading(text, null, get().now())
      set({
        ...read,
        slug,
        base,
        savedText: saved,
        past: [],
        future: [],
        typing: null,
        // An invalid text opens where it can be mended.
        view: read.card ? (view ?? 'editor') : 'yaml',
        step: 'source',
        serverProblems: [],
        serverFor: null,
        focusLine: null,
        integrationId: null,
        probes: {},
      })
    },

    setText: (given, group) => {
      const text = lineFeeds(given)
      const state = get()
      if (text === state.text) return
      step(reading(text, state.lastValid, state.now()), group)
    },

    change: (edit, group) => {
      const state = get()
      if (!state.card) return
      const card = changeCard(state.card, edit)
      if (card.text === state.text) return
      step({ text: card.text, card, problems: [], lastValid: { card, at: state.now() } }, group)
    },

    set: (path, value, group) => get().change((doc) => setAt(doc, path, value), group),
    remove: (path, group) => get().change((doc) => deleteAt(doc, path), group),

    undo: () => {
      get().flusher?.()
      const state = get()
      const back = state.past[state.past.length - 1]
      if (back === undefined) return
      set({
        ...reading(back, state.lastValid, state.now()),
        past: state.past.slice(0, -1),
        future: [...state.future, state.text],
        typing: null,
      })
    },

    redo: () => {
      const state = get()
      const forward = state.future[state.future.length - 1]
      if (forward === undefined) return
      set({
        ...reading(forward, state.lastValid, state.now()),
        future: state.future.slice(0, -1),
        past: [...state.past, state.text].slice(-HISTORY),
        typing: null,
      })
    },

    setView: (view) => {
      get().flusher?.()
      if (view === 'editor' && !get().card) return false
      set({ view, typing: null })
      return true
    },

    setStep: (one) => set({ step: one }),

    saved: (slug, text, base) => set({ slug, savedText: text, base, serverProblems: [], serverFor: null }),

    setServerProblems: (problems, forText) => set({ serverProblems: problems, serverFor: forText }),

    goToLine: (line) => set({ view: 'yaml', focusLine: line, typing: null }),
    lineShown: () => set({ focusLine: null }),

    setIntegration: (id) => set({ integrationId: id, probes: {} }),
    setProbe: (requestId, probe) =>
      set((state) => {
        const probes = { ...state.probes }
        if (probe) probes[requestId] = probe
        else delete probes[requestId]
        return { probes }
      }),
  }
})

/** Whether there is anything to lose: a card never saved, or a text that differs from the saved one. */
export function isDirty(state: Pick<CardEditorState, 'text' | 'savedText'>): boolean {
  return state.savedText === null || state.text !== state.savedText
}

const NONE: CardProblem[] = []

/** The server's problems that still belong to the text on screen. */
export function currentServerProblems(state: Pick<CardEditorState, 'serverProblems' | 'serverFor' | 'text'>): CardProblem[] {
  // ⚠️ The same empty list every time: a selector that hands out a new one makes React render for ever.
  return state.serverFor === state.text ? state.serverProblems : NONE
}

/**
 * One field of the card for a step of the editor: its value as plain data, and how to set it. `undefined` sets
 * nothing, it removes the field. Typing in the field is one step back (KARTEN-9 EC-10).
 *
 * While the text is invalid the field shows the last valid version and changes nothing.
 */
export function useCardField<T = unknown>(path: CardPath): [T | undefined, (value: T | undefined) => void] {
  const key = pathText(path)
  const card = useCardEditor((state) => state.card ?? state.lastValid?.card ?? null)
  const value = card ? (readAt(card, path) as T | undefined) : undefined
  const write = useCallback(
    (next: T | undefined) => {
      const editor = useCardEditor.getState()
      if (next === undefined) editor.remove(path, `field:${key}`)
      else editor.set(path, next, `field:${key}`)
    },
    // The path is a new array on every render; its text is what counts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [key],
  )
  return [value, write]
}

/** The server's problems for one field, to show beside it (KARTEN-9 AC-13). */
export function useFieldProblems(path: CardPath): CardProblem[] {
  const key = pathText(path)
  return useCardEditor((state) => currentServerProblems(state)).filter((problem) => problem.path === key)
}
