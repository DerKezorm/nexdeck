import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, post } from '../../../api/client'
import { Dialog, Field, Select } from '../../../components/ui'
import { documentKey, importFailure, type ImportChoice, type ImportDocument } from '../../../lib/cardExchange'
import { entryPath, SHOP_CATALOG_KEY, SHOP_STATE_KEY, type ShopEntry, type ShopInstalledAnswer, type ShopInstallCheck } from '../../../lib/cardShop'
import { pickText } from '../../../lib/cardText'
import { ShopActs } from './ShopActs'

type Answer = ImportChoice | 'cancel'
const ANSWERS: Answer[] = ['replace', 'copy', 'cancel']

/** The queries that show cards, integrations and the shop itself, refreshed when something came in. */
const LISTS = [['skins'], ['custom-cards'], ['cards-library'], ['own-integrations'], ['adapters'], ['cards-sources'], ['integrations'], SHOP_CATALOG_KEY, SHOP_STATE_KEY, ['workshop-entry'], ['workshop-updates']]

/** What the install itself says went wrong, in the words of the interface; anything else is worded as an import is. */
const OWN = ['checksum_mismatch', 'needs_newer_nexdeck', 'entry_removed', 'risk_not_acknowledged', 'no_such_entry', 'github_unreachable', 'github_rejected', 'github_rate_limited', 'catalog_invalid', 'type_mismatch', 'definition_unreadable', 'dropped_not_confirmed']

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
  const [lossOk, setLossOk] = useState(false)
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
  // An own connection by the author of the card is ticked at first; one by anybody else waits to be looked at.
  const takes = (one: ShopEntry) => taking[one.id] ?? one.author.id === entry.author.id
  // Replacing an own connection whose new text drops fields throws their stored values away, secrets included.
  const left = (document: ImportDocument) => offered.some((one) => document.type === 'integration' && one.slug === document.short && !takes(one))
  const losing = documents.filter((document) => document.exists && !left(document) && answers[documentKey(document)] === 'replace' && (document.dropped_fields ?? []).length > 0)
  // A skin is one file that becomes one skin under a free name: nothing to choose, only whether this nexdeck can wear it.
  const skin = entry.type === 'skin'
  const fileOk = skin ? result?.ok === true : documents.length > 0 && !problems && undecided.length === 0 && !stopped && (losing.length === 0 || lossOk)
  const ready = result !== undefined && fileOk && (!needRisk || understood)

  const picked = connections.find((one) => String(one.id) === connection) ?? connections[0] ?? null
  const failureText = (failure: unknown) => {
    if (failure instanceof ApiError && OWN.includes(failure.code)) return t(`cards.shop.errors.${failure.code}`, { defaultValue: failure.message, version: entry.min_nexdeck ?? '' })
    return importFailure(t, failure)
  }

  const close = () => {
    setAnswers({})
    setTaking({})
    setUnderstood(false)
    setLossOk(false)
    setError('')
    onClose()
  }

  const run = async () => {
    if (!result) return
    setBusy(true)
    setError('')
    const choices: Record<string, ImportChoice> = {}
    for (const document of documents) if (document.exists) choices[documentKey(document)] = answers[documentKey(document)] as ImportChoice
    const withIntegrations = offered.filter(takes).map((one) => one.id)
    try {
      const answer = await post<ShopInstalledAnswer>(`/workshop/entries/${entryPath(entry)}/install`, { choices, with_integrations: withIntegrations, accept_risk: needRisk ? understood : true, confirm_dropped: losing.length > 0 && lossOk })
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

      {result && (
        <div className="grid gap-3 mb-3" data-testid="install-acts">
          <ShopActs entry={result.entry} />
        </div>
      )}

      {result && connections.length > 1 && (
        <Field label={t('cards.shop.install.connection')} help={t('cards.shop.install.connectionHelp')}>
          <Select value={String(picked?.id ?? '')} onChange={setConnection} options={connections.map((one) => ({ value: String(one.id), label: one.name }))} />
        </Field>
      )}
      {result && connections.length === 1 && <p className="text-sm mb-3">{t('cards.shop.install.connectionOne', { name: connections[0].name })}</p>}
      {result && entry.type === 'card' && connections.length === 0 && <p className="text-sm text-warn mb-3">{t('cards.shop.install.noConnection')}</p>}
      {result && skin && result.ok && <p className="text-sm mb-3">{t('cards.shop.install.skinAs', { key: result.skin_key ?? entry.slug })}</p>}
      {result && skin && !result.ok && (
        <div className="text-sm text-bad mb-3" role="alert" data-testid="install-skin-problems">
          <p>{t('cards.shop.install.problems')}</p>
          <ul className="list-disc pl-5">
            {(result.problems ?? []).slice(0, 8).map((one, index) => (
              <li key={index}>{one.path ? `${one.path}: ${one.message}` : one.message}</li>
            ))}
          </ul>
        </div>
      )}

      {offered.length > 0 && (
        <fieldset className="mb-3" data-testid="install-offered">
          <legend className="text-[12px] text-faint mb-1">{t('cards.shop.install.offered')}</legend>
          {offered.map((one) => (
            <div key={one.id} className="py-0.5">
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" className="accent-accent" checked={takes(one)} onChange={(event) => setTaking((current) => ({ ...current, [one.id]: event.target.checked }))} />
                {t('cards.shop.install.alsoAdd', { name: pickText(one.name, i18n.language) || one.slug, author: one.author.login })}
              </label>
              {one.author.id !== entry.author.id && <p className="text-[12px] text-warn ml-6">{t('cards.shop.install.offeredStranger')}</p>}
            </div>
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
                  <legend className="text-[12px] text-warn float-left w-full mb-1.5">{`${pickText(document.name, i18n.language) || key} · ${t(document.same ? 'cards.exchange.existsSame' : 'cards.exchange.exists')}`}</legend>
                  <div className="clear-both flex flex-wrap gap-x-4 gap-y-1">
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

      {losing.length > 0 && (
        <div className="rounded-xl border border-bad/50 p-3 mb-3" role="alert" data-testid="install-dropped">
          {losing.map((document) => (
            <p key={documentKey(document)} className="text-sm mb-2">
              {t('cards.shop.install.dropped', { name: pickText(document.name, i18n.language) || documentKey(document), fields: (document.dropped_fields ?? []).join(', ') })}
            </p>
          ))}
          <label className="inline-flex items-center gap-2 text-sm">
            <input type="checkbox" className="accent-accent" checked={lossOk} onChange={(event) => setLossOk(event.target.checked)} />
            {t('cards.shop.install.droppedCheck')}
          </label>
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
