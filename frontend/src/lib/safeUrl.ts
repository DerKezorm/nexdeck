/**
 * An address from somewhere else, made safe to put in a link.
 *
 * ⚠️ Most addresses on a board are not the operator's. A feed entry's link,
 * a Hacker News story, a monitor's URL from Uptime Kuma: all of them come out
 * of a third-party service and land in an `href`. A `javascript:` address
 * there runs as part of nexdeck, with the session, on any board that shows
 * that card.
 *
 * The content-security-policy the server sends stops it in a deployed build.
 * It is not sent by the Vite server, and a reverse proxy that rewrites
 * headers can drop it, so the check belongs here as well: one rule, at the
 * place where the value becomes a link.
 */

/** Everything that may stand in an href. Anything else becomes nothing. */
const ALLOWED = new Set(['http:', 'https:', 'mailto:'])

/**
 * The address if it is one nexdeck may link to, otherwise an empty string.
 *
 * A relative address ("/b/home", "#top") is kept: it stays inside the app.
 */
export function safeUrl(value: unknown): string {
  const text = typeof value === 'string' ? value.trim() : ''
  if (!text) return ''
  // A relative address has no scheme to worry about.
  if (text.startsWith('/') || text.startsWith('#') || text.startsWith('?')) return text
  try {
    const parsed = new URL(text, window.location.origin)
    return ALLOWED.has(parsed.protocol) ? text : ''
  } catch {
    // Not an address at all. Better nothing than a guess.
    return ''
  }
}

/** True when the value is something this app is willing to open. */
export function isSafeUrl(value: unknown): boolean {
  return safeUrl(value) !== ''
}
