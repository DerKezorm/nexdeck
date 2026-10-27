/**
 * What the management of custom cards (KARTEN-11) reads from the server, and how a problem in a card's text is worded.
 *
 * The names and texts of a card are the author's own (`CardText`), so they are picked in the viewer's language and never
 * passed through nexdeck's table of translations (KARTEN-1 AC-5, AC-6).
 */
import type { TFunction } from 'i18next'

import { ApiError } from '../api/client'
import type { CardText } from './cardText'

export type CardForm = 'value' | 'stats' | 'list' | 'posters' | 'builder'

/** A kind of connection a card reads through, as people read it. */
/**
 * A path the built-in cards of a kind of service ask, found in the code, with the cards that ask it (English names, as the
 * library has them). No card behind it: the path is from the documentation of the service.
 */
export interface CardRead {
  path: string
  widgets: { kind: string; label: string }[]
}
export interface CardReads {
  reads: CardRead[]
}

export interface CardSource {
  kind: string
  label: string
  icon: string
  /** The category of the service in the library; older answers have none. */
  category?: string
  /** An integration an administrator described (KARTEN-3); its kind begins with `custom:`. */
  custom?: boolean
}

/** Whether a kind of service is an own integration: it carries the mark "Custom". */
export function isOwnKind(source: { kind: string; custom?: boolean }): boolean {
  return source.custom === true || source.kind.startsWith('custom:')
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
  /** A card of blocks: the block that is its number (KARTEN-7 AC-8). Only a card that has one goes into Key figures. */
  main?: string | null
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

/**
 * A problem in words: the sentence nexdeck has for its code (`errors.card`), with the blanks filled in, else the
 * server's English sentence.
 *
 * ⚠️ A blank that names a kind of value (`expected`, `what`) is a code too, and is worded through `errors.cardTerms`.
 * Where it is a list of choices (`must be one of …`), it stays as it came.
 */
export function problemText(t: TFunction, problem: CardProblem): string {
  const params: Record<string, unknown> = { ...problem.params }
  for (const name of ['expected', 'what']) {
    const value = params[name]
    if (typeof value === 'string') params[name] = t(`errors.cardTerms.${value}`, { defaultValue: value })
  }
  return t(`errors.card.${problem.code}`, { ...params, defaultValue: problem.message })
}

/** The source of a card as one line: the kinds it can read through. */
export function sourceLine(card: { requires: CardSource[] }): string {
  return card.requires.map((one) => one.label).join(', ')
}
