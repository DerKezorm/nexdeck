/**
 * Bring one card into view and let it light up for a moment: where a row of
 * the attention card leads. False when the card is not on the page shown.
 */
export function focusCard(widgetId: number): boolean {
  const card = document.querySelector<HTMLElement>(`[data-widget="${widgetId}"]`)
  if (!card) return false
  const still = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  card.scrollIntoView({ behavior: still ? 'auto' : 'smooth', block: 'center' })
  card.classList.add('nd-focus')
  window.setTimeout(() => card.classList.remove('nd-focus'), 1800)
  return true
}
