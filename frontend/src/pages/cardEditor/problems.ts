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
