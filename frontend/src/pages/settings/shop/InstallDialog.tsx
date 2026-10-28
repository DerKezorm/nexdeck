import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, post } from '../../../api/client'
import { Dialog, Field, Select } from '../../../components/ui'
import { documentKey, importFailure, type ImportChoice, type ImportDocument } from '../../../lib/cardExchange'
import { entryPath, SHOP_CATALOG_KEY, SHOP_STATE_KEY, type ShopEntry, type ShopInstalledAnswer, type ShopInstallCheck } from '../../../lib/cardShop'
import { pickText } from '../../../lib/cardText'

type Answer = ImportChoice | 'cancel'
const ANSWERS: Answer[] = ['replace', 'copy', 'cancel']

/** The queries that show cards, integrations and the shop itself, refreshed when something came in. */
const LISTS = [['custom-cards'], ['cards-library'], ['own-integrations'], ['adapters'], ['cards-sources'], ['integrations'], SHOP_CATALOG_KEY, SHOP_STATE_KEY, ['workshop-entry'], ['workshop-updates']]

/** What the install itself says went wrong, in the words of the interface; anything else is worded as an import is. */
const OWN = ['checksum_mismatch', 'needs_newer_nexdeck', 'entry_removed', 'risk_not_acknowledged', 'no_such_entry', 'github_unreachable', 'github_rejected', 'github_rate_limited', 'catalog_invalid']

/**
 * Install from the shop (KARTEN-14 AC-7 to AC-9, EC-1 to EC-4). The server first says what installing would do, then does
 * all of it or nothing: the card, the own integrations on offer, the choices for names that are taken. Before the first
 * install each administrator reads once that cards of the shop come from strangers and run at their own risk.
 */
