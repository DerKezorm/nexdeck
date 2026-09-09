/**
 * ⚠️ This is the comparison a saved card is released by, so the two ways it
 * can be wrong are both faults somebody sees:
 *
 * saying yes too early puts the card back on the server's older answer, which
 * is the "I change something, it shows, it jumps back" report; saying no when
 * the two really are the same leaves the draft standing until its timeout,
 * and a change made by somebody else in those twenty seconds is invisible.
 */
import { describe, expect, it } from 'vitest'

import { sameSettings } from './savedYet'

const SAVED = { title: 'Clock', icon: 'lucide:clock', link: '', options: { seconds: true, date: false, label: 'Home' } }

describe('sameSettings', () => {
  it('says yes once the board carries what was saved', () => {
    expect(sameSettings({ ...SAVED }, SAVED)).toBe(true)
  })

  it('says no while the board still has the older options', () => {
    expect(sameSettings({ ...SAVED, options: { ...SAVED.options, seconds: false } }, SAVED)).toBe(false)
  })

  it('ignores the order the keys arrived in', () => {
    // ⚠️ One side was built in the browser, the other came back as JSON.
    // Plain JSON.stringify calls these two different.
    const shuffled = { label: 'Home', date: false, seconds: true }
    expect(sameSettings({ ...SAVED, options: shuffled }, SAVED)).toBe(true)
  })

  it('compares nested options by value, not by identity', () => {
    const nested = { title: 'X', icon: '', link: '', options: { rows: [{ a: 1, b: 2 }], deep: { x: [1, 2] } } }
    const other = { title: 'X', icon: '', link: '', options: { deep: { x: [1, 2] }, rows: [{ b: 2, a: 1 }] } }
    expect(sameSettings(nested, other)).toBe(true)
    expect(sameSettings(nested, { ...other, options: { deep: { x: [2, 1] }, rows: [{ a: 1, b: 2 }] } })).toBe(false)
  })

  it('treats a missing field and an empty one as the same', () => {
    // The server sends null for a link nobody set; the sheet sends ''.
    expect(sameSettings({ title: 'X', link: null }, { title: 'X', link: '' })).toBe(true)
    expect(sameSettings({ title: 'X' }, { title: 'X', options: {} })).toBe(true)
  })

  it('notices the three fields beside the options', () => {
    expect(sameSettings({ ...SAVED, title: 'Other' }, SAVED)).toBe(false)
    expect(sameSettings({ ...SAVED, icon: 'lucide:sun' }, SAVED)).toBe(false)
    expect(sameSettings({ ...SAVED, link: 'https://example.com' }, SAVED)).toBe(false)
  })
})
