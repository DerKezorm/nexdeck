import { useEffect, useId, useRef, type ReactNode } from 'react'

import { shownStyle, useLook } from '../../lib/appearance'
import { followPointer } from '../../lib/cardLook'
import { canRefract, refract } from '../../lib/refraction'
import { useAuth } from '../../stores/auth'

/**
 * The surfaces of a home page that take the card style of Appearance: the
 * pills, chips, tiles and cards. The drawn styles (a bulb, a dial, a door)
 * are pictures, not cards, and stay as they are. ``app.css`` names the same
 * list for the styles (``:root[data-cards]`` on a home page).
 */
export const SURFACES = '.lamp-pill, .lamp-chip, .lamp-tile, .lamp-slide, .climate-tile, .climate-digits, .stat-card, .sensor-pill, .sensor-chip, .sensor-tile'

/**
 * An element of a home page as the cards of the board are: liquid glass
 * bends its edge where the browser can (``refract``), the glare follows the
 * pointer, and the surface tips towards it when the account allows it, as a
 * card does (``WidgetCard``). Not while the page is arranged: a tipped
 * element would not stand where the guides say.
 */
export function Felt({ arranging, look, children }: { arranging: boolean; look: string; children: ReactNode }) {
  const box = useRef<HTMLDivElement>(null)
  const filterId = `nd-hg-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`
  const liquid = useLook((state) => shownStyle(state) === 'liquid' && state.refraction)
  const tilts = useAuth((state) => state.user?.tilt !== false) && !arranging
  const tiltsNow = useRef(tilts)
  useEffect(() => {
    tiltsNow.current = tilts
    const surface = box.current?.querySelector<HTMLElement>(SURFACES)
    // Arranging starts: a tipped surface lies flat again.
    if (!tilts && surface) {
      surface.classList.remove('is-tipping')
      surface.style.transform = ''
    }
  }, [tilts])
  useEffect(() => {
    const surface = box.current?.querySelector<HTMLElement>(SURFACES)
    if (!surface) return
    const undo = followPointer(surface, () => tiltsNow.current)
    let unbend: (() => void) | undefined
    if (liquid && canRefract()) {
      const radius = Math.min(parseFloat(getComputedStyle(surface).borderTopLeftRadius) || 16, surface.offsetHeight / 2 || 16)
      unbend = refract(surface, filterId, radius)
    }
    return () => {
      undo()
      unbend?.()
    }
  }, [liquid, look, filterId])
  return <div ref={box} className="contents" data-felt>{children}</div>
}
