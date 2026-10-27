/**
 * Where a sign-in goes back to: ``/login?next=/go/plex`` returns to the tile
 * once the person is in.
 *
 * ⚠️ Only a path of nexdeck's own. ``next`` stands in an address anybody can
 * write and send, and a sign-in page that forwards to whatever it is handed
 * sends a freshly signed-in person to a look-alike page elsewhere. So
 * ``//elsewhere.example``, ``/\elsewhere.example``, ``https://...`` and
 * anything with a control character in it count as no ``next`` at all.
 *
 * The path waits in the tab's session storage, for ten minutes at most: a
 * sign-in at a provider leaves the page and comes back to ``/``, not here.
 */
const KEY = 'nexdeck.return'
const MINUTES = 10

export function returnPath(raw: string | null | undefined): string | null {
  if (!raw || raw.length > 600) return null
  if (!raw.startsWith('/') || raw.startsWith('//') || raw.includes('\\')) return null
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f\u007f]/.test(raw)) return null
  try {
    const url = new URL(raw, window.location.origin)
    if (url.origin !== window.location.origin) return null
    return `${url.pathname}${url.search}${url.hash}`
  } catch {
    return null
  }
}

/** Keep a path to go back to after the sign-in. */
export function keepReturn(path: string): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify({ path, at: Date.now() }))
  } catch {
    // Without storage the way back is lost; signing in still works.
  }
}

function read(remove: boolean): string | null {
  try {
    const raw = sessionStorage.getItem(KEY)
    if (remove) sessionStorage.removeItem(KEY)
    if (!raw) return null
    const kept = JSON.parse(raw) as { path?: unknown; at?: unknown }
    if (typeof kept.at !== 'number' || Date.now() - kept.at > MINUTES * 60_000) return null
    return typeof kept.path === 'string' ? returnPath(kept.path) : null
  } catch {
    return null
  }
}

/** The path waiting to be gone back to, without taking it. */
export function waitingReturn(): string | null {
  return read(false)
}

/** The path waiting to be gone back to; it is gone afterwards. */
export function takeReturn(): string | null {
  return read(true)
}
