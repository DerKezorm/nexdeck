/**
 * The update of a skin from the Card shop (skins, phase D): the two versions, the list of changes, and whether to keep
 * what was changed here as a copy. A skin reads and presses nothing, so there is nothing to confirm one by one as with a
 * card; whoever wears it wears the new version at once.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, get, post } from '../../../api/client'
import { Dialog } from '../../../components/ui'
import { SHOP_CATALOG_KEY, SHOP_UPDATES_KEY } from '../../../lib/cardShop'
import type { CardText } from '../../../lib/cardText'
import { pickText } from '../../../lib/cardText'
import { Changelog } from './Changelog'

/** The queries that show skins and the shop, refreshed when a skin took a new version. */
const LISTS = [['skins'], ['appearance'], ['workshop-entry'], SHOP_CATALOG_KEY, SHOP_UPDATES_KEY]

export interface SkinUpdate {
  key: string
  name: CardText
  installed_version: string
  new_version: string
  needs_newer: boolean
  min_nexdeck: string | null
  changelog: string | null
  locally_changed: boolean
}

export function SkinUpdateDialog({ skin, open, onClose }: { skin: string; open: boolean; onClose: () => void }) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const [keepMine, setKeepMine] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState<{ copy_key: string | null } | null>(null)
  const update = useQuery({
    queryKey: ['workshop-skin-update', skin],
    queryFn: () => get<SkinUpdate>(`/workshop/updates/skins/${encodeURIComponent(skin)}`),
    enabled: open && skin !== '',
    retry: false,
    gcTime: 0,
  })
  const found = update.data

  const close = () => {
    setError('')
    setDone(null)
    onClose()
  }

  const take = async () => {
    if (!found) return
    setBusy(true)
    setError('')
    try {
      const answer = await post<{ status: string; copy_key: string | null }>(`/workshop/updates/skins/${encodeURIComponent(skin)}/accept`, {
        keep_mine: keepMine,
        expected_version: found.new_version,
      })
      await Promise.all(LISTS.map((queryKey) => queryClient.invalidateQueries({ queryKey })))
      setDone({ copy_key: answer.copy_key })
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : t('errors.network'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open={open}
      onClose={close}
      title={t('cards.shop.skinUpdate.title', { name: found ? pickText(found.name, i18n.language) || skin : skin })}
      size="md"
      footer={
        done ? (
          <button className="btn btn-accent" onClick={close}>
            {t('common.close')}
          </button>
        ) : (
          <>
            <button className="btn" onClick={close}>
              {t('common.cancel')}
            </button>
            <button className="btn btn-accent" disabled={busy || !found || found.needs_newer} onClick={() => void take()}>
              {t('cards.shop.skinUpdate.action')}
            </button>
          </>
        )
      }
    >
      <div className="grid gap-3" data-testid="skin-update">
        {update.isError && (
          <p className="text-sm text-bad" role="alert">
            {update.error instanceof ApiError ? update.error.message : t('errors.network')}
          </p>
        )}
        {found && !done && (
          <>
            <p className="text-sm">{t('cards.shop.skinUpdate.lead', { from: found.installed_version, to: found.new_version })}</p>
            {found.needs_newer && <p className="text-sm text-warn">{t('cards.shop.needsNexdeck', { version: found.min_nexdeck ?? '' })}</p>}
            <Changelog text={found.changelog ?? ''} installed={found.installed_version} testId="skin-update-changelog" />
            {found.locally_changed && (
              <label className="inline-flex items-center gap-2 text-sm">
                <input type="checkbox" className="accent-accent" checked={keepMine} onChange={(event) => setKeepMine(event.target.checked)} />
                {t('cards.shop.skinUpdate.keepMine')}
              </label>
            )}
          </>
        )}
        {done && (
          <p className="text-sm text-ok" role="status">
            {done.copy_key ? t('cards.shop.skinUpdate.doneCopy', { key: done.copy_key }) : t('cards.shop.skinUpdate.done')}
          </p>
        )}
        {error && (
          <p className="text-sm text-bad" role="alert">
            {error}
          </p>
        )}
      </div>
    </Dialog>
  )
}
