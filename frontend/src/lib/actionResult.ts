/**
 * What a pressed button says afterwards, on the board and on a wall display: the answer of the service in the
 * words of the card, and a failure in the language of the person (KARTEN-8 AC-9).
 */
import type { TFunction } from 'i18next'

import { ApiError } from '../api/client'
import { tLabel } from '../i18n/texts'
import { pausedUntil } from './testResult'

/** The sentence for a failed press: English keeps the server's own words, every other language gets the sentence of the code, and a code without one the translated server sentence. */
export function actionFailureText(t: TFunction, language: string, failure: unknown): string {
  if (!(failure instanceof ApiError)) return t('errors.network')
  if (language.split('-')[0] === 'en') return failure.message
  return t(`errors.widget.${failure.code}`, { defaultValue: tLabel(failure.message), ...pausedUntil(failure.message) })
}

/** The sentence for a press that went through: the one the adapter wrote, translated by wording when it is one of ours. */
export function actionDoneText(message: string): string {
  return tLabel(message)
}
