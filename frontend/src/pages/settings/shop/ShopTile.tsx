import { ThumbsUp } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { serverUrl } from '../../../api/client'
import { ServiceIcon } from '../../../components/ServiceIcon'
import { useGround } from '../../../lib/ground'
import { pickText } from '../../../lib/cardText'
import type { ShopEntry } from '../../../lib/cardShop'

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
 * name, author, thumbs, class and what it needs. The whole tile opens the detail.
 */
export function ShopTile({ entry, onOpen }: { entry: ShopEntry; onOpen?: (entry: ShopEntry) => void }) {
  const { t, i18n } = useTranslation()
  const ground = useGround((state) => state.mode)
  const name = pickText(entry.name, i18n.language) || entry.slug
  const have = (kind: string) => entry.connections.some((one) => one.kind === kind)
  const frame = 'w-full text-left rounded-xl border border-line p-3 grid gap-2 h-full content-start'
  const content = (
    <>
        <div className="aspect-[4/3] rounded-lg overflow-hidden bg-[color-mix(in_srgb,var(--nd-text)_6%,transparent)] flex items-center justify-center">
          <img
            src={serverUrl(entry.images[ground])}
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
          <div className="text-sm font-medium truncate">{name}</div>
          <div className="text-[11px] text-muted truncate">{t('cards.shop.by', { author: entry.author.login })}</div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="inline-flex items-center gap-1 text-[12px] text-muted" role="img" aria-label={t('cards.shop.thumbs', { count: entry.thumbs })} title={t('cards.shop.thumbs', { count: entry.thumbs })}>
            <ThumbsUp size={12} aria-hidden="true" />
            {entry.thumbs}
          </span>
          <ClassChip entry={entry} />
          <span className="chip !py-0 text-[11px]">{t(`cards.shop.type.${entry.type}`)}</span>
          <ShopBadges entry={entry} />
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px]" role="group" aria-label={t('cards.shop.needs')}>
          {entry.requires.map((need) => (
            <span key={need.kind} className={`inline-flex items-center gap-1.5 ${have(need.kind) ? '' : 'text-muted'}`}>
              <ServiceIcon icon={need.icon} size={14} />
              {need.label}
              {!have(need.kind) && <span className="text-[11px] text-warn">{t('cards.shop.noConnection')}</span>}
            </span>
          ))}
        </div>
    </>
  )
  return (
    <li className="min-w-0" data-testid={`shop-tile-${entry.id}`}>
      {onOpen ? (
        <button type="button" className={`${frame} hover:bg-surface-hover focus-visible:outline-2 focus-visible:outline-accent`} onClick={() => onOpen(entry)}>
          {content}
        </button>
      ) : (
        <div className={frame}>{content}</div>
      )}
    </li>
  )
}
