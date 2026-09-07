/**
 * Buttons: a card that is nothing but big targets.
 *
 * ⚠️ Where a button leads decides how it is drawn. A board or a page of one
 * stays inside nexdeck, so it is a router link: the app keeps its state, the
 * stream stays open, and a wall display does not reload itself. An address
 * leaves, so it is a plain anchor in a new tab. Drawing both as the same
 * anchor would reload the whole app to go one board over.
 */
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { safeUrl } from '../lib/safeUrl'
import type { WidgetData, WidgetView } from '../lib/types'
import { ServiceIcon } from './ServiceIcon'

interface Props {
  widget: WidgetView
  data?: WidgetData
  editing?: boolean
}

/** Where one button leads, and whether that is inside nexdeck or out of it. */
export function targetOf(raw: string): { inside: string } | { outside: string } | null {
  const where = raw.trim()
  if (!where) return null
  // An address, in any of the forms somebody might type.
  if (/^[a-z][a-z0-9+.-]*:/i.test(where) || where.startsWith('//')) {
    const url = safeUrl(where)
    return url ? { outside: url } : null
  }
  // ⚠️ A board or a page of it, written as people say it: "home" or
  // "home/media". Anything with a slash beyond that is not a board name, and
  // guessing what it might be is how a link ends up pointing at the app's
  // own settings.
  const parts = where.replace(/^\/+|\/+$/g, '').split('/')
  if (parts.length > 2 || parts.some((part) => !/^[a-z0-9-]+$/i.test(part))) return null
  return { inside: `/b/${parts.join('/')}` }
}

export function ButtonCard({ widget, data, editing }: Props) {
  const { t } = useTranslation()
  const buttons = data?.items ?? []
  const columns = String(data?.meta?.columns ?? 'auto')
  const labels = data?.meta?.labels !== false
  const accent = Boolean(data?.meta?.accent)

  if (!buttons.length) {
    return <p className="flex-1 grid place-items-center text-[12px] text-faint px-3 text-center">{t('card.noButtons')}</p>
  }

  // "auto" lets the grid decide from the card's own width; a fixed count is
  // for people who want two rows of two whatever the card does.
  const style = columns === 'auto'
    ? { gridTemplateColumns: 'repeat(auto-fit, minmax(84px, 1fr))' }
    : { gridTemplateColumns: `repeat(${Number(columns) || 1}, minmax(0, 1fr))` }

  return (
    <div className="flex-1 min-h-0 grid gap-1.5 p-2 content-center" style={style} role="group" aria-label={widget.title || t('card.buttons')}>
      {buttons.map((one, index) => {
        const title = String(one.title ?? '')
        const target = targetOf(String(one.url ?? ''))
        const look = `flex items-center ${labels ? 'gap-2 px-2.5' : 'justify-center px-1'} py-2 min-h-11 rounded-lg border text-[13px] font-semibold no-underline truncate ${
          accent && index === 0
            ? 'bg-accent text-on-accent border-transparent hover:bg-accent-strong'
            : 'bg-surface-hover text-ink border-line hover:border-accent hover:bg-accent-soft'
        }`
        const inside = (
          <>
            <ServiceIcon icon={String(one.icon || 'lucide:square-arrow-out-up-right')} size={18} className="flex-none" />
            {labels && <span className="truncate">{title}</span>}
          </>
        )
        // ⚠️ In edit mode a button leads nowhere. The card is being arranged,
        // and a press that navigates away takes the arrangement with it.
        if (editing || !target) {
          return (
            <span key={index} className={`${look} opacity-90`} title={target ? title : t('card.buttonNowhere')} aria-label={labels ? undefined : title}>
              {inside}
            </span>
          )
        }
        if ('inside' in target) {
          return (
            <Link key={index} to={target.inside} className={look} title={title} aria-label={labels ? undefined : title}>
              {inside}
            </Link>
          )
        }
        return (
          <a key={index} href={target.outside} target="_blank" rel="noreferrer noopener" className={look} title={title} aria-label={labels ? undefined : title}>
            {inside}
          </a>
        )
      })}
    </div>
  )
}
