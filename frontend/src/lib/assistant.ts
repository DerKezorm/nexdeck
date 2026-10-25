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
  | { fact: 'depends'; count: number; names: string[]; containers: number }

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
    case 'depends':
      return [fact.count ? t('assistant.fact.depends', { count: fact.count, names: fact.names.join(', ') }) : '',
        fact.containers ? t('assistant.fact.containers', { count: fact.containers }) : ''].filter(Boolean).join(' · ')
  }
}
