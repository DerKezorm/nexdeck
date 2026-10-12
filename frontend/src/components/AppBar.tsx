import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useLocation } from 'react-router-dom'

/**
 * One bar for every page, standing from the first moment to the last.
 *
 * ⚠️ Issues #27 and #40. The app installed on iPadOS 26 blurs the top of the
 * page unless it finds a solid bar there, and once the blur is back it stays
 * until the app is started again. Every page used to bring a bar of its own:
 * a board one, settings and system another, sign-in none. Going from a board to
 * the settings took one bar down and put another up, and signing in went from no
 * bar to a bar; each brought the blur back. Now the bar is built once, above the
 * routes, and a page only puts its content into it with {@link Bar}. Between two
 * pages, and while one loads, it stands empty.
 */

type Look = 'bare' | 'full'
type Slot = { element: HTMLElement | null; setLook: (look: Look) => void }

const BarSlot = createContext<Slot | undefined>(undefined)

const BAR_CLASS = 'glass-strong app-bar z-40 h-12 flex items-center gap-2 px-3 border-x-0 border-t-0 rounded-none'

/** Pages that never had a bar: the wall display and the preview of a card. */
const BARLESS = [/^\/k(\/|$)/, /^\/preview(\/|$)/]

/**
 * The bar itself, and the place a page puts its content into.
 *
 * Fixed at the top; each page keeps the room for it with the spacer in {@link Bar}.
 * With nothing in it, it is bare in a browser tab (as sign-in always looked)
 * and solid in the installed app.
 */
export function AppBarFrame({ children }: { children: ReactNode }) {
  const [element, setElement] = useState<HTMLElement | null>(null)
  const [look, setLook] = useState<Look>('bare')
  const slot = useMemo(() => ({ element, setLook }), [element])
  const { pathname } = useLocation()
  const barless = BARLESS.some((pattern) => pattern.test(pathname))
  return (
    <BarSlot.Provider value={barless ? undefined : slot}>
      {!barless && <header ref={setElement} className={`${BAR_CLASS} fixed top-0 inset-x-0`} data-look={look} data-no-picture />}
      {children}
    </BarSlot.Provider>
  )
}

/**
 * A page's content for the bar.
 *
 * ``bare`` keeps it without a surface in a browser tab, for a page that shows
 * only a button or two up there. ``spacer`` keeps the room below the bar in the
 * page; a page that centres its content in the whole window goes without.
 * Outside {@link AppBarFrame} (a test of one component) the bar is drawn in place.
 */
export function Bar({ children, bare = false, spacer = true }: { children: ReactNode; bare?: boolean; spacer?: boolean }) {
  const slot = useContext(BarSlot)
  const setLook = slot?.setLook
  useEffect(() => {
    if (!setLook) return
    setLook(bare ? 'bare' : 'full')
    return () => setLook('bare')
  }, [setLook, bare])
  if (slot === undefined) {
    return (
      <header className={`${BAR_CLASS} sticky top-0`} data-no-picture>
        {children}
      </header>
    )
  }
  return (
    <>
      {spacer && <div className="h-12" data-no-picture aria-hidden />}
      {slot.element && createPortal(children, slot.element)}
    </>
  )
}
