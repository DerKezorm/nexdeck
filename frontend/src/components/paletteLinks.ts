import { safeUrl } from '../lib/safeUrl'
import type { WidgetData, WidgetView } from '../lib/types'
import { targetOf } from './ButtonCard'

export interface PaletteLink {
  title: string
  url: string
  icon: string
  newTab: boolean
}

/** Cards whose rows are saved links: the services that keep bookmarks. */
const BOOKMARK_LISTS = new Set(['karakeep.recent', 'linkwarden.recent', 'linkding.recent', 'readeck.recent'])

/**
 * The addresses a card leads to beyond its own link (issue #46).
 *
 * Read from what the card already shows, so the bar asks no service anything
 * and a bookmark service lists only what its card has loaded. A link card on
 * the board that the bar did not know was reported as "not quick to search".
 */
export function linksOf(widget: WidgetView, data: WidgetData | undefined): PaletteLink[] {
  if (!data) return []
  if (widget.kind === 'core.button') {
    if (data.meta?.kind !== 'link') return []
    const target = targetOf('link', String(data.meta?.where ?? ''))
    if (!target || !('outside' in target)) return []
    return [{ title: widget.title || target.outside, url: target.outside, icon: widget.icon || 'lucide:square-arrow-out-up-right', newTab: data.meta?.new_tab !== false }]
  }
  const own = widget.kind === 'core.bookmarks'
  if (!own && !BOOKMARK_LISTS.has(widget.kind)) return []
  const links: PaletteLink[] = []
  for (const item of data.items ?? []) {
    // ⚠️ Through safeUrl, as on the card: a javascript: address typed into a
    // bookmark would otherwise run in nexdeck's origin from the bar.
    const url = safeUrl(String(item.url ?? ''))
    if (!url) continue
    const icon = own ? String(item.icon || 'lucide:link') : widget.icon || 'lucide:link'
    links.push({ title: String(item.title || url), url, icon, newTab: true })
  }
  return links
}