export function InstallDialog({
  entry,
  riskAcknowledged,
  connections,
  open,
  onClose,
  onInstalled,
}: {
  entry: ShopEntry
  riskAcknowledged: boolean
  connections: { id: number; name: string }[]
  open: boolean
  onClose: () => void
  onInstalled: (answer: ShopInstalledAnswer, connection: number | null) => void
}) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const [answers, setAnswers] = useState<Record<string, Answer>>({})
  const [taking, setTaking] = useState<Record<string, boolean>>({})
  const [understood, setUnderstood] = useState(false)
  const [connection, setConnection] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const check = useQuery({
    queryKey: ['workshop-install-check', entry.id, entry.version],
    queryFn: () => post<ShopInstallCheck>(`/workshop/entries/${entryPath(entry)}/install/check`, {}),
    enabled: open,
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 0,
    gcTime: 0,
  })

  const result = check.data
  const documents: ImportDocument[] = result?.documents ?? []
  const offered = result?.offered_integrations ?? []
  const needRisk = !(riskAcknowledged || result?.risk_acknowledged)
  const problems = documents.some((document) => (document.problems ?? []).length > 0)
  const undecided = documents.filter((document) => document.exists && !answers[documentKey(document)])
  const stopped = Object.values(answers).includes('cancel')
  const ready = result !== undefined && documents.length > 0 && !problems && undecided.length === 0 && !stopped && (!needRisk || understood)
  const picked = connections.find((one) => String(one.id) === connection) ?? connections[0] ?? null
  const failureText = (failure: unknown) => {
    if (failure instanceof ApiError && OWN.includes(failure.code)) return t(`cards.shop.errors.${failure.code}`, { defaultValue: failure.message, version: entry.min_nexdeck ?? '' })
    return importFailure(t, failure)
  }

  const close = () => {
    setAnswers({})
    setTaking({})
    setUnderstood(false)
    setError('')
    onClose()
  }

  const run = async () => {
    if (!result) return
    setBusy(true)
    setError('')
    const choices: Record<string, ImportChoice> = {}
    for (const document of documents) if (document.exists) choices[documentKey(document)] = answers[documentKey(document)] as ImportChoice
    const withIntegrations = offered.filter((one) => taking[one.id] !== false).map((one) => one.id)
    try {
      const answer = await post<ShopInstalledAnswer>(`/workshop/entries/${entryPath(entry)}/install`, { choices, with_integrations: withIntegrations, accept_risk: needRisk ? understood : true })
      await Promise.all(LISTS.map((queryKey) => queryClient.invalidateQueries({ queryKey })))
      onInstalled(answer, picked?.id ?? null)
      close()
    } catch (failure) {
      setError(failureText(failure))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open={open}
      onClose={close}
      title={t('cards.shop.install.title', { name: pickText(entry.name, i18n.language) || entry.slug })}
      size="md"
      footer={
        <>
          <button className="btn" onClick={close}>
            {t('common.cancel')}
          </button>
          <button className="btn btn-accent" disabled={busy || !ready} onClick={() => void run()}>
            {t('cards.shop.install.action')}
          </button>
        </>
      }
    >
      {check.isPending && (
        <p className="text-sm text-muted" role="status">
          {t('cards.shop.install.checking')}
        </p>
      )}
      {check.isError && (
        <p className="text-sm text-bad" role="alert" data-testid="install-check-failed">
          {failureText(check.error)}
        </p>
      )}

      {needRisk && result && (
        <div className="rounded-xl border border-warn/50 p-3 mb-3" role="note" data-testid="install-risk">
          <p className="text-sm font-medium mb-1">{t('cards.shop.install.riskTitle')}</p>
          <p className="text-sm mb-2">{t('cards.shop.install.riskBody')}</p>
          <label className="inline-flex items-center gap-2 text-sm">
            <input type="checkbox" className="accent-accent" checked={understood} onChange={(event) => setUnderstood(event.target.checked)} />
            {t('cards.shop.install.riskCheck')}
          </label>
        </div>
      )}

      {result && connections.length > 1 && (
        <Field label={t('cards.shop.install.connection')} help={t('cards.shop.install.connectionHelp')}>
          <Select value={String(picked?.id ?? '')} onChange={setConnection} options={connections.map((one) => ({ value: String(one.id), label: one.name }))} />
        </Field>
      )}
      {result && connections.length === 1 && <p className="text-sm mb-3">{t('cards.shop.install.connectionOne', { name: connections[0].name })}</p>}
      {result && entry.type === 'card' && connections.length === 0 && <p className="text-sm text-warn mb-3">{t('cards.shop.install.noConnection')}</p>}

      {offered.length > 0 && (
        <fieldset className="mb-3" data-testid="install-offered">
          <legend className="text-[12px] text-faint mb-1">{t('cards.shop.install.offered')}</legend>
          {offered.map((one) => (
            <label key={one.id} className="flex items-center gap-2 text-sm py-0.5">
              <input type="checkbox" className="accent-accent" checked={taking[one.id] !== false} onChange={(event) => setTaking((current) => ({ ...current, [one.id]: event.target.checked }))} />
              {t('cards.shop.install.alsoAdd', { name: pickText(one.name, i18n.language) || one.slug })}
            </label>
          ))}
        </fieldset>
      )}

      {result && result.missing_integrations.length > 0 && (
        <p className="text-sm text-warn mb-3" role="note" data-testid="install-missing">
          {t('cards.exchange.missing', { kinds: result.missing_integrations.map((kind) => kind.replace(/^custom:/, '')).join(', ') })}
        </p>
      )}

      {documents.some((document) => document.exists) && (
        <div className="grid gap-3 mb-3">
          {documents
            .filter((document) => document.exists)
            .map((document) => {
              const key = documentKey(document)
              return (
                <fieldset key={key} className="rounded-xl border border-line p-3" data-testid={`install-conflict-${key}`}>
                  <legend className="text-[12px] text-warn px-1">{`${pickText(document.name, i18n.language) || key} · ${t(document.same ? 'cards.exchange.existsSame' : 'cards.exchange.exists')}`}</legend>
                  <div className="flex flex-wrap gap-x-4 gap-y-1">
                    {ANSWERS.map((answer) => (
                      <label key={answer} className="inline-flex items-center gap-1.5 text-sm">
                        <input type="radio" className="accent-accent" name={`install-${key}`} checked={answers[key] === answer} onChange={() => setAnswers((current) => ({ ...current, [key]: answer }))} />
                        {t(`cards.exchange.${answer}`)}
                      </label>
                    ))}
                  </div>
                </fieldset>
              )
            })}
        </div>
      )}

      {documents.some((document) => (document.problems ?? []).length > 0) && (
        <p className="text-sm text-bad mb-3" role="alert">
          {t('cards.shop.install.problems')}
        </p>
      )}

      {error && (
        <p className="text-sm text-bad" role="alert" data-testid="install-error">
          {error}
        </p>
      )}
    </Dialog>
  )
}
