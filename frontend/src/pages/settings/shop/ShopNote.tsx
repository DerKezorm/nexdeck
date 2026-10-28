import { AlertTriangle, ArrowUpCircle } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import type { RemovedLevel } from '../../../lib/cardShop'

/**
 * What the Card shop has to say about a card installed from it (KARTEN-15 AC-1, AC-6, AC-7): "Update available" opens the
 * update, "Removed from the Card shop" names the reason and is red when the card was taken back as harmful. The card
 * itself goes on running either way.
 */
export function ShopNote({
  update,
  removed,
  onUpdate,
  compact = false,
}: {
  update: boolean
  removed: { level: RemovedLevel; reason: string } | null
  onUpdate?: () => void
  compact?: boolean
}) {
  const { t } = useTranslation()
  if (!update && !removed) return null
  const harmful = removed?.level === 'harmful'
  const why = removed ? `${t('cards.shop.removed')}${removed.reason ? `: ${removed.reason}` : ''}` : ''
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5 min-w-0" data-testid="shop-note">
      {removed && (
        <span className={`inline-flex items-center gap-1 text-[11px] min-w-0 ${harmful ? 'text-bad font-medium' : 'text-warn'}`} title={why} data-level={removed.level} data-testid="shop-note-removed">
          <AlertTriangle size={12} aria-hidden="true" className="flex-none" />
          <span className={compact ? 'truncate' : 'break-words'}>{compact ? t('cards.shop.removed') : why}</span>
        </span>
      )}
      {update && !removed && onUpdate && (
        <button type="button" className="inline-flex items-center gap-1 text-[11px] text-accent hover:underline" onClick={onUpdate} data-testid="shop-note-update">
          <ArrowUpCircle size={12} aria-hidden="true" className="flex-none" />
          {t('cards.shop.updateAvailable')}
        </button>
      )}
      {update && !removed && !onUpdate && (
        <span className="inline-flex items-center gap-1 text-[11px] text-accent min-w-0" data-testid="shop-note-update">
          <ArrowUpCircle size={12} aria-hidden="true" className="flex-none" />
          <span className="truncate">{t('cards.shop.updateAvailable')}</span>
        </span>
      )}
    </span>
  )
}
