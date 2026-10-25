/**
 * What the management of custom cards (KARTEN-11) reads from the server, and how a problem in a card's text is worded.
 *
 * The names and texts of a card are the author's own (`CardText`), so they are picked in the viewer's language and never
 * passed through nexdeck's table of translations (KARTEN-1 AC-5, AC-6).
 */
import type { TFunction } from 'i18next'

import { ApiError } from '../api/client'
import type { CardText } from './cardText'

export type CardForm = 'value' | 'stats' | 'list' | 'posters'

/** A kind of connection a card reads through, as people read it. */
export interface CardSource {
  kind: string
  label: string
  icon: string
}

export interface CardBoard {
  id: number
  slug: string
  name: string
}

/** One row of System > Custom cards. */
export interface CustomCardRow {
  slug: string
  name: CardText
  description?: CardText | null
  form: CardForm
  version: string
  author?: string | null
  requires: CardSource[]
  origin: 'local' | 'shop'
  shop_version: string
  boards: CardBoard[]
  users_may_place: boolean
  updated_at: string
}

export interface CardList {
  cards: CustomCardRow[]
  limit: number
}

/** A card this account may place, with the connections it could be placed on right now. */
export interface LibraryCard {
  slug: string
  name: CardText
  description?: CardText | null
  form: CardForm
  version: string
  requires: CardSource[]
  fits: { id: number; name: string; kind: string }[]
}

/** One thing wrong in the text of a card, from the server's check. */
export interface CardProblem {
  code: string
  message: string
  path: string
  line: number | null
  params: Record<string, unknown>
}

/** The problems a rejected save carries, if it carries any. */
export function problemsOf(failure: unknown): CardProblem[] {
  if (!(failure instanceof ApiError)) return []
  const list = failure.detail?.problems
  return Array.isArray(list) ? (list as CardProblem[]) : []
}

/** A problem in words: translated when nexdeck knows its code, else the server's English sentence. */
export function problemText(t: TFunction, problem: CardProblem): string {
  return t(`cards.problem.${problem.code}`, { ...problem.params, defaultValue: problem.message })
}

/** The source of a card as one line: the kinds it can read through. */
export function sourceLine(card: { requires: CardSource[] }): string {
  return card.requires.map((one) => one.label).join(', ')
}

/** The text a new card starts from. It is a working card, so Save succeeds as it stands. */
export const STARTER = `# A custom card asks a connection something and shows what comes back.
nexdeck-card: 1
slug: my-card
name: My card
version: "1.0.0"
requires: [sonarr]
requests:
  - id: queue
    path: /api/v3/queue
form: value
value:
  path: totalRecords
  label: Waiting
demo:
  queue: {totalRecords: 4}
`
