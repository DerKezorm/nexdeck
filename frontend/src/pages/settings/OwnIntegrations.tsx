import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Pencil, Plus, Share2, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'

import { ApiError, del, downloadGet, get } from '../../api/client'
import { ServiceIcon } from '../../components/ServiceIcon'
import { Confirm, EmptyState } from '../../components/ui'
import { exportName } from '../../lib/cardExchange'
import { unchangedFromShop } from '../../lib/cardShare'
import { ShareDialog } from './share/ShareDialog'

/** One own integration in the list (`GET /own-integrations`). */
export interface OwnIntegrationRow {
  short: string
  kind: string
  name: string
  logo: string
  description: string
  connections: number
  updated_at: string
  updated_by: string
  /** Set when it came from the Card shop; with `locally_changed` false it is as the shop has it and is not shared again (KARTEN-16). */
  shop_ref?: string
  locally_changed?: boolean
}

/** The most own integrations an installation keeps (KARTEN-3 AC-12). */
export const MAX_OWN_INTEGRATIONS = 50

export const OWN_INTEGRATIONS_KEY = ['own-integrations']

/**
 * System > Custom cards > Integrations (KARTEN-3): the services nexdeck does not know, described by an administrator.
 * "Describe an integration" and "Edit" lead to the editor, a page of its own; deleting asks first and says what
 * happens to the connections and cards that use it.
 */
export function useOwnIntegrations() {
  return useQuery({ queryKey: OWN_INTEGRATIONS_KEY, queryFn: () => get<OwnIntegrationRow[]>('/own-integrations') })
}

/** An integration that came from the Card shop and was not changed since has nothing of its own to share. */
const sameAsShop = (row: OwnIntegrationRow) => Boolean(row.shop_ref) && unchangedFromShop(row)

export function OwnIntegrations() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const list = useOwnIntegrations()
  const [removing, setRemoving] = useState<OwnIntegrationRow | null>(null)
  const [sharing, setSharing] = useState<OwnIntegrationRow | null>(null)
  const [error, setError] = useState('')
  const rows = list.data ?? []

  const openNew = () => navigate('/system/custom-cards/integrations/new')
  const save = async (row: OwnIntegrationRow) => {
    setError('')
    try {
      await downloadGet(`/own-integrations/${encodeURIComponent(row.short)}/export`, exportName(row.short))
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : t('errors.network'))
    }
  }

  const remove = async (row: OwnIntegrationRow) => {
    setError('')
    try {
      await del(`/own-integrations/${encodeURIComponent(row.short)}`)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: OWN_INTEGRATIONS_KEY }),
        queryClient.invalidateQueries({ queryKey: ['adapters'] }),
        queryClient.invalidateQueries({ queryKey: ['cards-sources'] }),
        queryClient.invalidateQueries({ queryKey: ['integrations'] }),
      ])
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : t('errors.network'))
    }
  }

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <p className="text-sm text-muted min-w-0 flex-1 basis-60">{t('cards.integrations.lead')}</p>
        <button className="btn btn-accent" onClick={openNew} disabled={rows.length >= MAX_OWN_INTEGRATIONS}>
          <Plus size={15} /> {t('cards.integrations.describe')}
        </button>
      </div>
      {error && (
        <p className="text-sm text-bad mb-3" role="alert">
          {error}
        </p>
      )}
      {list.isError && (
        <p className="text-sm text-bad mb-3" role="alert">
          {t('errors.network')}
        </p>
      )}
      {list.isSuccess && rows.length === 0 && (
        <EmptyState
          title={t('cards.integrations.emptyTitle')}
          body={t('cards.integrations.emptyBody')}
          action={
            <button className="btn btn-accent" onClick={openNew}>
              <Plus size={15} /> {t('cards.integrations.describe')}
            </button>
          }
        />
      )}
      {rows.length > 0 && (
        <>
          <ul className="divide-y divide-line" data-testid="own-integrations">
            {rows.map((row) => (
              <li key={row.short} className="py-3 flex flex-wrap items-center gap-x-3 gap-y-1.5">
                <ServiceIcon icon={row.logo || row.kind} size={28} />
                <div className="min-w-0 flex-1 basis-48">
                  <div className="text-sm font-medium truncate">{row.name}</div>
                  <div className="text-[11px] text-muted truncate">
                    <span className="chip !py-0 mr-1.5">{t('cards.integrations.custom')}</span>
                    {row.kind}
                  </div>
                </div>
                <div className="text-sm text-muted">{t('cards.integrations.connections', { count: row.connections })}</div>
                <div className="flex items-center justify-end gap-0.5">
                  <button className="btn btn-icon btn-flat" onClick={() => navigate(`/system/custom-cards/integrations/${encodeURIComponent(row.short)}/edit`)} aria-label={t('cards.editNamed', { name: row.name })} title={t('cards.edit')}>
                    <Pencil size={15} />
                  </button>
                  <button className="btn btn-icon btn-flat" onClick={() => void save(row)} aria-label={t('cards.exchange.exportNamed', { name: row.name })} title={t('cards.exchange.export')}>
                    <Download size={15} />
                  </button>
                  <button
                    className="btn btn-icon btn-flat"
                    onClick={() => setSharing(row)}
                    aria-label={t('cards.share.buttonNamed', { name: row.name })}
                    title={sameAsShop(row) ? t('cards.share.problem.unchanged_from_shop') : t('cards.share.button')}
                    disabled={sameAsShop(row)}
                  >
                    <Share2 size={15} />
                  </button>
                  <button className="btn btn-icon btn-flat btn-danger" onClick={() => setRemoving(row)} aria-label={t('cards.deleteNamed', { name: row.name })} title={t('cards.delete')}>
                    <Trash2 size={15} />
                  </button>
                </div>
              </li>
            ))}
          </ul>
          <p className="text-xs text-muted mt-3">{t('cards.integrations.footer', { count: rows.length, limit: MAX_OWN_INTEGRATIONS })}</p>
        </>
      )}
      {sharing && <ShareDialog kind="integration" slug={sharing.short} name={sharing.name} open onClose={() => setSharing(null)} />}
      <Confirm
        open={removing !== null}
        title={t('cards.integrations.deleteTitle', { name: removing?.name ?? '' })}
        body={removing && removing.connections === 0 ? t('cards.integrations.deleteBodyNone') : t('cards.integrations.deleteBody', { count: removing?.connections ?? 0 })}
        danger
        confirmLabel={t('cards.delete')}
        onCancel={() => setRemoving(null)}
        onConfirm={() => {
          const row = removing
          setRemoving(null)
          if (row) void remove(row)
        }}
      />
    </>
  )
}
