/**
 * Handing a card or an integration to someone else as a file, and taking one in (KARTEN-12).
 *
 * The server checks a file (`POST /cards/import/check`) and answers once per document in it. What it does not hand
 * back is the text of each document, so the preview cuts the file at its `---` lines itself and finds the document
 * of a card by its short name.
 */
import type { CardText } from './cardText'
import type { CardForm } from './customCards'

/** The most the server reads of one file, in bytes. */
export const IMPORT_MAX_BYTES = 512 * 1024

/** One thing wrong in a file; `line` counts from the top of the whole file. */
export interface ImportProblem {
  line: number | null
  path?: string
  message: string
}

/** A kind of connection a document reads through: a short name, or the object the card list uses. */
export type ImportSource = string | { kind: string; label?: string; icon?: string }

/** One document of a file, as the check describes it. */
export interface ImportDocument {
  type: 'card' | 'integration'
  slug?: string
  short?: string
  name?: CardText | null
  requires?: ImportSource[]
  buttons?: { label: CardText; method: string; path: string }[]
  form?: CardForm | string | null
  problems?: ImportProblem[]
  exists: boolean
  same: boolean
}

/** The answer of `POST /cards/import/check`. */
export interface ImportCheck {
  documents: ImportDocument[]
  /** Kinds a card needs that the file does not carry and the installation does not have. */
  missing_integrations: string[]
}

export type ImportChoice = 'replace' | 'copy' | 'skip'

/** The key of a document in the choices the import takes: `card:<slug>` or `integration:<short>`. */
export function documentKey(document: ImportDocument): string {
  return `${document.type}:${document.type === 'card' ? document.slug : document.short}`
}

export function sourceKind(source: ImportSource): string {
  return typeof source === 'string' ? source : source.kind
}

/** The text of every document of a file; a line of three dashes ends one. */
export function splitDocuments(text: string): string[] {
  return text
    .split(/^---[ \t]*\r?$/m)
    .map((part) => part.replace(/^\r?\n/, ''))
    .filter((part) => part.trim() !== '' && part.split(/\r?\n/).some((line) => line.trim() !== '' && !line.trim().startsWith('#')))
}

/** The text of the card with this short name in a file, or `null`. */
export function cardTextOf(text: string, slug: string): string | null {
  const own = new RegExp(`^slug:\\s*["']?${slug.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}["']?\\s*(#.*)?$`, 'm')
  return splitDocuments(text).find((part) => own.test(part) && /^nexdeck-card:/m.test(part)) ?? null
}

/** A name for a file this person saves, when the server does not give one. */
export function exportName(short: string): string {
  return `${short}.nexdeck.yaml`
}
