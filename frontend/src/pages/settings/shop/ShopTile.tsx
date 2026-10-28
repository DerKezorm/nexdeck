import { ThumbsUp } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { serverUrl } from '../../../api/client'
import { ServiceIcon } from '../../../components/ServiceIcon'
import { useGround } from '../../../lib/ground'
import { pickText } from '../../../lib/cardText'
import { pictureSrc, type ShopEntry } from '../../../lib/cardShop'
import { hasDiscussion, ThumbButton, ThumbNotes, useThumb } from './shopThumb'

/** The state of an entry beside this installation, as a short word: what the tile and the detail page show first. */
export function ShopBadges({ entry }: { entry: ShopEntry }) {
  const { t } = useTranslation()
  return (
    <>
      {entry.installed !== null && (
        <span className="chip !py-0 text-[11px]" data-testid="shop-installed">
          {t('cards.shop.installed')}
        </span>
      )}
      {entry.installed?.update && !entry.removed && (
        <span className="chip !py-0 text-[11px] text-accent" data-testid="shop-update">
          {t('cards.shop.updateAvailable')}
        </span>
      )}
      {entry.removed && (
        <span
          className={`chip !py-0 text-[11px] ${entry.removed.level === 'harmful' ? '!text-bad' : 'text-warn'}`}
          data-testid="shop-removed"
          data-level={entry.removed.level}
        >
          {t('cards.shop.removed')}
        </span>
      )}
    </>
  )
}

/** The class of an entry in words: it only reads, it has buttons, or it signs in with a login of its own (KARTEN-13). */
export function ClassChip({ entry }: { entry: ShopEntry }) {
  const { t } = useTranslation()
  return <span className={`chip !py-0 text-[11px] ${entry.class === 'login' ? 'text-warn' : ''}`}>{t(`cards.shop.class.${entry.class}`)}</span>
}

/**
 * One entry of the shop as a tile: the preview picture (fetched through the server and only when it comes into view),
 * name, author, thumbs, class and what it needs. The whole tile opens the detail: the name is the button, stretched over
 * the tile, so the thumb can be a button of its own on top of it. The thumb sets the administrator's thumb on the
 * discussion of the entry; when nobody is signed in to GitHub it opens the detail, where the sign-in is.
 */
export function ShopTile({ entry, onOpen }: { entry: ShopEntry; onOpen?: (entry: ShopEntry) => void }) {
  const { t, i18n } = useTranslation()
  const ground = useGround((state) => state.mode)
  const thumb = useThumb(entry, false)
  const name = pickText(entry.name, i18n.language) || entry.slug
  const have = (kind: string) => entry.connections.some((one) => one.kind === kind)
  const press = async () => {
    if ((await thumb.set()) === 'login') {
      thumb.close()
      onOpen?.(entry)
    }
  }
  return (
    <li className="min-w-0" data-testid={`shop-tile-${entry.id}`}>
      <div className={`relative w-full text-left rounded-xl border border-line p-3 grid gap-2 h-full content-start ${onOpen ? 'hover:bg-surface-hover' : ''}`}>
        <div className="aspect-[4/3] rounded-lg overflow-hidden bg-[color-mix(in_srgb,var(--nd-text)_6%,transparent)] flex items-center justify-center">
          <img
            src={serverUrl(pictureSrc(entry, ground))}
            alt=""
            loading="lazy"
            decoding="async"
            className="w-full h-full object-contain"
            onError={(event) => {
              event.currentTarget.style.visibility = 'hidden'
            }}
          />
        </div>
        <div className="min-w-0">
          {onOpen ? (
            <button type="button" className="block max-w-full text-sm font-medium truncate text-left after:absolute after:inset-0 after:rounded-xl focus-visible:outline-none focus-visible:after:outline-2 focus-visible:after:outline-accent" onClick={() => onOpen(entry)}>
              {name}
            </button>
          ) : (
            <div className="text-sm font-medium truncate">{name}</div>
          )}
          <div className="text-[11px] text-muted truncate">{t('cards.shop.by', { author: entry.author.login })}</div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {hasDiscussion(entry) ? (
            <ThumbButton entry={entry} thumb={thumb} onPress={() => void press()} tile />
          ) : (
            <span className="inline-flex items-center gap-1 text-[12px] text-muted" role="img" aria-label={t('cards.shop.thumbs', { count: entry.thumbs })} title={t('cards.shop.thumbs', { count: entry.thumbs })}>
              <ThumbsUp size={12} aria-hidden="true" />
              {entry.thumbs}
            </span>
          )}
          <ClassChip entry={entry} />
          <span className="chip !py-0 text-[11px]">{t(`cards.shop.type.${entry.type}`)}</span>
          <ShopBadges entry={entry} />
        </div>
        <ThumbNotes thumb={thumb} small />
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px]" role="group" aria-label={t('cards.shop.needs')}>
          {entry.requires.map((need) => (
            <span key={need.kind} className={`inline-flex items-center gap-1.5 ${have(need.kind) ? '' : 'text-muted'}`}>
              <ServiceIcon icon={need.icon} size={14} />
              {need.label}
              {!have(need.kind) && <span className="text-[11px] text-warn">{t('cards.shop.noConnection')}</span>}
            </span>
          ))}
        </div>
      </div>
    </li>
  )
}
