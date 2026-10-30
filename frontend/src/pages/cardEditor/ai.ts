/**
 * What "Ask AI" holds while the editor is open (KARTEN-17): the description, the one request that may be running, and
 * the answer waiting to be taken or thrown away. The editor's text is never touched before "Accept" (AC-5): the answer
 * is a proposal beside it, and taking it is one step of the editor's own history, so it can be undone.
 */
import { create } from 'zustand'

import { ApiError, del, post } from '../../api/client'
import { readAt } from '../../lib/cardDocument'
import type { CardProblem } from '../../lib/customCards'
import { useAssistant } from '../../lib/assistant'
import { useCardEditor, type CardEditorState } from './store'

export type AiMode = 'new' | 'change' | 'translate'

/**
 * What the card that came back uses, as the server tells it (AC-10): the kinds of connection and the paths it reads (all of
 * them, one after the other), the form, and the buttons with the methods they use.
 */
export interface AiSummary {
  connection_kind: string | null
  path: string | null
  form: string
  buttons: boolean
  methods?: string[]
  /** The connection nexdeck asked to check the card when it was not the chosen one; only the shape of its answer went out. */
  asked?: { name: string; kind: string } | null
  /** The paths of the card nexdeck did not ask: not named by the administrator and not read by its own cards of the kind. */
  unasked?: string[]
}

export interface AiAnswer {
  ok: boolean
  yaml: string
  problems?: CardProblem[]
  summary: AiSummary
  sent: { values: boolean }
}

export interface AiProposal extends AiAnswer {
  mode: AiMode
}

interface AiState {
  /** Whether the panel is open. */
  open: boolean
  description: string
  /** "Include sample values": for the next request only (AC-3). */
  values: boolean
  running: boolean
  /** A sentence for a request that failed; the draft in the editor is as it was (EC-1, EC-4). */
  error: string
  proposal: AiProposal | null

  setOpen: (open: boolean) => void
  setDescription: (text: string) => void
  setValues: (on: boolean) => void
  ask: (mode: AiMode, connectionId: number | null, t: (key: string, options?: Record<string, unknown>) => string) => Promise<void>
  cancel: () => void
  accept: () => void
  discard: () => void
  reset: () => void
}

/** The request in flight; its answer is dropped once Cancel was pressed. */
let flying: object | null = null

const START: Pick<AiState, 'open' | 'description' | 'values' | 'running' | 'error' | 'proposal'> = {
  open: false,
  description: '',
  values: false,
  running: false,
  error: '',
  proposal: null,
}

/**
 * Whether the card on screen is still the one a new card begins as: never saved and its display not designed yet. Then
 * the description is of a whole card (`new`); anything else is a change of the card there is.
 */
export function isFresh({ slug, card }: Pick<CardEditorState, 'slug' | 'card'>): boolean {
  if (slug !== null) return false
  if (!card) return false
  return readAt(card, ['form']) === 'value' && readAt(card, ['value']) === '@'
}

/** The sentence for a failure of the request; the provider's own word for a limit or a missing balance stays in it. */
function sentenceOf(failure: unknown, t: (key: string, options?: Record<string, unknown>) => string): string {
  if (failure instanceof ApiError) {
    switch (failure.code) {
      case 'ai_unreachable':
        return t('editor.ai.error.unreachable', { message: failure.message })
      case 'ai_limit':
        return t('editor.ai.error.limit', { message: failure.message })
      case 'ai_busy':
        return t('editor.ai.error.busy')
      case 'assistant_off':
        return t('editor.ai.error.off')
      default:
        return t('editor.ai.error.failed', { message: failure.message })
    }
  }
  return t('errors.network')
}

export const useCardAi = create<AiState>((set, get) => ({
  ...START,

  setOpen: (open) => set({ open }),
  setDescription: (description) => set({ description }),
  setValues: (values) => set({ values }),

  ask: async (mode, connectionId, t) => {
    if (get().running) return
    const editor = useCardEditor.getState()
    editor.flusher?.()
    const state = useCardEditor.getState()
    const card = state.card
    const kind = card ? readAt(card, ['requires', 0]) : undefined
    const path = card ? readAt(card, ['requests', 0, 'path']) : undefined
    const known = typeof path === 'string' && path !== '/'
    // A new card needs the connection and the path of the Source step; without them the description goes as a change
    // of the card there is (the server refuses `new` without both).
    const wanted: AiMode = mode === 'new' && !(typeof kind === 'string' && kind && known && connectionId !== null) ? 'change' : mode
    const body: Record<string, unknown> = {
      mode: wanted,
      description: get().description.trim(),
      include_values: get().values,
      ...(wanted !== 'new' ? { yaml: state.text } : {}),
      ...(typeof kind === 'string' && kind ? { kind } : {}),
      ...(connectionId !== null ? { connection_id: connectionId } : {}),
      ...(known ? { path } : {}),
    }
    const mine = {}
    flying = mine
    // The tick is for this one request: it is used up when the request goes, whatever comes of it (AC-3).
    set({ running: true, error: '', proposal: null, values: false })
    try {
      const answer = await post<AiAnswer>('/cards/ai', body)
      if (flying !== mine) return
      set({ proposal: { ...answer, mode: wanted } })
    } catch (failure) {
      if (flying !== mine) return
      // The provider went while the request ran (EC-6): the buttons go with it.
      if (failure instanceof ApiError && failure.code === 'assistant_off') void useAssistant.getState().load()
      set({ error: sentenceOf(failure, t) })
    } finally {
      if (flying === mine) {
        flying = null
        set({ running: false })
      }
    }
  },

  cancel: () => {
    if (!get().running) return
    // The server stops the request of this administrator; whatever still arrives is dropped.
    flying = null
    set({ running: false })
    void del('/cards/ai').catch(() => undefined)
  },

  accept: () => {
    const proposal = get().proposal
    if (!proposal) return
    useCardEditor.getState().adopt(proposal.yaml)
    set({ proposal: null })
  },

  discard: () => set({ proposal: null }),

  reset: () => {
    if (get().running) void del('/cards/ai').catch(() => undefined)
    flying = null
    set(START)
  },
}))
