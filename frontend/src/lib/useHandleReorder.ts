/**
 * Dragging a list into a new order by a handle.
 *
 * ⚠️ The window listens, not the handle. Reordering moves the handle's own
 * node in the DOM, and a moved node loses its pointer capture: from the second
 * step on the events go to whatever sits under the cursor, so the row follows
 * only when the pointer happens to cross its own handle again. Upwards that
 * often happens and downwards it does not, which is why it looked like a
 * direction problem when it first turned up in the board list.
 *
 * ⚠️ And where a row belongs is counted, not looked up. "Which row contains
 * the pointer" leaves dead ground: the gaps between rows, and everything past
 * the last one, which is exactly where a drag downwards ends up.
 */
import { useEffect, useRef, useState } from 'react'

export interface Reorder<T> {
  /** The order to draw right now: the dragged one while a finger is down. */
  rows: T[]
  /** The row being held, by key, or null. */
  holding: string | null
  /** Put on every row, so a drag can ask where the rows actually are. */
  rowRef: (key: string) => (element: HTMLElement | null) => void
  /** Put on the handle of each row. */
  handleProps: (key: string) => {
    onPointerDown: (event: React.PointerEvent) => void
    onKeyDown: (event: React.KeyboardEvent) => void
  }
}

/** Where a list would be if the held row were dropped at `y`. */
export function orderIfDroppedAt<T>(
  rows: T[],
  keyOf: (one: T) => string,
  y: number,
  heldKey: string,
  boxes: Map<string, HTMLElement>,
): T[] {
  const held = rows.find((one) => keyOf(one) === heldKey)
  if (!held) return rows
  const others = rows.filter((one) => keyOf(one) !== heldKey)
  const place = others.filter((one) => {
    const box = boxes.get(keyOf(one))?.getBoundingClientRect()
    return box ? y >= box.top + box.height / 2 : false
  }).length
  return [...others.slice(0, place), held, ...others.slice(place)]
}

/** Move one entry of a list to another place. */
export function moved<T>(list: readonly T[], from: number, to: number): T[] {
  const next = [...list]
  if (from < 0 || from >= next.length || to < 0 || to >= next.length || from === to) return next
  const [one] = next.splice(from, 1)
  next.splice(to, 0, one)
  return next
}

/**
 * @param saved  the order as it stands
 * @param keyOf  a stable key per row
 * @param onDrop called with the new order, only when something really moved
 */
export function useHandleReorder<T>(saved: T[], keyOf: (one: T) => string, onDrop: (order: T[]) => void): Reorder<T> {
  const [dragged, setDragged] = useState<T[] | null>(null)
  const [holding, setHolding] = useState<string | null>(null)
  const boxes = useRef(new Map<string, HTMLElement>())
  const rows = dragged ?? saved

  useEffect(() => {
    if (holding === null) return
    const key = holding
    const follow = (event: PointerEvent) => {
      const y = event.clientY
      // The updater form, so every move sees the order the last one left,
      // whether or not React has re-rendered in between. Returning the same
      // array when nothing moved keeps this from redrawing on every pixel.
      setDragged((current) => {
        if (!current) return current
        const order = orderIfDroppedAt(current, keyOf, y, key, boxes.current)
        return order.every((one, place) => keyOf(one) === keyOf(current[place])) ? current : order
      })
    }
    const letGo = () => setHolding(null)
    window.addEventListener('pointermove', follow)
    window.addEventListener('pointerup', letGo)
    window.addEventListener('pointercancel', letGo)
    return () => {
      window.removeEventListener('pointermove', follow)
      window.removeEventListener('pointerup', letGo)
      window.removeEventListener('pointercancel', letGo)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [holding])

  useEffect(() => {
    if (holding !== null || dragged === null) return
    if (!dragged.every((one, place) => keyOf(one) === keyOf(saved[place]))) onDrop(dragged)
    setDragged(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [holding, dragged])

  return {
    rows,
    holding,
    rowRef: (key: string) => (element: HTMLElement | null) => {
      if (element) boxes.current.set(key, element)
      else boxes.current.delete(key)
    },
    handleProps: (key: string) => ({
      onPointerDown: (event: React.PointerEvent) => {
        // ⚠️ No setPointerCapture; see the note at the top of this file.
        event.preventDefault()
        setDragged(rows)
        setHolding(key)
      },
      onKeyDown: (event: React.KeyboardEvent) => {
        // Ctrl, Alt and Meta with an arrow belong to the browser and the
        // window manager. Taking those costs more than sorting a list is worth.
        if (event.ctrlKey || event.altKey || event.metaKey) return
        const at = rows.findIndex((one) => keyOf(one) === key)
        const to = event.key === 'ArrowUp' ? at - 1 : event.key === 'ArrowDown' ? at + 1 : -1
        if (to < 0 || to >= rows.length) return
        event.preventDefault()
        setDragged(moved(rows, at, to))
      },
    }),
  }
}
