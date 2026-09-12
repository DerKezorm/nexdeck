import { useEffect, type RefObject } from 'react'

/**
 * Hold the focus inside an open dialog, and give it back on the way out.
 *
 * ⚠️ Both Sheet and Dialog said ``aria-modal="true"``, which promises exactly
 * this, and neither did it. Tab walked straight out of the dialog into the
 * page behind it, where a screen reader then read a form the person could not
 * see; and closing dropped the focus onto the document, so the next Tab
 * started again from the top of the page instead of at the button that had
 * opened the thing. The command bar made the same promise and got it on
 * 12.09.2026, which is why this lives here and not inside ui.tsx.
 */
export function useFocusTrap(open: boolean, container: RefObject<HTMLElement | null>): void {
  useEffect(() => {
    if (!open) return
    const cameFrom = document.activeElement as HTMLElement | null
    const inside = (): HTMLElement[] => {
      const found = container.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )
      return [...(found ?? [])].filter((element) => element.offsetParent !== null || element === document.activeElement)
    }
    // The first thing inside, so the keyboard starts where the eye does.
    const first = inside()[0]
    first?.focus()

    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return
      const stops = inside()
      if (!stops.length) return
      const edge = event.shiftKey ? stops[0] : stops[stops.length - 1]
      if (document.activeElement === edge || !container.current?.contains(document.activeElement)) {
        event.preventDefault()
        ;(event.shiftKey ? stops[stops.length - 1] : stops[0]).focus()
      }
    }
    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('keydown', onKey, true)
      // Back to whatever opened it, if that is still on the page.
      if (cameFrom?.isConnected) cameFrom.focus()
    }
  }, [open, container])
}
