import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, get, put } from '../../../api/client'
import { SHOP_CATALOG_KEY, SHOP_STATE_KEY, SHOP_UPDATES_KEY, type ShopCatalog, type ShopState, type ShopUpdates } from '../../../lib/cardShop'

/** Whether the shop is on, and what it knows about this administrator (`GET /workshop/state`). It never asks GitHub. */
export function useShopState() {
  return useQuery({ queryKey: SHOP_STATE_KEY, queryFn: () => get<ShopState>('/workshop/state'), staleTime: 30_000 })
}

/**
 * The catalog. Asked only when the shop is on, and each time the tab opens: the server answers from its memory when the
 * last fetch is younger than ten minutes (KARTEN-14 AC-12).
 */
export function useShopCatalog(enabled: boolean) {
  return useQuery({
    queryKey: SHOP_CATALOG_KEY,
    queryFn: () => get<ShopCatalog>('/workshop/catalog'),
    enabled,
    staleTime: 0,
    refetchOnWindowFocus: false,
    retry: false,
  })
}

/** The updates and recalls of the cards installed from the shop. Asked even when the shop is off: the server then answers empty. */
export function useShopUpdates(enabled = true) {
  return useQuery({ queryKey: SHOP_UPDATES_KEY, queryFn: () => get<ShopUpdates>('/workshop/updates'), staleTime: 60_000, enabled })
}

/** Switches the shop on or off. Turning it on asks nothing of GitHub; the first request comes with the catalog. */
export function useShopSwitch() {
  const queryClient = useQueryClient()
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const set = async (enabled: boolean) => {
    setBusy(true)
    setError('')
    try {
      const state = await put<ShopState>('/workshop/settings', { enabled })
      queryClient.setQueryData(SHOP_STATE_KEY, state)
      queryClient.removeQueries({ queryKey: SHOP_CATALOG_KEY })
      await Promise.all([queryClient.invalidateQueries({ queryKey: SHOP_UPDATES_KEY }), queryClient.invalidateQueries({ queryKey: ['custom-cards'] })])
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : t('errors.network'))
    } finally {
      setBusy(false)
    }
  }
  return { set, busy, error }
}

/** The code of a failed request, if it was one the server answered. */
export function codeOf(failure: unknown): string {
  return failure instanceof ApiError ? failure.code : ''
}
