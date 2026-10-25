/**
 * Asks before the editor is left with unsaved changes (KARTEN-9 AC-11): a link or button inside nexdeck, the
 * browser's back button, a reload or closing the tab.
 *
 * ⚠️ The app runs on `<BrowserRouter>`, where React Router's own `useBlocker` does not work (it needs a data
 * router). So the navigator's `push` and `replace` are held while there is something to lose, and the browser's
 * back button meets an extra entry of the same address first: going back lands on it, the editor stays and asks.
 * A reload or a closed tab gets the browser's own question (`beforeunload`).
 */
import { useCallback, useContext, useEffect, useRef, useState } from 'react'
import { UNSAFE_NavigationContext } from 'react-router-dom'

const MARK = 'nexdeckCardEditor'

type RouterNavigator = React.ContextType<typeof UNSAFE_NavigationContext>['navigator']

/** Hand every `push` and `replace` of the router to `decide`, which goes on or not. Returns the way back. */
function holdNavigator(navigator: RouterNavigator, decide: (go: () => void) => void): () => void {
  const { push, replace } = navigator
  navigator.push = (...args) => decide(() => push.apply(navigator, args))
  navigator.replace = (...args) => decide(() => replace.apply(navigator, args))
  return () => {
    navigator.push = push
    navigator.replace = replace
  }
}

export interface LeaveGuard {
  /** A way out is waiting for an answer. */
  asking: boolean
  leave: () => void
  stay: () => void
  /** Let the next navigation through without asking: after a save, or for "Reload". */
  allow: () => void
}

export function useLeaveGuard(when: boolean): LeaveGuard {
  const { navigator } = useContext(UNSAFE_NavigationContext)
  const [pending, setPending] = useState<(() => void) | null>(null)
  const allowed = useRef(false)
  const whenRef = useRef(when)
  useEffect(() => {
    whenRef.current = when
  }, [when])

  useEffect(() => {
    if (!when) return
    return holdNavigator(navigator, (go) => {
      if (allowed.current) {
        allowed.current = false
        go()
        return
      }
      setPending(() => go)
    })
  }, [when, navigator])

  useEffect(() => {
    if (!when) return
    const onUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      // Older browsers want a text; every browser shows its own.
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', onUnload)
    return () => window.removeEventListener('beforeunload', onUnload)
  }, [when])

  useEffect(() => {
    if (!when) return
    const state = (window.history.state ?? {}) as Record<string, unknown>
    if (!state[MARK]) window.history.pushState({ ...state, [MARK]: true }, '', window.location.href)
    const onPop = (event: PopStateEvent) => {
      if (allowed.current) {
        allowed.current = false
        return
      }
      if (!whenRef.current || (event.state as Record<string, unknown> | null)?.[MARK]) return
      // Back from the extra entry onto the editor's own: ask, and be ready to go on back.
      setPending(() => () => {
        allowed.current = true
        window.history.back()
      })
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [when])

  const leave = useCallback(() => {
    const go = pending
    setPending(null)
    if (!go) return
    allowed.current = true
    go()
  }, [pending])

  const stay = useCallback(() => {
    setPending(null)
    const state = (window.history.state ?? {}) as Record<string, unknown>
    if (whenRef.current && !state[MARK]) window.history.pushState({ ...state, [MARK]: true }, '', window.location.href)
  }, [])

  // ⚠️ Only while something is held: once the question is off (a save made the card clean) the next navigation goes
  // through unheld and would never use the flag up, and the next real change would leave without asking.
  const allow = useCallback(() => {
    if (whenRef.current) allowed.current = true
  }, [])

  return { asking: pending !== null, leave, stay, allow }
}
