/**
 * A picture, or a few of them one after another.
 *
 * ⚠️ The pictures are typed in by hand, so an address here is no more
 * trustworthy than one in a bookmark. `safeUrl` keeps out the schemes that
 * would run rather than draw.
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { safeUrl } from '../lib/safeUrl'
import type { WidgetData, WidgetView } from '../lib/types'

interface Props {
  widget: WidgetView
  data?: WidgetData
}

export function ImageCard({ widget, data }: Props) {
  const { t } = useTranslation()
  const pictures = (data?.items ?? [])
    .map((one) => ({ url: safeUrl(String(one.url ?? '')), caption: String(one.title ?? '') }))
    .filter((one): one is { url: string; caption: string } => Boolean(one.url))
  const every = Number(data?.meta?.every ?? 0)
  const fit = data?.meta?.fit === 'contain' ? 'contain' : 'cover'
  const captions = data?.meta?.captions !== false
  const [at, setAt] = useState(0)

  // A card that loses a picture must not keep pointing past the end of the
  // list, and one that is edited down to a single picture must not keep
  // ticking either.
  const count = pictures.length
  useEffect(() => {
    if (at >= count) setAt(0)
  }, [at, count])
  useEffect(() => {
    if (every <= 0 || count < 2) return
    const timer = window.setInterval(() => setAt((current) => (current + 1) % count), every * 1000)
    return () => window.clearInterval(timer)
  }, [every, count])

  if (!count) {
    return <p className="flex-1 grid place-items-center text-[12px] text-faint px-3 text-center">{t('card.noPictures')}</p>
  }

  const showing = pictures[Math.min(at, count - 1)]
  return (
    <div
      className="relative flex-1 min-h-0 overflow-hidden bg-elev"
      // Clicking moves on, so a wall display does not have to be waited out.
      onClick={count > 1 ? () => setAt((current) => (current + 1) % count) : undefined}
      role={count > 1 ? 'button' : undefined}
      tabIndex={count > 1 ? 0 : undefined}
      onKeyDown={count > 1 ? (event) => {
        if (event.key !== 'Enter' && event.key !== ' ') return
        event.preventDefault()
        setAt((current) => (current + 1) % count)
      } : undefined}
      aria-label={count > 1 ? t('card.pictureNext', { count }) : undefined}
    >
      <img
        src={showing.url}
        // ⚠️ The caption is the only description there is. Without one the
        // picture is decoration as far as a screen reader is concerned, and an
        // invented alt text would be worse than none.
        alt={showing.caption}
        data-testid="picture"
        className="w-full h-full"
        style={{ objectFit: fit }}
        loading="lazy"
      />
      {captions && showing.caption && (
        <p className="absolute inset-x-0 bottom-0 px-3 pt-5 pb-2 text-[12px] font-semibold text-white bg-gradient-to-t from-black/80 to-transparent truncate">
          {showing.caption}
        </p>
      )}
      {count > 1 && (
        <span className="absolute right-2 bottom-2 flex gap-1" aria-hidden="true">
          {pictures.map((one, index) => (
            <i key={one.url + index} className={`block w-1.5 h-1.5 rounded-full ${index === at ? 'bg-white' : 'bg-white/40'}`} />
          ))}
        </span>
      )}
      <span className="sr-only">{widget.title}</span>
    </div>
  )
}
