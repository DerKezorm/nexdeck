import { useEffect, useState, type RefObject } from 'react'

/** The card's size, measured, because what fits depends on height as much as on width. */
export function useBoxSize(ref: RefObject<HTMLElement | null>): { width: number; height: number } {
  const [size, setSize] = useState({ width: 0, height: 0 })
  useEffect(() => {
    const node = ref.current
    if (!node) return
    // ⚠️ Measured once at once, not only when the observer reports. Its
    // reports come with the next painted frame, and a tab that is not on
    // screen paints none: the card sat in its fallback face until somebody
    // looked, and the first frame anybody saw was the wrong one.
    setSize({ width: node.clientWidth, height: node.clientHeight })
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(([entry]) => {
      const box = entry.contentRect
      setSize((old) => (Math.abs(old.width - box.width) < 1 && Math.abs(old.height - box.height) < 1 ? old : { width: box.width, height: box.height }))
    })
    observer.observe(node)
    return () => observer.disconnect()
  }, [ref])
  return size
}
