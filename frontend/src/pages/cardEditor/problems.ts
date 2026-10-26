/**
 * What is wrong with a card, in words: the YAML's own problems (found in this browser) and the server's (found on
 * saving or by the check), both in the language on screen.
 */
import type { TFunction } from 'i18next'

import type { LocalProblem } from '../../lib/cardDocument'
import { problemText, type CardProblem } from '../../lib/customCards'

export function localProblemText(t: TFunction, problem: LocalProblem): string {
  return t(`editor.local.${problem.code}`, { reason: problem.reason ?? '' })
}

export function serverProblemText(t: TFunction, problem: CardProblem): string {
  return problemText(t, problem)
}

/**
 * Where in the card a problem lies, in the words of the guided way ("The number", "Main text") instead of the path
 * of the field (`value.total.rows.filter[0].value`); `null` where there is no such word, then nothing is named.
 */
export function partOfProblem(t: TFunction, path: string): string | null {
  const word = (key: string, options?: Record<string, unknown>) => t(`editor.guided.part.${key}`, options)
  const stat = /^stats\[(\d+)\]/.exec(path)
  if (/^name\b/.test(path)) return word('name')
  if (/^slug\b/.test(path)) return word('slug')
  if (/^(value|stats\[\d+\])(\..*)?\.rules\b/.test(path) || /^rules\b/.test(path)) return word('colours')
  if (stat) return word('numberN', { number: Number(stat[1]) + 1 })
  if (/^value\b/.test(path)) return word('number')
  if (/^rows\b/.test(path)) return word('lines')
  if (/^item\.title\b/.test(path)) return word('main')
  if (/^item\.subtitle\b/.test(path)) return word('below')
  if (/^item\.value\b/.test(path)) return word('right')
  if (/^item\.image\b/.test(path)) return word('picture')
  if (/^item\.status\b/.test(path)) return word('lineRed')
  if (/^requests\b/.test(path)) return word('ask')
  return null
}
