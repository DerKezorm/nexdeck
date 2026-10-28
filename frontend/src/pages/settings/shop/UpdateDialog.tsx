import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, get, post } from '../../../api/client'
import { Dialog } from '../../../components/ui'
import { SHOP_CATALOG_KEY, SHOP_UPDATES_KEY, type ShopButtonText, type ShopUpdate } from '../../../lib/cardShop'
import { pickText } from '../../../lib/cardText'
import { Changelog } from './Changelog'

/** The queries that show cards and the shop, refreshed when a card took a new version; the boards follow at once. */
const LISTS = [['custom-cards'], ['cards-library'], ['workshop-entry'], ['board'], SHOP_CATALOG_KEY, SHOP_UPDATES_KEY]

interface Accepted {
  status: 'updated' | 'already_up_to_date'
  slug: string
  version: string
  copy_slug: string | null
}

/** What a button asks or shows besides what it sends, so that a change in it can be seen (KARTEN-15 AC-3). */
function flags(t: (key: string, options?: Record<string, unknown>) => string, button: ShopButtonText): string[] {
  const found: string[] = []
  if (button.confirm) found.push(t('cards.shop.update.flag.confirm'))
  if (button.danger) found.push(t('cards.shop.update.flag.danger'))
  if (button.asks && button.asks.length > 0) found.push(t('cards.shop.update.flag.asks', { names: button.asks.map((one) => one.name).join(', ') }))
  if (button.answer) found.push(t('cards.shop.update.flag.answer'))
  return found
}

/** A button as a line: its label and what it does to the service (method, address, and the content it sends), and how it asks first. */
function ButtonLine({ button }: { button: ShopButtonText }) {
  const { t, i18n } = useTranslation()
  const content = button.body === undefined || button.body === null ? '' : ` ${JSON.stringify(button.body)}`
  const more = flags(t, button)
  return (
    <span className="break-words">
      {pickText(button.label, i18n.language) || button.id} <span className="font-mono text-[12px] text-muted">{`${button.method} ${button.path}${content}`}</span>
      {more.length > 0 && <span className="text-[12px] text-muted">{` · ${more.join(' · ')}`}</span>}
    </span>
  )
}

/** What the server answered, as a sentence of the interface: its own words for the codes this dialog meets. */
function failureText(t: (key: string, options?: Record<string, unknown>) => string, failure: unknown, version: string): string {
  if (!(failure instanceof ApiError)) return t('errors.network')
  const own = [
    'update_changed', 'buttons_not_confirmed', 'needs_newer_nexdeck', 'entry_removed', 'checksum_mismatch', 'not_installed_from_shop', 'no_update', 'github_unreachable',
    'update_invalid', 'too_many_cards', 'copy_failed', 'github_rejected', 'github_rate_limited', 'catalog_invalid', 'type_mismatch',
  ]
  if (own.includes(failure.code)) return t(`cards.shop.update.errors.${failure.code}`, { defaultValue: failure.message, version })
  return failure.message
}

/**
 * The update of a card from the shop (KARTEN-15 AC-2 to AC-5, EC-1, EC-2, EC-5, EC-6): what the author changed, what the new
 * version may do that the old one could not, every new or changed button to be confirmed one by one, and a warning when the
 * card was changed here (with "Keep mine as a copy" ticked). "Later" closes the dialog and the notice stays.
 */
