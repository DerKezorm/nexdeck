import type { TFunction } from 'i18next'

import { ApiError, post } from '../../../api/client'
import { SHARE_FAILURES, shareProblems } from '../../../lib/cardShare'

/** The issue a card is to be sent into again after it is saved: `?resend=<number>` on the address of the editor. */
export function resendNumber(params: URLSearchParams): number {
  const number = Number(params.get('resend') ?? '')
  return Number.isInteger(number) && number > 0 ? number : 0
}

/**
 * "Fix and resend" (KARTEN-16 AC-10): the saved text goes into the issue it was handed in with, or, when it did not
 * change, the Workshop is asked to check it once more. Says in a sentence what happened; a failure never loses the save.
 */
export async function resendIssue(t: TFunction, number: number): Promise<{ ok: boolean; message: string }> {
  try {
    const answer = await post<{ how: 'edited' | 'recheck' }>('/workshop/submit/resend', { issue: number })
    return { ok: true, message: t(answer.how === 'recheck' ? 'cards.share.resend.recheck' : 'cards.share.resend.edited', { number }) }
  } catch (failure) {
    const problems = shareProblems(failure)
    if (problems.length) return { ok: false, message: t('cards.share.resend.failed', { message: problems[0].message }) }
    if (failure instanceof ApiError) {
      const own = (SHARE_FAILURES as readonly string[]).includes(failure.code) ? t(`cards.share.errors.${failure.code}`, { defaultValue: failure.message }) : failure.message
      return { ok: false, message: t('cards.share.resend.failed', { message: own }) }
    }
    return { ok: false, message: t('cards.share.resend.failed', { message: t('errors.network') }) }
  }
}
