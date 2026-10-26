/**
 * What a connection test said, in words (KARTEN-3 AC-9): the codes an own integration can fail with each have a
 * sentence and a hint of their own; any other answer keeps the server's words.
 */
import type { TFunction } from 'i18next'

export interface TestResult {
  ok: boolean
  code?: string
  message: string
  hint?: string
}

/** The codes with words of their own. `sign_in_paused` is worded on cards (`errors.widget`) with the time taken from the server's sentence; the Test button signs in anyway and never meets it. */
export const TEST_CODES = ['auth_failed', 'unreachable', 'unexpected_answer', 'sign_in_no_ticket', 'sign_in_failed', 'sign_in_web_page'] as const

export function testResultText(t: TFunction, result: TestResult): { message: string; hint: string | undefined } {
  if (!result.ok && result.code && (TEST_CODES as readonly string[]).includes(result.code)) {
    return {
      message: t(`settings.integrations.testCode.${result.code}`, { defaultValue: result.message }),
      hint: t(`settings.integrations.testHint.${result.code}`, { defaultValue: result.hint ?? '' }) || undefined,
    }
  }
  return { message: result.message, hint: result.hint }
}

/**
 * The time in "Signing in is paused until 14:30 after three failed attempts." (KARTEN-3 EC-4), for the sentence of the
 * code in every other language. The server writes it as hours and minutes, so a card can name it without a second request.
 */
export function pausedUntil(message: unknown): { time: string } {
  return { time: /\b(\d{1,2}:\d{2})\b/.exec(String(message ?? ''))?.[1] ?? '' }
}
