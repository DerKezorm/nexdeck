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

/** The codes with words of their own. `sign_in_paused` carries the time in the server's sentence and keeps it. */
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
