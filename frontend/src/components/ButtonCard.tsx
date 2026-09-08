/**
 * The button card: the whole card is one button.
 *
 * ⚠️ Where it leads decides the element. A board stays inside nexdeck, so it
 * is a router link: the app keeps its state, the stream stays open, and a
 * wall display does not reload itself to go one board over. An address leaves,
 * so it is a plain anchor. Drawing both the same way would reload the whole
 * app for a board switch.
 *
 * The name and the symbol are the card's own, set where every card sets them.
 * A second name in the widget's options would be a second place to change and
 * one of them would end up stale.
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

/** Where the button leads, or nothing when it leads nowhere valid. */
export function targetOf(kind: string, where: string): { inside: string } | { outside: string } | null {
  const wanted = (where || '').trim()
  if (!wanted) return null
  if (kind === 'link') {
    // ⚠️ Through safeUrl. The address is typed in, and javascript: in it
    // would run in nexdeck's own origin, with the session.
    const url = safeUrl(wanted)
    return url ? { outside: url } : null
  }
  // A board, or one page of it, as the picker writes it: "home", "home/media".
  const parts = wanted.replace(/^\/+|\/+$/g, '').split('/')
  if (parts.length > 2 || parts.some((part) => !/^[a-z0-9-]+$/i.test(part))) return null
  return { inside: `/b/${parts.join('/')}` }
}

export function ButtonCard({ widget, data, editing }: Props) {
  const { t } = useTranslation()
  const kind = String(data?.meta?.kind ?? 'board')
  const look = String(data?.meta?.look ?? 'label')
  const colour = typeof data?.meta?.colour === 'string' && data.meta.colour ? data.meta.colour : undefined
  const newTab = data?.meta?.new_tab !== false
  const target = targetOf(kind, String(data?.meta?.where ?? ''))
  const name = widget.title || ''

  const big = look === 'icon'
  const inside = (
    <>
      {look !== 'text' && <ServiceIcon icon={widget.icon || 'lucide:square-arrow-out-up-right'} size={big ? 40 : 20} className="flex-none" />}
      {look !== 'icon' && <span className="truncate">{name}</span>}
    </>
  )

  // The accent colour, when one was picked, carries its own text colour: a
  // light ground needs dark text and a dark ground light text, and guessing
  // wrong makes the name unreadable rather than merely off.
  const painted = colour
    ? { background: colour, color: readableOn(colour), borderColor: 'transparent' }
    : undefined

  const shape = [
    'flex-1 min-h-0 w-full flex items-center no-underline',
    big ? 'justify-center' : 'justify-start gap-2.5 px-3',
    'font-semibold',
    big ? 'text-[13px]' : 'text-[14px]',
    colour ? '' : 'text-ink hover:bg-accent-soft',
    'transition-colors',
  ].join(' ')

  // ⚠️ Inert while the board is being arranged, and it has to say so. In edit
  // mode the whole card is the drag handle, so a live button would fire on
  // every attempt to move the card by its face. Reported as "nothing happens":
  // the card had just been configured, which happens in edit mode, and nothing
  // on it explained the silence.
  if (editing || !target) {
    return (
      <span
        className={`${shape} opacity-90`}
        style={painted}
        title={target ? t('card.buttonWhileEditing') : t('card.buttonNowhere')}
        aria-label={look === 'icon' ? name : undefined}
      >
        {inside}
      </span>
    )
  }
  if ('inside' in target) {
    return (
      <Link to={target.inside} className={shape} style={painted} title={name} aria-label={look === 'icon' ? name : undefined}>
        {inside}
      </Link>
    )
  }
  return (
    <a
      href={target.outside}
      target={newTab ? '_blank' : undefined}
      rel="noreferrer noopener"
      className={shape}
      style={painted}
      title={name}
      aria-label={look === 'icon' ? name : undefined}
    >
      {inside}
    </a>
  )
}

/** Black or white, whichever can be read on this colour.
 *
 *  The usual relative-luminance test, so a pale yellow gets dark text and a
 *  deep blue gets light text instead of one of them being guessed. */
export function readableOn(colour: string): string {
  const hex = colour.replace('#', '')
  if (hex.length !== 3 && hex.length !== 6) return '#ffffff'
  const full = hex.length === 3 ? hex.split('').map((c) => c + c).join('') : hex
  const channel = (at: number) => {
    const part = parseInt(full.slice(at, at + 2), 16) / 255
    return part <= 0.03928 ? part / 12.92 : ((part + 0.055) / 1.055) ** 2.4
  }
  const luminance = 0.2126 * channel(0) + 0.7152 * channel(2) + 0.0722 * channel(4)
  return luminance > 0.36 ? '#0b1116' : '#ffffff'
}
