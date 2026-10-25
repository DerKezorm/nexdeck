/**
 * The chat's words (roadmap M3), loaded with the chat and its setting page
 * rather than with every board (``lazyTexts.ts``). The title and the facts
 * about a button stay in the main language files; the button, Ctrl K and the
 * question before a press use them.
 */
import { useLazyTexts } from './lazyTexts'

/** Whether the chat's words are there in the language on screen. */
export function useAssistantTexts(): boolean {
  return useLazyTexts('assistant')
}
