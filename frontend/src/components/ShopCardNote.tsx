import { useTranslation } from 'react-i18next'
import { Link, useInRouterContext } from 'react-router-dom'

import { useShopUpdates } from '../pages/settings/shop/hooks'
import { ShopNote } from '../pages/settings/shop/ShopNote'

/**
 * On a card of the Card shop, for administrators only: "Update available" or "Removed from the Card shop" with the reason,
 * red when it was taken back as harmful (KARTEN-15 AC-6, AC-7). It leads to Custom cards, where the update is taken.
 * The notes come from the one list of updates that every card on the board shares.
 */
export function ShopCardNote({ slug }: { slug: string }) {
  const { t } = useTranslation()
  const inRouter = useInRouterContext()
  const updates = useShopUpdates()
  const removed = updates.data?.removed.find((one) => one.slug === slug) ?? null
  const update = updates.data?.updates.find((one) => one.slug === slug) ?? null
  if (!removed && !update) return null
  const note = <ShopNote compact update={Boolean(update)} removed={removed ? { level: removed.level, reason: removed.reason } : null} />
  const label = removed ? `${t('cards.shop.removed')}${removed.reason ? `: ${removed.reason}` : ''}` : t('cards.shop.updateAvailable')
  const frame = 'max-w-[55%] min-w-0 hidden @min-[240px]:inline-flex'
  // An update waits as a plain mark here: taking it is a decision for the page that lists the cards.
  return inRouter ? (
    <Link to="/system/cards" className={frame} title={label} aria-label={label} data-testid="card-shop-note">
      {note}
    </Link>
  ) : (
    <a href="/system/cards" className={frame} title={label} aria-label={label} data-testid="card-shop-note">
      {note}
    </a>
  )
}
