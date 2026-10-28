import { Search } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { EmptyState, Select } from '../../../components/ui'
import {
  narrowed,
  NO_FILTERS,
  rememberFits,
  SHOP_CATEGORIES,
  SHOP_SORTS,
  shopList,
  storedFits,
  visible,
  type ShopCatalog,
  type ShopEntry,
  type ShopFilters,
  type ShopState,
} from '../../../lib/cardShop'
import { useShopSwitch } from './hooks'
import { ShopTile } from './ShopTile'

/** The tiles drawn at first; more come with "Show more". A catalog of a thousand entries stays smooth this way (KARTEN-14 EC-8). */
export const PAGE = 48

/**
 * The shop with its catalog (KARTEN-14 AC-3, AC-4): search, filters, sorting and the tiles. Search, filters and sorting
 * work on the list the server sent, so the list changes at once. "Fits my connections" is on at first and remembered for
 * this browser (EC-9).
 */
export function ShopList({ catalog, onOpen }: { catalog: ShopCatalog; state: ShopState; onOpen?: (entry: ShopEntry) => void }) {
  const { t, i18n } = useTranslation()
  const switchShop = useShopSwitch()
  const [filters, setFilters] = useState<ShopFilters>(() => ({ ...NO_FILTERS, fits: storedFits() }))
  const [limit, setLimit] = useState(PAGE)
  const lang = i18n.language

  const entries = useMemo(() => catalog.entries.filter(visible), [catalog.entries])
  const shown = useMemo(() => shopList(entries, filters, lang), [entries, filters, lang])
  // A new search or filter starts at the top of the list again.
  useEffect(() => setLimit(PAGE), [filters])

  const change = (next: Partial<ShopFilters>) => {
    if (next.fits !== undefined) rememberFits(next.fits)
    setFilters((current) => ({ ...current, ...next }))
  }
  const clear = () => {
    rememberFits(false)
    setFilters({ ...NO_FILTERS, sort: filters.sort })
  }

  const categories = [{ value: 'all', label: t('cards.shop.allCategories') }, ...SHOP_CATEGORIES.map((one) => ({ value: one, label: t(`cards.shop.category.${one}`) }))]
  const types = [
    { value: 'all', label: t('cards.shop.allTypes') },
    { value: 'card', label: t('cards.shop.type.cards') },
    { value: 'integration', label: t('cards.shop.type.integrations') },
  ]
  const sorts = SHOP_SORTS.map((one) => ({ value: one, label: t(`cards.shop.sort.${one}`) }))

  return (
    <div data-testid="shop-list">
      {catalog.warning && (
        <p className="text-sm text-warn mb-3" role="status" data-testid="shop-stale">
          {t('cards.shop.stale', { time: new Date(catalog.fetched_at).toLocaleString(lang) })}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <div className="relative flex-1 basis-56 min-w-0">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" aria-hidden="true" />
          <input className="input input-icon" aria-label={t('cards.shop.search')} placeholder={t('cards.shop.search')} value={filters.query} onChange={(event) => change({ query: event.target.value })} />
        </div>
        <Select className="!w-auto" value={filters.category} onChange={(value) => change({ category: value as ShopFilters['category'] })} options={categories} id="shop-category" />
        <Select className="!w-auto" value={filters.type} onChange={(value) => change({ type: value as ShopFilters['type'] })} options={types} id="shop-type" />
        <Select className="!w-auto" value={filters.sort} onChange={(value) => change({ sort: value as ShopFilters['sort'] })} options={sorts} id="shop-sort" />
      </div>
      <label className="inline-flex items-center gap-2 text-sm mb-3">
        <input type="checkbox" className="accent-accent" checked={filters.fits} onChange={(event) => change({ fits: event.target.checked })} />
        {t('cards.shop.fits')}
      </label>

      {shown.length === 0 ? (
        <EmptyState
          title={t('cards.shop.noMatch')}
          action={
            narrowed(filters) ? (
              <button className="btn" onClick={clear}>
                {t('cards.shop.clear')}
              </button>
            ) : undefined
          }
        />
      ) : (
        <>
          <p className="text-xs text-muted mb-2" role="status">
            {t('cards.shop.count', { count: shown.length })}
          </p>
          <ul className="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4" aria-label={t('cards.shop.list')}>
            {shown.slice(0, limit).map((entry) => (
              <ShopTile key={entry.id} entry={entry} onOpen={onOpen} />
            ))}
          </ul>
          {shown.length > limit && (
            <div className="flex justify-center mt-4">
              <button className="btn" onClick={() => setLimit(limit + PAGE)}>
                {t('cards.shop.more', { count: shown.length - limit })}
              </button>
            </div>
          )}
        </>
      )}
      <p className="text-xs text-muted mt-4 flex flex-wrap items-center gap-x-3">
        <button className="text-accent hover:underline" disabled={switchShop.busy} onClick={() => void switchShop.set(false)}>
          {t('cards.shop.turnOff')}
        </button>
      </p>
      {switchShop.error && (
        <p className="text-sm text-bad" role="alert">
          {switchShop.error}
        </p>
      )}
    </div>
  )
}
