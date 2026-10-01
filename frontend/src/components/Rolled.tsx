import { useEffect, useRef, useState } from 'react'

import { formatValue } from '../lib/format'

/** How long a number takes to roll from the old value to the new one. */
export const ROLL_MS = 900

/** Whether the person asked for less motion: then a number changes at once. */
function stillWanted(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/**
 * The value a number shows on its way from one reading to the next, `share`
 * of the way there, eased out so it settles rather than stops. Whole numbers
 * stay whole on the way: 5 going to 7 shows 6, never 5.6.
 */
export function between(from: number, to: number, share: number): number {
  const eased = 1 - (1 - Math.min(1, Math.max(0, share))) ** 3
  const value = from + (to - from) * eased
  return Number.isInteger(from) && Number.isInteger(to) ? Math.round(value) : value
}

/**
 * A number that rolls to its new value instead of jumping, written the way
 * the card writes every number. A board that updates live is much easier to
 * follow when a figure counts up than when it flickers to another, and it is
 * what makes a dashboard look alive in a screen recording.
 *
 * The first reading is shown as it is. Anything that is not a number, and
 * every number when less motion is asked for, changes at once.
 */
export function Rolled({ value, unit = '' }: { value: number | string | null | undefined; unit?: string }) {
  const [shown, setShown] = useState(value)
  // Where the number stands on screen right now, which is where the next roll
  // starts: a reading that arrives mid-roll carries on from there.
  const now = useRef(value)
  useEffect(() => {
    const start = now.current
    if (typeof value !== 'number' || typeof start !== 'number' || start === value || stillWanted()) {
      now.current = value
      setShown(value)
      return
    }
    const began = performance.now()
    let frame = 0
    const step = (time: number) => {
      const share = (time - began) / ROLL_MS
      const next = share >= 1 ? value : between(start, value, share)
      now.current = next
      setShown(next)
      if (share < 1) frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [value])
  return <>{formatValue(shown, unit)}</>
}
