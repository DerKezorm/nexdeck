/**
 * The rule that decides what a card shows while its settings are open.
 *
 * ⚠️ Its own file because the bug lived in one arrow function inside a page
 * component, where nothing could reach it. The symptom was reported as "the
 * change appears, jumps back, and is right again after F5", and it had been
 * that way for as long as the sheet has had a preview.
 */
import type { WidgetData } from './types'
import { nextPreview, type HeldPreview } from './previewHold'

const DATA: WidgetData = { status: 'ok', meta: { face: 'hands' } }
const OLD: WidgetData = { status: 'ok', meta: { face: 'digits' } }

describe('nextPreview', () => {
  it('shows a preview the sheet just made', () => {
    expect(nextPreview(null, 7, DATA)).toEqual({ id: 7, data: DATA })
  })

  it('replaces one preview with the next', () => {
    const held: HeldPreview = { id: 7, data: OLD }
    expect(nextPreview(held, 7, DATA)).toEqual({ id: 7, data: DATA })
  })

  it('drops a draft preview when the sheet says there is none', () => {
    expect(nextPreview({ id: 7, data: DATA }, 7, null)).toBeNull()
  })

  it('keeps a held preview when the sheet says there is none', () => {
    // ⚠️ The bug. After a save the sheet refetches the widget, its draft
    // options equal the saved ones again, and it reports "nothing to preview"
    // a tick after the hold was set. Clearing it there dropped the card back
    // to the collector's last answer, which still had the old options.
    const held: HeldPreview = { id: 7, data: DATA, holdUntilChange: 1699 }
    expect(nextPreview(held, 7, null)).toBe(held)
  })

  it('a hold of zero is still a hold', () => {
    // ⚠️ `holdUntilChange` is an `updated_at`, and a card the collector has
    // never answered for has 0. Written as a truthiness test this would have
    // let exactly those cards flash their old data, which is the case the
    // whole rule is about.
    const held: HeldPreview = { id: 7, data: DATA, holdUntilChange: 0 }
    expect(nextPreview(held, 7, null)).toBe(held)
  })
})
