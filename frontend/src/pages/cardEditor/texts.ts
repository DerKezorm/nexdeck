/**
 * The texts of a card for the Texts step (KARTEN-9 AC-8): which texts a card has, which languages it is written in,
 * and how one text in one language is written into the card.
 *
 * A text is a string while it is English only (`name: Queue`) and a map once a second language comes
 * (`name: {en: Queue, de: Warteschlange}`); that is how the definition writes it (KARTEN-1 AC-5).
 */
import type { Document } from 'yaml'

import { deleteAt, expandValueRef, readAt, readIn, setAt, type CardDoc, type CardPath } from '../../lib/cardDocument'

/** One text of the card: where it stands and what it is called on screen. */
export interface TextSpot {
  id: string
  path: CardPath
  /** The key of the words that name it, and their blanks. */
  label: { key: string; number?: number }
  required?: boolean
  /** A label or unit of a value: the value is written out long before the text can be set on it. */
  valueRef?: CardPath
  long?: boolean
}

/** The texts this card has, in the order the card shows them. */
export function textSpots(card: CardDoc): TextSpot[] {
  const spots: TextSpot[] = [
    { id: 'name', path: ['name'], label: { key: 'editor.texts.name' }, required: true },
    { id: 'description', path: ['description'], label: { key: 'editor.texts.description' }, long: true },
  ]
  const form = readAt(card, ['form'])
  const valueTexts = (path: CardPath, number?: number) => {
    const id = path.join('.')
    spots.push(
      { id: `${id}.label`, path: [...path, 'label'], label: { key: number ? 'editor.texts.labelOf' : 'editor.texts.label', number }, valueRef: path },
      { id: `${id}.unit`, path: [...path, 'unit'], label: { key: number ? 'editor.texts.unitOf' : 'editor.texts.unit', number }, valueRef: path },
    )
  }
  if (form === 'value' && readAt(card, ['value']) !== undefined) valueTexts(['value'])
  if (form === 'stats') {
    const stats = readAt(card, ['stats'])
    if (Array.isArray(stats)) stats.forEach((_, index) => valueTexts(['stats', index], index + 1))
  }
  if (form === 'list' && readAt(card, ['item', 'value']) !== undefined) {
    spots.push({ id: 'item.value.unit', path: ['item', 'value', 'unit'], label: { key: 'editor.texts.rowUnit' }, valueRef: ['item', 'value'] })
  }
  if (form === 'list' || form === 'posters') spots.push({ id: 'empty', path: ['empty'], label: { key: 'editor.texts.empty' } })
  return spots
}

/** English first, then every language the card is written in, in the order they first appear. */
export function languagesOf(card: CardDoc, spots: TextSpot[]): string[] {
  const found = ['en']
  for (const spot of spots) {
    const value = readAt(card, spot.path)
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      for (const code of Object.keys(value)) if (!found.includes(code)) found.push(code)
    }
  }
  return found
}

/** The text of one spot in one language, `''` when it is not written. */
export function textIn(card: CardDoc, spot: TextSpot, language: string): string {
  const value = readAt(card, spot.path)
  if (typeof value === 'string') return language === 'en' ? value : ''
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const one = (value as Record<string, unknown>)[language]
    return typeof one === 'string' ? one : ''
  }
  return ''
}

/**
 * Write `text` in `language` for one spot. An empty text removes that language; an empty English removes the whole
 * text, except a required one (the name), which stays empty for the check to name.
 */
export function writeText(doc: Document, spot: TextSpot, language: string, text: string): void {
  const current = readIn(doc, spot.path)
  const many = current !== null && typeof current === 'object' && !Array.isArray(current)
  if (text && spot.valueRef) expandValueRef(doc, spot.valueRef)
  if (many) {
    if (text || (language === 'en' && spot.required)) setAt(doc, [...spot.path, language], text)
    else deleteAt(doc, [...spot.path, language])
    const left = readIn(doc, spot.path)
    if (left && typeof left === 'object' && Object.keys(left).length === 0) deleteAt(doc, spot.path)
    return
  }
  if (language === 'en') {
    if (text || spot.required) setAt(doc, spot.path, text)
    else deleteAt(doc, spot.path)
    return
  }
  if (text) setAt(doc, spot.path, { en: typeof current === 'string' ? current : '', [language]: text })
}

/** Take one language out of every text of the card. */
export function removeLanguage(doc: Document, spots: TextSpot[], language: string): void {
  for (const spot of spots) {
    const current = readIn(doc, spot.path)
    if (current && typeof current === 'object' && !Array.isArray(current) && language in current) writeText(doc, spot, language, '')
  }
}

/** Languages offered by "+ Language"; any other code can be written in the YAML view. */
export const OFFERED_LANGUAGES = ['de', 'es', 'fr', 'it', 'nl', 'pt', 'pl', 'sv', 'da', 'nb', 'fi', 'cs', 'tr', 'ja', 'zh', 'ko']