export function UpdateDialog({ slug, name: known, open, onClose }: { slug: string; name: string; open: boolean; onClose: () => void }) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const [confirmed, setConfirmed] = useState<Record<string, boolean>>({})
  const [keepMine, setKeepMine] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<Accepted | null>(null)

  const update = useQuery({
    queryKey: ['workshop-update', slug],
    queryFn: () => get<ShopUpdate>(`/workshop/updates/${encodeURIComponent(slug)}`),
    enabled: open && slug !== '',
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 0,
    gcTime: 0,
  })

  const data = update.data
  const toConfirm = data?.buttons_to_confirm ?? []
  const allConfirmed = toConfirm.every((id) => confirmed[id])
  const blocked = data?.needs_newer === true
  const name = (data ? pickText(data.name, i18n.language) : '') || known || slug
  const buttons = data?.permissions.buttons
  const requests = data?.permissions.requests
  const requires = data?.permissions.requires
  const nothingNew = !!data && !buttons?.added.length && !buttons?.changed.length && !buttons?.removed.length && !requests?.added.length && !requests?.changed.length && !requests?.removed.length && !requires?.added.length && !requires?.removed.length

  const close = () => {
    setConfirmed({})
    setKeepMine(true)
    setError('')
    setResult(null)
    onClose()
  }

  const accept = async () => {
    if (!data) return
    setBusy(true)
    setError('')
    try {
      const answer = await post<Accepted>(`/workshop/updates/${encodeURIComponent(slug)}/accept`, {
        confirmed_buttons: toConfirm.filter((id) => confirmed[id]),
        keep_mine: keepMine,
        expected_version: data.new_version,
      })
      await Promise.all(LISTS.map((queryKey) => queryClient.invalidateQueries({ queryKey })))
      setResult(answer)
    } catch (failure) {
      setError(failureText(t, failure, data.min_nexdeck ?? ''))
      if (failure instanceof ApiError && failure.code === 'update_changed') void update.refetch()
    } finally {
      setBusy(false)
    }
  }

  const missing = update.isError && update.error instanceof ApiError && update.error.code === 'no_update'

  return (
    <Dialog
      open={open}
      onClose={close}
      title={t('cards.shop.update.title', { name })}
      size="lg"
      footer={
        result ? (
          <button className="btn btn-accent" onClick={close}>
            {t('common.close')}
          </button>
        ) : (
          <>
            <button className="btn" onClick={close}>
              {t('cards.shop.update.later')}
            </button>
            <button className="btn btn-accent" disabled={busy || !data || blocked || !allConfirmed} onClick={() => void accept()}>
              {t('cards.shop.update.accept')}
            </button>
          </>
        )
      }
    >
      {update.isPending && (
        <p className="text-sm text-muted" role="status">
          {t('cards.shop.update.loading')}
        </p>
      )}
      {update.isError && (
        <p className={`text-sm ${missing ? 'text-muted' : 'text-bad'}`} role={missing ? 'status' : 'alert'} data-testid="update-failed">
          {missing ? t('cards.shop.update.upToDate') : failureText(t, update.error, '')}
        </p>
      )}

      {result && (
        <div className="grid gap-1" role="status" data-testid="update-done">
          <p className="text-sm">{result.status === 'already_up_to_date' ? t('cards.shop.update.upToDate') : t('cards.shop.update.done', { version: result.version })}</p>
          {result.copy_slug && <p className="text-sm text-muted">{t('cards.shop.update.copyMade', { slug: result.copy_slug })}</p>}
        </div>
      )}

      {data && !result && (
        <div className="grid gap-4">
          <p className="text-sm">
            {t('cards.shop.update.versions', { from: data.installed_version, to: data.new_version })}
            {data.placed_on > 0 && <span className="text-muted"> {t('cards.shop.update.placedOn', { count: data.placed_on })}</span>}
          </p>

          {blocked && (
            <p className="text-sm text-warn" role="note" data-testid="update-needs-newer">
              {t('cards.shop.needsNexdeck', { version: data.min_nexdeck ?? '' })}
            </p>
          )}

          {data.locally_changed && (
            <div className="rounded-xl border border-warn/50 p-3" role="note" data-testid="update-local">
              <p className="text-sm mb-2">{t('cards.shop.update.localWarning')}</p>
              <label className="inline-flex items-center gap-2 text-sm">
                <input type="checkbox" className="accent-accent" checked={keepMine} onChange={(event) => setKeepMine(event.target.checked)} />
                {t('cards.shop.update.keepMine')}
              </label>
            </div>
          )}

          <section className="grid gap-1">
            <h4 className="text-[11px] uppercase tracking-wide text-faint">{t('cards.shop.sections.changes')}</h4>
            {data.changelog ? (
              <Changelog text={data.changelog} installed={data.installed_version} testId="update-changelog" />
            ) : (
              <p className="text-sm text-muted">{t('cards.shop.noChanges')}</p>
            )}
          </section>

          <section className="grid gap-1" data-testid="update-permissions">
            <h4 className="text-[11px] uppercase tracking-wide text-faint">{t('cards.shop.update.rights')}</h4>
            {nothingNew && <p className="text-sm text-muted">{t('cards.shop.update.noRights')}</p>}
            {data.connection_changed && (
              <p className="text-sm text-warn" role="note" data-testid="update-connection">
                {t('cards.shop.update.connectionChanged')}
              </p>
            )}
            <ul className="grid gap-1 text-sm">
              {requires?.added.map((kind) => (
                <li key={`ra-${kind}`}>{t('cards.shop.update.needsNow', { kind })}</li>
              ))}
              {requires?.removed.map((kind) => (
                <li key={`rr-${kind}`}>{t('cards.shop.update.needsNoMore', { kind })}</li>
              ))}
              {requests?.added.map((one) => (
                <li key={`qa-${one.id}`}>
                  {t('cards.shop.update.readsNew')} <span className="font-mono text-[12px] text-muted">{one.path}</span>
                </li>
              ))}
              {requests?.changed.map((one) => (
                <li key={`qc-${one.id}`}>
                  {t('cards.shop.update.readsChanged')} <span className="font-mono text-[12px] text-muted">{`${one.before} → ${one.after}`}</span>
                </li>
              ))}
              {requests?.removed.map((one) => (
                <li key={`qr-${one.id}`}>
                  {t('cards.shop.update.readsGone')} <span className="font-mono text-[12px] text-muted">{one.path}</span>
                </li>
              ))}
              {buttons?.added.map((one) => (
                <li key={`ba-${one.id}`}>
                  {t('cards.shop.update.buttonNew')} <ButtonLine button={one} />
                </li>
              ))}
              {buttons?.changed.map((one) => (
                <li key={`bc-${one.after.id}`}>
                  {t('cards.shop.update.buttonChanged')} <ButtonLine button={one.before} /> → <ButtonLine button={one.after} />
                </li>
              ))}
              {buttons?.removed.map((one) => (
                <li key={`br-${one.id}`}>
                  {t('cards.shop.update.buttonGone')} <ButtonLine button={one} />
                </li>
              ))}
            </ul>
          </section>

          {toConfirm.length > 0 && (
            <fieldset className="rounded-xl border border-bad/50 p-3" data-testid="update-confirm">
              <legend className="text-[12px] text-bad px-1">{t('cards.shop.update.confirmButtons')}</legend>
              <p className="text-[12px] text-muted mb-2">{t('cards.shop.update.confirmHelp')}</p>
              {toConfirm.map((id) => {
                const button = [...(buttons?.added ?? []), ...(buttons?.changed.map((one) => one.after) ?? [])].find((one) => one.id === id)
                return (
                  <label key={id} className="flex items-start gap-2 text-sm py-0.5">
                    <input type="checkbox" className="accent-accent mt-1" checked={confirmed[id] === true} onChange={(event) => setConfirmed((current) => ({ ...current, [id]: event.target.checked }))} />
                    <span className="min-w-0">{button ? <ButtonLine button={button} /> : id}</span>
                  </label>
                )
              })}
            </fieldset>
          )}

          {error && (
            <p className="text-sm text-bad" role="alert" data-testid="update-error">
              {error}
            </p>
          )}
        </div>
      )}
    </Dialog>
  )
}
