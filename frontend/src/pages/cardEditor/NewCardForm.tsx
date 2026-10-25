import { useQuery } from '@tanstack/react-query'
import { ClipboardPaste, Plus } from 'lucide-react'
import { useId, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { get } from '../../api/client'
import type { Integration } from '../../api/types'
import { ServiceIcon } from '../../components/ServiceIcon'
import type { CardSource } from '../../lib/customCards'
import type { CardDraft } from './draft'
import { slugFrom, START_ORDER, startText, STARTS, type StartKind } from './templates'

/** The rule of a short name, as the server checks it. */
const SLUG = /^[a-z0-9][a-z0-9-]{0,59}$/

type Source = CardSource & { category?: string }

/**
 * A new card (KARTEN-9 AC-2): its name, its short name (made from the name until it is typed), the kind of connection
 * it reads through, and what it starts from. Without a connection of a fitting kind it says so and leads to adding
 * one (EC-6). A whole card can be pasted instead (KARTEN-10 AC-6).
 */
export function NewCardForm({
  offer,
  onRestore,
  onDiscard,
  onCreate,
  onPaste,
}: {
  offer: CardDraft | null
  onRestore: () => void
  onDiscard: () => void
  onCreate: (text: string) => void
  onPaste: () => void
}) {
  const { t, i18n } = useTranslation()
  const ids = useId()
  const sources = useQuery({ queryKey: ['cards-sources'], queryFn: () => get<Source[]>('/cards/sources'), staleTime: 60_000 })
  const integrations = useQuery({ queryKey: ['integrations'], queryFn: () => get<Integration[]>('/integrations') })
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [slugTyped, setSlugTyped] = useState(false)
  const [chosen, setChosen] = useState('')
  const [start, setStart] = useState<StartKind>('blank')
  const [tried, setTried] = useState(false)

  const kinds = useMemo(() => sources.data ?? [], [sources.data])
  const connected = useMemo(() => new Set((integrations.data ?? []).map((one) => one.kind)), [integrations.data])
  // The first kind there is a connection for, so that the preview can show real data from the start.
  const source = chosen || kinds.find((one) => connected.has(one.kind))?.kind || kinds[0]?.kind || ''
  const label = kinds.find((one) => one.kind === source)?.label ?? source
  const anyConnected = kinds.some((one) => connected.has(one.kind))
  const shortName = slugTyped ? slug : slugFrom(name)
  const nameMissing = !name.trim()
  const slugWrong = !SLUG.test(shortName)

  const create = () => {
    setTried(true)
    if (nameMissing || slugWrong || !source) return
    onCreate(startText(start, { name: name.trim(), slug: shortName, source }))
  }

  const serviceName = (kind: string | null) => (kind ? (kinds.find((one) => one.kind === kind)?.label ?? kind) : '')

  return (
    <div className="max-w-3xl mx-auto px-3 sm:px-4 py-5 grid gap-4 min-w-0">
      {offer && (
        <div className="rounded-xl border border-accent/40 px-3 py-2 flex flex-wrap items-center gap-2" role="status">
          <div className="min-w-0 flex-1 basis-60">
            <div className="text-sm font-medium break-words hyphens-auto">{t('editor.restore.title')}</div>
            <div className="text-[13px] text-muted break-words hyphens-auto">
              {t('editor.restore.body', { time: new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(offer.at)) })}
            </div>
          </div>
          <button type="button" className="btn btn-accent" onClick={onRestore}>
            {t('editor.restore.restore')}
          </button>
          <button type="button" className="btn btn-flat" onClick={onDiscard}>
            {t('editor.restore.discard')}
          </button>
        </div>
      )}

      <section className="glass rounded-2xl p-4 sm:p-5 grid gap-4 min-w-0" aria-labelledby={`${ids}-title`}>
        <h1 id={`${ids}-title`} className="font-semibold text-[15px] break-words hyphens-auto">
          {t('editor.new.title')}
        </h1>

        <div className="grid gap-4 sm:grid-cols-2 min-w-0">
          <div className="grid gap-1 min-w-0 content-start">
            <label className="text-[12px] font-medium text-muted break-words hyphens-auto" htmlFor={`${ids}-name`}>
              {t('editor.new.name')}
            </label>
            <input id={`${ids}-name`} className="input" value={name} maxLength={60} onChange={(event) => setName(event.target.value)} aria-invalid={tried && nameMissing ? true : undefined} />
            {tried && nameMissing && (
              <span className="text-[12px] text-bad" role="alert">
                {t('editor.new.nameRequired')}
              </span>
            )}
          </div>
          <div className="grid gap-1 min-w-0 content-start">
            <label className="text-[12px] font-medium text-muted break-words hyphens-auto" htmlFor={`${ids}-slug`}>
              {t('editor.new.slug')}
            </label>
            <input
              id={`${ids}-slug`}
              className="input font-mono"
              value={shortName}
              maxLength={60}
              spellCheck={false}
              onChange={(event) => {
                setSlugTyped(true)
                setSlug(event.target.value)
              }}
              aria-invalid={tried && slugWrong ? true : undefined}
            />
            <span className={`text-[12px] break-words hyphens-auto ${tried && slugWrong ? 'text-bad' : 'text-faint'}`}>{tried && slugWrong ? t('editor.new.slugInvalid') : t('editor.new.slugHelp')}</span>
          </div>
        </div>

        <div className="grid gap-1 min-w-0">
          <label className="text-[12px] font-medium text-muted break-words hyphens-auto" htmlFor={`${ids}-source`}>
            {t('editor.new.source')}
          </label>
          <select id={`${ids}-source`} className="input" value={source} onChange={(event) => setChosen(event.target.value)} disabled={!kinds.length}>
            {kinds.map((one) => (
              <option key={one.kind} value={one.kind}>
                {one.label}
              </option>
            ))}
          </select>
          <span className="text-[12px] text-faint break-words hyphens-auto">{t('editor.new.sourceHelp')}</span>
        </div>

        {sources.isSuccess && integrations.isSuccess && source && !connected.has(source) && (
          <div className="rounded-xl border border-warn/40 px-3 py-2 flex flex-wrap items-center gap-2 text-sm" role="status" data-testid="card-no-connection">
            <span className="min-w-0 flex-1 basis-60 break-words hyphens-auto">{anyConnected ? t('editor.new.noConnection', { kind: label }) : t('editor.new.noConnectionAtAll')}</span>
            <Link className="btn" to={`/system/integrations?add=${encodeURIComponent(source)}`}>
              <Plus size={15} /> {t('editor.new.addIntegration')}
            </Link>
          </div>
        )}

        <fieldset className="grid gap-2 min-w-0">
          <legend className="text-[12px] font-medium text-muted mb-1 break-words hyphens-auto">{t('editor.new.start')}</legend>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 min-w-0">
            {START_ORDER.map((kind) => {
              const own = STARTS[kind].for
              return (
                <label key={kind} className={`flex items-start gap-2 rounded-xl border px-3 py-2 cursor-pointer min-w-0 ${start === kind ? 'border-accent/50 bg-accent-soft' : 'border-line hover:bg-surface-hover'}`}>
                  <input type="radio" name={`${ids}-start`} className="mt-1" checked={start === kind} onChange={() => setStart(kind)} />
                  <span className="min-w-0">
                    <span className="block text-sm font-medium break-words hyphens-auto">{t(`editor.new.starts.${kind}`)}</span>
                    <span className="flex items-center gap-1 text-[12px] text-muted break-words hyphens-auto">
                      {own && <ServiceIcon icon={kinds.find((one) => one.kind === own)?.icon ?? own} size={13} />}
                      {own ? t('editor.new.startFor', { service: serviceName(own) }) : t('editor.new.blankHelp')}
                    </span>
                  </span>
                </label>
              )
            })}
          </div>
        </fieldset>

        <div className="flex flex-wrap items-center justify-between gap-2">
          <button type="button" className="btn btn-flat" onClick={onPaste}>
            <ClipboardPaste size={15} /> {t('editor.new.paste')}
          </button>
          <button type="button" className="btn btn-accent" onClick={create} disabled={!source}>
            {t('editor.new.create')}
          </button>
        </div>
      </section>
    </div>
  )
}
