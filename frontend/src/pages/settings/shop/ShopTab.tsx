import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Spinner } from '../../../components/ui'
import { SHOP_CATALOG_KEY } from '../../../lib/cardShop'
import { codeOf, useShopCatalog, useShopState, useShopSwitch } from './hooks'
import { ShopDetailPage } from './ShopDetailPage'
import { ShopList } from './ShopList'

/** The shop while it is off: one sentence, "Turn on", and what the shop sends (KARTEN-14 AC-2, AC-13). */
function ShopOff() {
  const { t } = useTranslation()
  const shop = useShopSwitch()
  const [explaining, setExplaining] = useState(false)
  return (
    <div className="rounded-xl border border-line p-5 grid gap-3 justify-items-start" data-testid="shop-off">
      <h3 className="font-semibold text-[15px]">{t('cards.shop.offTitle')}</h3>
      <p className="text-sm text-muted">{t('cards.shop.offLead')}</p>
      <div className="flex flex-wrap items-center gap-2">
        <button className="btn btn-accent" disabled={shop.busy} onClick={() => void shop.set(true)}>
          {t('cards.shop.turnOn')}
        </button>
        <button className="btn btn-flat" aria-expanded={explaining} onClick={() => setExplaining(!explaining)}>
          {t('cards.shop.whatItSends')}
        </button>
      </div>
      {explaining && (
        <p className="text-sm" role="note" data-testid="shop-sends">
          {t('cards.shop.sendsBody')}
        </p>
      )}
      {shop.error && (
        <p className="text-sm text-bad" role="alert">
          {shop.error}
        </p>
      )}
    </div>
  )
}

const KNOWN = ['github_unreachable', 'github_rejected', 'github_rate_limited', 'catalog_invalid', 'catalog_empty']

/** The reason there is no list: GitHub did not answer, or the catalog is empty or broken. Installed cards go on (AC-10, EC-6). */
function ShopProblem({ code, onAgain }: { code: string; onAgain: () => void }) {
  const { t } = useTranslation()
  const kind = KNOWN.includes(code) ? code : 'other'
  return (
    <div className="rounded-xl border border-line p-5 grid gap-3 justify-items-start" role="alert" data-testid="shop-problem" data-code={code || 'other'}>
      <h3 className="font-semibold text-[15px] text-bad">{t(`cards.shop.problem.${kind}.title`)}</h3>
      <p className="text-sm text-muted">{t(`cards.shop.problem.${kind}.body`)}</p>
      <button className="btn" onClick={onAgain}>
        {t('cards.shop.tryAgain')}
      </button>
    </div>
  )
}

/**
 * The Card shop tab of System > Custom cards (KARTEN-14): off, a problem with the catalog, or the list.
 * The catalog is asked only once the shop is on.
 */
export function ShopTab() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const state = useShopState()
  const enabled = state.data?.enabled === true
  const catalog = useShopCatalog(enabled)
  // Which entry is open is kept here, so "back" lands on the same list with the same search.
  const [opened, setOpened] = useState<string | null>(null)

  if (state.isPending) return <Spinner />
  if (state.isError || !state.data) {
    return (
      <p className="text-sm text-bad" role="alert">
        {t('errors.network')}
      </p>
    )
  }
  if (!enabled) return <ShopOff />
  if (catalog.isPending) {
    return (
      <p className="text-sm text-muted" role="status">
        {t('cards.shop.loading')}
      </p>
    )
  }
  if (catalog.isError || !catalog.data) {
    return <ShopProblem code={codeOf(catalog.error)} onAgain={() => void queryClient.invalidateQueries({ queryKey: SHOP_CATALOG_KEY })} />
  }
  const current = opened ? catalog.data.entries.find((one) => one.id === opened) : undefined
  return (
    <>
      {current && <ShopDetailPage entry={current} entries={catalog.data.entries} state={state.data} onBack={() => setOpened(null)} onOpenEntry={setOpened} />}
      <div hidden={current !== undefined}>
        <ShopList catalog={catalog.data} state={state.data} onOpen={(one) => setOpened(one.id)} />
      </div>
    </>
  )
}
