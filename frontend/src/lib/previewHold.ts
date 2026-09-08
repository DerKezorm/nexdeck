import type { WidgetData } from './types'

/** What the board shows for one card instead of the collector's answer. */
export interface HeldPreview {
  id: number
  data: WidgetData
  /**
   * Set when the sheet has just saved: the preview stays until the server has
   * fetched with the new options, so the card does not flash its old numbers
   * in between. ``undefined`` means the preview is only a draft and may go at
   * any time.
   */
  holdUntilChange?: number
}

/**
 * What the board's preview should be after the sheet reports one, or reports
 * that there is none.
 *
 * ⚠️ A held preview is not cleared by "there is nothing to preview any more".
 * That is what the sheet says the moment a save lands: it refetches the
 * widget, the draft options equal the saved ones again, and the report arrives
 * a tick after ``onSaved`` set the hold. Clearing it there dropped the card
 * back to the collector's last answer, which still had the old options, so a
 * change appeared, jumped back, and was right again only after a reload. It
 * had been that way for as long as the sheet has had a preview.
 */
export function nextPreview(
  current: HeldPreview | null,
  id: number,
  preview: WidgetData | null,
): HeldPreview | null {
  if (preview) return { id, data: preview }
  return current?.holdUntilChange !== undefined ? current : null
}
