/**
 * A finger swiped sideways across a page: the next page or the one before.
 *
 * Kept apart from any one page so every place that turns pages by a swipe
 * does it alike. The board turns its pages this way on a phone.
 *
 * ⚠️ A phone page is scrolled up and down all the time, and a scroll that
 * turned the page would be worse than no swipe at all. So a swipe is only
 * one that goes sideways far, quickly and at least twice as far as up or
 * down; one that starts going up or down is a scroll for good, whatever the
 * finger does after.
 */
import { useEffect, useRef, type RefObject } from 'react'

/** How far the finger travels sideways before it is a swipe. */
export const SWIPE_PX = 60
/** Sideways at least this many times as far as up or down. */
export const STEEPNESS = 2
/** A swipe is quick; a finger that rests and then moves reads or drags. */
export const SWIPE_MS = 800
/** After this much movement the gesture has its direction, and keeps it. */
const DECIDED_PX = 12

export interface Touch {
  x: number
  y: number
  t: number
}

/** -1 for the next page (the finger went left), 1 for the one before, 0 for no swipe. */
export function swipeOf(start: Touch, end: Touch): -1 | 0 | 1 {
  const dx = end.x - start.x
  const dy = end.y - start.y
  if (end.t - start.t > SWIPE_MS) return 0
  if (Math.abs(dx) < SWIPE_PX || Math.abs(dx) < STEEPNESS * Math.abs(dy)) return 0
  return dx < 0 ? -1 : 1
}

/** Whether a movement so far has shown itself to be a scroll up or down. */
export function scrolling(start: Touch, now: Touch): boolean {
  const dx = Math.abs(now.x - start.x)
  const dy = Math.abs(now.y - start.y)
  return dy >= DECIDED_PX && dy > dx
}

/**
 * The page a swipe leads to, or nothing at the first or the last page:
 * a swipe past the end does not wrap round, where a wall display cycling
 * by itself would.
 */
export function pageAfter<Page extends { id: number }>(pages: Page[], current: number | undefined, direction: -1 | 1): Page | undefined {
  const index = pages.findIndex((page) => page.id === current)
  return index >= 0 ? pages[index - direction] : undefined
}

/**
 * Whether the element under the finger, or one around it up to ``root``,
 * takes sideways movement for itself: a row that scrolls sideways, a
 * slider, a field, a control that is swiped (it says so with
 * ``touch-action``), a dialog or a sheet, or anything marked ``data-no-swipe``.
 */
export function takesSideways(target: EventTarget | null, root: Element | null): boolean {
  let node = target instanceof Element ? target : null
  while (node && node !== root?.parentElement) {
    // ⚠️ A dialog or a sheet is drawn inside the page more often than not:
    // a finger in it is reading or choosing, never turning the page behind.
    if (node.matches('input, textarea, select, [contenteditable="true"], [data-no-swipe], [role="dialog"], [aria-modal="true"]')) return true
    const style = window.getComputedStyle(node)
    const action = style.touchAction || ''
    if (action === 'none' || (action.includes('pan-y') && !action.includes('pan-x'))) return true
    if ((style.overflowX === 'auto' || style.overflowX === 'scroll') && node.scrollWidth > node.clientWidth) return true
    if (node === root) break
    node = node.parentElement
  }
  return false
}

/**
 * Calls ``onSwipe`` for a swipe that starts inside ``area``, while ``enabled``
 * and while ``narrow`` matches the screen.
 *
 * Listened to on the document rather than on the area: a page that is
 * still loading has no area yet, and the area may be drawn anew. What lies
 * outside it never turns a page, and neither does a dialog inside it.
 *
 * ``narrow`` is when the screen counts as one that swipes; a wall display
 * passes ``all``, since a wall tablet is wide and touch events come from a
 * touch screen only.
 */
export function useSwipe(area: RefObject<HTMLElement | null>, enabled: boolean, onSwipe: (direction: -1 | 1) => void, narrow = '(max-width: 767px)'): void {
  const latest = useRef(onSwipe)
  useEffect(() => {
    latest.current = onSwipe
  })
  useEffect(() => {
    if (!enabled) return
    let start: Touch | null = null
    const down = (event: TouchEvent) => {
      start = null
      const root = area.current
      if (event.touches.length !== 1 || !root || !root.contains(event.target as Node)) return
      if (!window.matchMedia?.(narrow).matches) return
      if (takesSideways(event.target, root)) return
      const finger = event.touches[0]
      start = { x: finger.clientX, y: finger.clientY, t: event.timeStamp }
    }
    const move = (event: TouchEvent) => {
      if (!start) return
      const finger = event.touches[0]
      if (event.touches.length !== 1 || !finger) start = null
      else if (scrolling(start, { x: finger.clientX, y: finger.clientY, t: event.timeStamp })) start = null
    }
    const up = (event: TouchEvent) => {
      const from = start
      start = null
      const finger = event.changedTouches[0]
      if (!from || !finger) return
      const direction = swipeOf(from, { x: finger.clientX, y: finger.clientY, t: event.timeStamp })
      if (direction) latest.current(direction)
    }
    const cancel = () => {
      start = null
    }
    document.addEventListener('touchstart', down, { passive: true })
    document.addEventListener('touchmove', move, { passive: true })
    document.addEventListener('touchend', up, { passive: true })
    document.addEventListener('touchcancel', cancel, { passive: true })
    return () => {
      document.removeEventListener('touchstart', down)
      document.removeEventListener('touchmove', move)
      document.removeEventListener('touchend', up)
      document.removeEventListener('touchcancel', cancel)
    }
  }, [area, enabled, narrow])
}
