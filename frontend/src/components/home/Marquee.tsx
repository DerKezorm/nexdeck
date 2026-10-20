import { useEffect, useRef, useState, type CSSProperties } from 'react'

/**
 * A name in a box of fixed width: as it is when it fits, a slow ticker back
 * and forth when it does not, with a rest at either end. With reduced motion
 * asked for, it stands still and ends in an ellipsis (``.lamp-marquee`` in
 * app.css).
 */
export function Marquee({ text, className = '' }: { text: string; className?: string }) {
  const box = useRef<HTMLSpanElement>(null)
  const inner = useRef<HTMLSpanElement>(null)
  const [shift, setShift] = useState(0)
  useEffect(() => {
    const measure = () => {
      if (!box.current || !inner.current) return
      setShift(Math.max(0, Math.ceil(inner.current.scrollWidth - box.current.clientWidth)))
    }
    measure()
    if (typeof ResizeObserver === 'undefined' || !box.current) return
    const watch = new ResizeObserver(measure)
    watch.observe(box.current)
    return () => watch.disconnect()
  }, [text])
  // About 25 pixels a second, and never in a hurry.
  const style = shift > 0 ? ({ '--shift': `-${shift}px`, '--marquee-time': `${Math.max(5, shift / 25 + 4)}s` } as CSSProperties) : undefined
  return (
    <span ref={box} className={`lamp-marquee ${className}`} data-marquee={shift > 0 ? '' : undefined} style={style} title={shift > 0 ? text : undefined}>
      <span ref={inner}>{text}</span>
    </span>
  )
}
