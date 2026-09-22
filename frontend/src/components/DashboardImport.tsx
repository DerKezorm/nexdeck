/**
 * A board from Homepage or Homarr, in two steps: the files go in and a plan
 * comes back; the plan is looked at, missing values are typed in, cards are
 * left out, and only then is anything made.
 *
 * The files can be pasted or picked; picked ones find their field by name,
 * and a JSON file means Homarr.
 */
import { useState, type ChangeEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'

import { ApiError, post } from '../api/client'
import { tAdapter } from '../i18n/texts'
import { useAuth } from '../stores/auth'
import { ServiceIcon } from './ServiceIcon'
import { Field, Select } from './ui'

type Source = 'homepage' | 'homarr'
type FileName = 'services' | 'bookmarks' | 'widgets' | 'config'

interface PlanConnection {
  key: string
  kind: string
  label: string
  icon: string
  name: string
  config: Record<string, string>
  missing: string[]
  fields: { name: string; label: string; secret: boolean; required: boolean }[]
  use: 'create' | number | null
  existing: { id: number; name: string }[]
}

interface PlanCard {
  key: string
  kind: string
  title: string
  icon: string
  connection: string | null
  include: boolean
}

export interface Plan {
  source: Source
  connections: PlanConnection[]
  pages: { name: string; cards: PlanCard[] }[]
  notes: string[]
}

const LEAVE_OUT = 'none'
const CREATE = 'create'

/** Which field a picked file belongs in, by its name. */
export function fieldFor(fileName: string): FileName | null {
  const lower = fileName.toLowerCase()
  if (lower.endsWith('.json')) return 'config'
  for (const name of ['services', 'bookmarks', 'widgets'] as const) if (lower.includes(name)) return name
  return null
}

export function DashboardImport() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const admin = useAuth((state) => state.user?.role === 'admin')
  const [source, setSource] = useState<Source>('homepage')
  const [files, setFiles] = useState<Record<FileName, string>>({ services: '', bookmarks: '', widgets: '', config: '' })
  const [plan, setPlan] = useState<Plan | null>(null)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const pick = async (event: ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(event.target.files ?? [])
    const read: Partial<Record<FileName, string>> = {}
    for (const file of picked) {
      const field = fieldFor(file.name)
      if (field) read[field] = await file.text()
    }
    setFiles((current) => ({ ...current, ...read }))
    if (read.config) setSource('homarr')
    else if (read.services || read.bookmarks || read.widgets) setSource('homepage')
    event.target.value = ''
  }

  const fail = (failure: unknown) => setError(failure instanceof ApiError ? failure.message : t('errors.network'))

  const look = () => {
    setBusy(true)
    setError('')
    const sent = source === 'homarr' ? { config: files.config } : { services: files.services, bookmarks: files.bookmarks, widgets: files.widgets }
    post<Plan>('/imports/preview', { source, files: sent })
      .then((answer) => {
        setPlan(answer)
        setName(t(`imports.defaultName.${answer.source}`))
      })
      .catch(fail)
      .finally(() => setBusy(false))
  }

  const setConnection = (key: string, change: Partial<PlanConnection>) =>
    setPlan((current) => (current ? { ...current, connections: current.connections.map((c) => (c.key === key ? { ...c, ...change } : c)) } : current))
  const toggle = (cardKey: string, include: boolean) =>
    setPlan((current) => (current ? { ...current, pages: current.pages.map((page) => ({ ...page, cards: page.cards.map((card) => (card.key === cardKey ? { ...card, include } : card)) })) } : current))

  const byKey = Object.fromEntries((plan?.connections ?? []).map((c) => [c.key, c]))
  const stillMissing = (c: PlanConnection) => (c.use === CREATE ? c.missing.filter((field) => !c.config[field]?.trim()) : [])
  const blocked = (plan?.connections ?? []).some((c) => stillMissing(c).length > 0)
  const arriving = (plan?.pages ?? []).flatMap((page) => page.cards).filter((card) => card.include && (!card.connection || byKey[card.connection]?.use !== null)).length

  const make = () => {
    if (!plan) return
    setBusy(true)
    setError('')
    post<{ slug: string }>('/imports/apply', { plan, name })
      .then((board) => navigate(`/b/${board.slug}`))
      .catch(fail)
      .finally(() => setBusy(false))
  }

  if (!plan) {
    return (
      <div>
        <div className="flex gap-1 mb-3" role="group" aria-label={t('imports.source')}>
          {(['homepage', 'homarr'] as const).map((entry) => (
            <button key={entry} type="button" className="btn h-8 text-xs" aria-pressed={source === entry} onClick={() => setSource(entry)}>
              {t(`imports.sources.${entry}`)}
            </button>
          ))}
          <label className="btn h-8 text-xs ml-auto cursor-pointer">
            {t('imports.pick')}
            <input type="file" multiple accept=".yaml,.yml,.json" className="sr-only" onChange={(event) => void pick(event)} />
          </label>
        </div>
        {source === 'homepage' ? (
          (['services', 'bookmarks', 'widgets'] as const).map((field) => (
            <Field key={field} label={`${field}.yaml`} htmlFor={`import-${field}`} help={field === 'services' ? t('imports.servicesHelp') : undefined}>
              <textarea id={`import-${field}`} className="input font-mono text-xs" rows={field === 'services' ? 6 : 3} value={files[field]} onChange={(event) => setFiles((current) => ({ ...current, [field]: event.target.value }))} />
            </Field>
          ))
        ) : (
          <Field label={t('imports.homarrConfig')} htmlFor="import-config" help={t('imports.homarrHelp')}>
            <textarea id="import-config" className="input font-mono text-xs" rows={8} value={files.config} onChange={(event) => setFiles((current) => ({ ...current, config: event.target.value }))} />
          </Field>
        )}
        {error && (
          <p className="text-sm text-bad mb-2" role="alert">
            {error}
          </p>
        )}
        <button className="btn btn-accent" disabled={busy || !(source === 'homarr' ? files.config : files.services || files.bookmarks || files.widgets).trim()} onClick={look}>
          {t('imports.look')}
        </button>
      </div>
    )
  }

  return (
    <div>
      <Field label={t('imports.name')} htmlFor="import-name">
        <input id="import-name" className="input" value={name} maxLength={80} onChange={(event) => setName(event.target.value)} />
      </Field>

      {plan.connections.length > 0 && (
        <>
          <p className="text-xs font-medium text-muted mb-2">{t('imports.connections')}</p>
          <ul className="space-y-2 mb-4">
            {plan.connections.map((connection) => {
              const value = connection.use === null ? LEAVE_OUT : String(connection.use)
              const missing = stillMissing(connection)
              return (
                <li key={connection.key} className="rounded-xl border border-line p-2.5">
                  <div className="flex items-center gap-2 flex-wrap">
                    <ServiceIcon icon={connection.icon} size={18} />
                    <label htmlFor={`use-${connection.key}`} className="text-sm font-medium">
                      {connection.name}
                    </label>
                    <span className="text-[11px] text-faint">{connection.label}</span>
                    {connection.config.url && <span className="text-[11px] text-faint num truncate max-w-[16rem]">{connection.config.url}</span>}
                    <Select
                      id={`use-${connection.key}`}
                      className="!w-auto ml-auto !h-8 text-xs"
                      value={value}
                      onChange={(next) => setConnection(connection.key, { use: next === LEAVE_OUT ? null : next === CREATE ? CREATE : Number(next) })}
                      options={[
                        ...(admin ? [{ value: CREATE, label: t('imports.create') }] : []),
                        ...connection.existing.map((row) => ({ value: String(row.id), label: t('imports.useExisting', { name: row.name }) })),
                        { value: LEAVE_OUT, label: t('imports.leaveOut') },
                      ]}
                    />
                  </div>
                  {connection.use === CREATE && connection.missing.length > 0 && (
                    <div className="grid gap-2 sm:grid-cols-2 mt-2">
                      {connection.missing.map((fieldName) => {
                        const field = connection.fields.find((one) => one.name === fieldName)
                        return (
                          <Field key={fieldName} label={tAdapter(field?.label ?? fieldName)} htmlFor={`${connection.key}-${fieldName}`}>
                            <input
                              id={`${connection.key}-${fieldName}`}
                              className="input"
                              type={field?.secret ? 'password' : 'text'}
                              autoComplete="off"
                              value={connection.config[fieldName] ?? ''}
                              onChange={(event) => setConnection(connection.key, { config: { ...connection.config, [fieldName]: event.target.value } })}
                            />
                          </Field>
                        )
                      })}
                    </div>
                  )}
                  {missing.length > 0 && <p className="text-[11px] text-warn mt-1">{t('imports.stillMissing')}</p>}
                </li>
              )
            })}
          </ul>
        </>
      )}

      <p className="text-xs font-medium text-muted mb-2">{t('imports.cards', { count: arriving })}</p>
      <div className="grid gap-3 sm:grid-cols-2 mb-4">
        {plan.pages.map((page) => (
          <fieldset key={page.name} className="rounded-xl border border-line p-2.5">
            <legend className="px-1 text-xs font-medium">{page.name}</legend>
            {page.cards.map((card) => {
              const gone = card.connection !== null && byKey[card.connection]?.use === null
              return (
                <label key={card.key} className={`flex items-center gap-2 text-sm py-0.5 ${gone ? 'opacity-50' : ''}`}>
                  <input type="checkbox" className="accent-accent" checked={card.include && !gone} disabled={gone} onChange={(event) => toggle(card.key, event.target.checked)} />
                  <ServiceIcon icon={card.icon} size={14} />
                  <span className="truncate">{card.title}</span>
                </label>
              )
            })}
          </fieldset>
        ))}
      </div>

      {plan.notes.length > 0 && (
        <div className="mb-4">
          <p className="text-xs font-medium text-muted mb-1">{t('imports.notes')}</p>
          <ul className="list-disc pl-5 text-xs text-muted space-y-0.5">
            {plan.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </div>
      )}
      {error && (
        <p className="text-sm text-bad mb-2" role="alert">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <button className="btn btn-accent" disabled={busy || blocked || arriving === 0} onClick={make}>
          {t('imports.make')}
        </button>
        <button className="btn" onClick={() => setPlan(null)}>
          {t('common.back')}
        </button>
      </div>
    </div>
  )
}
