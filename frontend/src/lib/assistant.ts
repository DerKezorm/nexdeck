/**
 * The assistant ("Ask nexdeck", roadmap M3): what the chat needs to know and
 * the words for what a button would hit.
 *
 * Administrators only. The button next to the bell shows once a provider is
 * set up under System; the panel itself is loaded the first time it opens.
 */
import type { TFunction } from 'i18next'
import { create } from 'zustand'

import { get } from '../api/client'

export interface AssistantState {
  ready: boolean
  provider: 'off' | 'anthropic' | 'openai'
  model: string
  leaves_the_house: boolean
  keep_days: number
}

/** Where a chip under an answer leads: a card, or the chronicle. */
export interface Citation {
  label: string
  target?: { board: string; page: string; widget: number }
  chronicle?: boolean
}

/** What a button would hit, as facts the browser words itself. */
export type Fact =
  | { fact: 'up'; text: string }
  | { fact: 'streams'; count: number; names: string[] }
  | { fact: 'downloads'; count: number }
  | { fact: 'devices'; count: number; names: string[] }
  | { fact: 'last_run'; at: string }

export interface Proposal {
  card_id: number
  card: string
  row: string
  action: string
  label: string
  danger: boolean
  params: Record<string, unknown>
  impact: Fact[]
}

export interface Permission {
  kind: 'log'
  card_id: number
  container: string
  grant: string
}

export interface Reply {
  text: string
  refused: boolean
  citations: Citation[]
  proposals: Proposal[]
  permissions: Permission[]
}

export type Turn = ({ me: true; text: string } | ({ me: false } & Reply))

export interface ConversationView {
  id: number
  title: string
  updated_at: string
  turns: Turn[]
}

export interface ConversationRow {
  id: number
  title: string
  updated_at: string
}

interface Store {
  state: AssistantState | null
  open: boolean
  /** A question handed over from Ctrl K, sent as soon as the panel is there. */
  asking: string
  load: () => Promise<void>
  setOpen: (open: boolean) => void
  ask: (question: string) => void
  taken: () => void
}

export const useAssistant = create<Store>((set) => ({
  state: null,
  open: false,
  asking: '',
  load: async () => {
    try {
      set({ state: await get<AssistantState>('/assistant') })
    } catch {
      set({ state: null })
    }
  },
  setOpen: (open) => set({ open }),
  ask: (question) => set({ open: true, asking: question }),
  taken: () => set({ asking: '' }),
}))

/** One fact about a button, as a sentence in the reader's language. */
export function factText(t: TFunction, fact: Fact): string {
  switch (fact.fact) {
    case 'up':
      return t('assistant.fact.up', { text: fact.text })
    case 'streams':
      return t('assistant.fact.streams', { count: fact.count, names: fact.names.join(', ') })
    case 'downloads':
      return t('assistant.fact.downloads', { count: fact.count })
    case 'devices':
      return t('assistant.fact.devices', { count: fact.count, names: fact.names.join(', ') })
    case 'last_run':
      return t('assistant.fact.lastRun', { when: new Date(fact.at).toLocaleString() })
  }
}

/** Which day heading a conversation goes under in the list. */
export function dayGroup(at: string, now: Date = new Date()): 'today' | 'yesterday' | 'week' | 'older' {
  const then = new Date(at)
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const day = 24 * 60 * 60 * 1000
  if (then.getTime() >= start) return 'today'
  if (then.getTime() >= start - day) return 'yesterday'
  if (then.getTime() >= start - 6 * day) return 'week'
  return 'older'
}

/**
 * The few marks an answer may carry: paragraphs, "- " list items and
 * **bold**. Parsed into pieces, never into HTML: what a model writes is not
 * trusted as markup.
 */
export type Block = { kind: 'p'; parts: Part[] } | { kind: 'ul'; items: Part[][] }
export type Part = { text: string; bold: boolean }

export function inline(text: string): Part[] {
  const pieces = text.split('**')
  // An odd number of marks leaves the last one as it was written.
  const closed = pieces.length % 2 === 1 ? pieces.length : pieces.length - 1
  const parts: Part[] = []
  pieces.forEach((piece, index) => {
    const shown = index >= closed ? `**${piece}` : piece
    if (shown) parts.push({ text: shown, bold: index < closed && index % 2 === 1 })
  })
  return parts
}

export function blocks(text: string): Block[] {
  const out: Block[] = []
  for (const chunk of text.split(/\n\s*\n/)) {
    const lines = chunk.split('\n').map((line) => line.trimEnd()).filter((line) => line.trim())
    let paragraph: string[] = []
    const flush = () => {
      if (paragraph.length) out.push({ kind: 'p', parts: inline(paragraph.join(' ')) })
      paragraph = []
    }
    for (const line of lines) {
      const item = /^\s*(?:[-*•]|\d+[.)])\s+(.*)$/.exec(line)
      if (item) {
        flush()
        const last = out[out.length - 1]
        if (last?.kind === 'ul') last.items.push(inline(item[1]))
        else out.push({ kind: 'ul', items: [inline(item[1])] })
      } else paragraph.push(line.trim())
    }
    flush()
  }
  return out
}
