/**
 * "Start from an example" in the editors (KARTEN-19 AC-4, EC-1): the entries of the Card shop that the Workshop marks as
 * examples, of the kind being made (a card or an own connection). A choice opens the checked definition as a new draft in
 * the editor; nothing is installed and nothing is saved before the administrator saves. With the shop off the list is not
 * asked for: the dialog says that examples come from the shop and offers to turn it on.
 */
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, get, serverUrl } from '../../api/client'
import { Dialog, Spinner } from '../../components/ui'
import { changeCard, parseCard, setAt } from '../../lib/cardDocument'
import { pickText } from '../../lib/cardText'
import { pictureSrc, SHOP_CATALOG_KEY, type ShopEntry, type ShopType } from '../../lib/cardShop'
import { useGround } from '../../lib/ground'
import { useShopCatalog, useShopState, useShopSwitch } from '../settings/shop/hooks'

/** What the server hands out for an example: its checked text and a short name nobody here has yet. */
export interface Example {
  id: string
  type: ShopType
  slug: string
  text: string
}

/** The text with its short name (`slug` of a card, `short` of an own connection) set; the text as it is if it cannot be read. */
export function withShortName(text: string, key: 'slug' | 'short', value: string): string {
  const parsed = parseCard(text)
  return parsed.ok ? changeCard(parsed.card, (doc) => setAt(doc, [key], value)).text : text
}

function Off() {
  const { t } = useTranslation()
  const shop = useShopSwitch()
  const [explaining, setExplaining] = useState(false)
  return (
    <div className="grid gap-3 justify-items-start" data-testid="example-shop-off">
      <p className="text-sm">{t('editor.examples.offLead')}</p>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className="btn btn-accent" disabled={shop.busy} onClick={() => void shop.set(true)}>
          {t('editor.examples.turnOn')}
        </button>
        <button type="button" className="btn btn-flat" aria-expanded={explaining} onClick={() => setExplaining(!explaining)}>
          {t('cards.shop.whatItSends')}
        </button>
      </div>
      {explaining && (
        <p className="text-sm text-muted" role="note" data-testid="example-shop-sends">
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

function Row({ entry, kind, busy, onChoose }: { entry: ShopEntry; kind: ShopType; busy: boolean; onChoose: (entry: ShopEntry) => void }) {
  const { t, i18n } = useTranslation()
  const ground = useGround((state) => state.mode)
  const name = pickText(entry.name, i18n.language) || entry.slug
  return (
    <li className="rounded-xl border border-line p-3 flex flex-col sm:flex-row gap-3 min-w-0" data-testid={`example-${entry.id}`}>
      <div className="sm:w-40 sm:flex-none aspect-[4/3] rounded-lg overflow-hidden bg-[color-mix(in_srgb,var(--nd-text)_6%,transparent)] flex items-center justify-center">
        <img
          src={serverUrl(pictureSrc(entry, ground))}
          alt=""
          loading="lazy"
          decoding="async"
          className="w-full h-full object-contain"
          onError={(event) => {
            event.currentTarget.style.visibility = 'hidden'
          }}
        />
      </div>
      <div className="min-w-0 flex-1 grid gap-1 content-start">
        <div className="text-sm font-medium break-words hyphens-auto">{name}</div>
        <p className="text-[13px] text-muted break-words hyphens-auto">{entry.description}</p>
        {kind === 'card' && !entry.fits && (
          <p className="text-[12px] text-warn break-words hyphens-auto" data-testid="example-no-connection">
            {t('editor.examples.noConnection')}
          </p>
        )}
      </div>
      <div className="sm:self-center">
        <button type="button" className="btn btn-accent" disabled={busy} onClick={() => onChoose(entry)}>
          {t('editor.examples.use')}
        </button>
      </div>
    </li>
  )
}

function List({ kind, onPick }: { kind: ShopType; onPick: (example: Example) => void }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const catalog = useShopCatalog(true)
  const [busy, setBusy] = useState(false)
  const [trouble, setTrouble] = useState('')
  if (catalog.isPending) {
    return (
      <p className="text-sm text-muted" role="status">
        {t('cards.shop.loading')}
      </p>
    )
  }
  if (catalog.isError || !catalog.data) {
    return (
      <div className="grid gap-2 justify-items-start" role="alert" data-testid="example-failed">
        <p className="text-sm text-bad">{t('editor.examples.failed')}</p>
        <button type="button" className="btn" onClick={() => void queryClient.invalidateQueries({ queryKey: SHOP_CATALOG_KEY })}>
          {t('cards.shop.tryAgain')}
        </button>
      </div>
    )
  }
  const examples = catalog.data.entries.filter((one) => one.starter === true && one.type === kind && !one.removed && !one.needs_newer)
  if (!examples.length) {
    return (
      <p className="text-sm text-muted" data-testid="example-none">
        {t(`editor.examples.none.${kind}`)}
      </p>
    )
  }
  const choose = async (entry: ShopEntry) => {
    setBusy(true)
    setTrouble('')
    try {
      onPick(await get<Example>(`/workshop/examples/${encodeURIComponent(entry.author_id)}/${encodeURIComponent(entry.slug)}`))
    } catch (failure) {
      setTrouble(failure instanceof ApiError ? failure.message : t('errors.network'))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="grid gap-3">
      {trouble && (
        <p className="text-sm text-bad rounded-lg border border-bad/40 px-3 py-2" role="alert" data-testid="example-trouble">
          {t('editor.examples.pickFailed', { why: trouble })}
        </p>
      )}
      <ul className="grid gap-2">
        {examples.map((one) => (
          <Row key={one.id} entry={one} kind={kind} busy={busy} onChoose={(entry) => void choose(entry)} />
        ))}
      </ul>
    </div>
  )
}

function Body({ kind, onPick }: { kind: ShopType; onPick: (example: Example) => void }) {
  const { t } = useTranslation()
  const state = useShopState()
  if (state.isPending) return <Spinner />
  if (state.isError || !state.data) {
    return (
      <p className="text-sm text-bad" role="alert">
        {t('errors.network')}
      </p>
    )
  }
  return state.data.enabled ? <List kind={kind} onPick={onPick} /> : <Off />
}

/** The bar above a new, untouched card or connection: start empty as before, or open the list of examples. */
export function ExampleStart({ kind, onPick }: { kind: ShopType; onPick: (example: Example) => void }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  return (
    <>
      <div className="rounded-xl border border-line px-3 py-2 flex flex-wrap items-center gap-2" data-testid="example-start">
        <span className="min-w-0 flex-1 basis-60 text-sm text-muted break-words hyphens-auto">{t(`editor.examples.bar.${kind}`)}</span>
        <button type="button" className="btn" onClick={() => setOpen(true)}>
          {t('editor.examples.button')}
        </button>
      </div>
      <Dialog open={open} onClose={() => setOpen(false)} title={t('editor.examples.title')} size="lg">
        <p className="text-sm text-muted mb-3 break-words hyphens-auto">{t(`editor.examples.lead.${kind}`)}</p>
        <Body
          kind={kind}
          onPick={(example) => {
            setOpen(false)
            onPick(example)
          }}
        />
      </Dialog>
    </>
  )
}
