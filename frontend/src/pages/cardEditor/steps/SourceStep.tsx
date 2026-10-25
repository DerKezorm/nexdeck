import { useQuery } from '@tanstack/react-query'
import { Plus, Trash2, X } from 'lucide-react'
import { useId, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { get } from '../../../api/client'
import { Spinner } from '../../../components/ui'
import { deleteAt, readAt, readIn, setAt, type CardPath } from '../../../lib/cardDocument'
import { problemText, type CardSource } from '../../../lib/customCards'
import { runProbe, useConnections } from '../connections'
import { DataTree } from '../DataTree'
import { DemoDialog } from '../DemoDialog'
import { FailureNote } from '../FailureNote'
import { requestIds } from '../slots'
import { useCardEditor, useCardField, useFieldProblems } from '../store'
import { StepFrame } from './StepFrame'

const MAX_REQUESTS = 5
/** How often a request can be made, as the card writes it. Another value written in the YAML is offered as well. */
const EVERY = ['10s', '30s', '60s', '2m', '5m', '10m', '15m', '30m', '1h', '6h', '12h', '24h']

/** "30s" in words: 30 seconds, 5 minutes, 1 hour. */
export function everyText(t: (key: string, options?: Record<string, unknown>) => string, every: string): string {
  const match = /^(\d+)([smh])$/.exec(every)
  if (!match) return every
  return t(`editor.source.every_${match[2]}`, { count: Number(match[1]) })
}

/** A new request's id: request2, request3, … whatever is free. */
function freeId(ids: string[]): string {
  for (let number = ids.length + 1; ; number += 1) if (!ids.includes(`request${number}`)) return `request${number}`
}

/** What the server found wrong with one field, beside it. */
export function FieldProblems({ path }: { path: CardPath }) {
  const { t } = useTranslation()
  const problems = useFieldProblems(path)
  return (
    <>
      {problems.map((problem, index) => (
        <p key={index} className="text-[12px] text-bad break-words hyphens-auto" role="alert">
          {problemText(t, problem)}
        </p>
      ))}
    </>
  )
}

function Request({ index, count, integrationId }: { index: number; count: number; integrationId: number | null }) {
  const { t, i18n } = useTranslation()
  const ids = useId()
  const [id] = useCardField<string>(['requests', index, 'id'])
  const [path, setPath] = useCardField<string>(['requests', index, 'path'])
  const [every, setEvery] = useCardField<string>(['requests', index, 'every'])
  const editable = useCardEditor((state) => state.card !== null)
  const probe = useCardEditor((state) => (id ? state.probes[id] : undefined))
  const [demoOpen, setDemoOpen] = useState(false)
  const choices = every && !EVERY.includes(every) ? [every, ...EVERY] : EVERY

  const rename = (next: string) => {
    const editor = useCardEditor.getState()
    editor.change((doc) => {
      setAt(doc, ['requests', index, 'id'], next)
      // The examples of the request go along with its new name. Emptied on the way (all of it typed anew), the name
      // leaves them where they were; the next letter takes the examples no request has.
      if (!next || next === id) return
      const demo = readIn(doc, ['demo'])
      const names = (readIn(doc, ['requests']) as { id?: unknown }[] | undefined)?.map((one) => String(one?.id ?? '')) ?? []
      const keys = demo && typeof demo === 'object' ? Object.keys(demo) : []
      const orphans = keys.filter((key) => !names.includes(key))
      const from = id && keys.includes(id) ? id : !id && orphans.length === 1 ? orphans[0] : null
      if (from === null || keys.includes(next)) return
      setAt(doc, ['demo', next], (demo as Record<string, unknown>)[from])
      deleteAt(doc, ['demo', from])
    }, `field:requests.${index}.id`)
    if (id && probe && next !== id) {
      editor.setProbe(id, null)
      editor.setProbe(next, probe)
    }
  }

  const remove = () => {
    const editor = useCardEditor.getState()
    editor.change((doc) => {
      deleteAt(doc, ['requests', index])
      if (id) deleteAt(doc, ['demo', id])
    })
    if (id) editor.setProbe(id, null)
  }

  return (
    <div className="grid gap-3 min-w-0 rounded-xl border border-line p-3" role="group" aria-label={t('editor.source.request', { number: index + 1 })}>
      <div className="grid gap-3 sm:grid-cols-2 min-w-0">
        <div className="grid gap-1 min-w-0">
          <label className="text-[12px] font-medium text-muted break-words hyphens-auto" htmlFor={`${ids}-id`}>
            {t('editor.source.id')}
          </label>
          <input id={`${ids}-id`} className="input input-mono" value={id ?? ''} disabled={!editable} onChange={(event) => rename(event.target.value)} />
          <FieldProblems path={['requests', index, 'id']} />
        </div>
        <div className="grid gap-1 min-w-0">
          <label className="text-[12px] font-medium text-muted break-words hyphens-auto" htmlFor={`${ids}-every`}>
            {t('editor.source.every')}
          </label>
          <select id={`${ids}-every`} className="input" value={every ?? ''} disabled={!editable} onChange={(event) => setEvery(event.target.value || undefined)}>
            <option value="">{t('editor.source.everyDefault')}</option>
            {choices.map((one) => (
              <option key={one} value={one}>
                {everyText(t, one)}
              </option>
            ))}
          </select>
          <FieldProblems path={['requests', index, 'every']} />
        </div>
      </div>
      <div className="grid gap-1 min-w-0">
        <label className="text-[12px] font-medium text-muted break-words hyphens-auto" htmlFor={`${ids}-path`}>
          {t('editor.source.path')}
        </label>
        <span className="flex flex-wrap sm:flex-nowrap gap-2 items-center min-w-0">
          <span className="chip font-mono text-[11px] flex-none">GET</span>
          <input id={`${ids}-path`} className="input input-mono min-w-0 flex-1 basis-40" value={path ?? ''} disabled={!editable} onChange={(event) => setPath(event.target.value)} />
          <button
            type="button"
            className="btn btn-accent flex-none"
            disabled={!editable || !path || !id || integrationId === null || probe?.status === 'loading'}
            onClick={() => {
              if (integrationId !== null && id && path) void runProbe(id, integrationId, path)
            }}
          >
            {probe?.status === 'loading' ? <Spinner /> : null}
            {t('editor.source.probe')}
          </button>
        </span>
        <span className="text-[12px] text-faint break-words hyphens-auto">{t('editor.source.pathHelp', { count: MAX_REQUESTS })}</span>
        <FieldProblems path={['requests', index, 'path']} />
      </div>
      {count > 1 && (
        <button type="button" className="btn btn-flat btn-danger justify-self-start" onClick={remove} disabled={!editable}>
          <Trash2 size={14} />
          {t('editor.source.removeRequest')}
        </button>
      )}

      {probe?.status === 'failed' && <FailureNote failure={probe} />}
      {probe?.status === 'done' && id && (
        <section className="grid gap-2 min-w-0" aria-label={t('editor.source.answer')}>
          <div className="flex flex-wrap items-baseline justify-between gap-2 min-w-0">
            <h3 className="text-sm font-semibold break-words hyphens-auto">{t('editor.source.answer')}</h3>
            <span className="text-[12px] text-muted font-mono break-all">
              GET {probe.path} · {t('editor.source.nodes', { count: probe.answer.nodes, number: probe.answer.nodes.toLocaleString(i18n.language) })}
            </span>
          </div>
          {probe.answer.cut && <p className="text-[12px] text-muted break-words hyphens-auto">{t('editor.source.cut')}</p>}
          <DataTree key={`${probe.integrationId}:${probe.path}`} requestId={id} tree={probe.answer.tree} />
          <p className="text-[12px] text-faint break-words hyphens-auto">{t('editor.source.onlyYou')}</p>
          <button type="button" className="btn btn-flat justify-self-start" onClick={() => setDemoOpen(true)} disabled={!editable}>
            {t('editor.source.useAsDemo')}
          </button>
          {demoOpen && <DemoDialog open onClose={() => setDemoOpen(false)} integrationId={probe.integrationId} />}
        </section>
      )}
    </div>
  )
}

/**
 * Step 1, Source (KARTEN-9 AC-2 to AC-5, AC-10, EC-1, EC-2, EC-4, EC-6, EC-9): the kinds of connection the card works
 * with, the connection to probe with (never written into the card, decision 4), the requests with their paths and how
 * often they are made, the probe and its answer as a tree, and "Use this answer as demo data".
 */
export function SourceStep() {
  const { t } = useTranslation()
  const ids = useId()
  const card = useCardEditor((state) => state.card ?? state.lastValid?.card ?? null)
  const editable = useCardEditor((state) => state.card !== null)
  const change = useCardEditor((state) => state.change)
  const setIntegration = useCardEditor((state) => state.setIntegration)
  const sources = useQuery({ queryKey: ['cards-sources'], queryFn: () => get<CardSource[]>('/cards/sources'), staleTime: 60_000 })
  const { kinds, fitting, chosen, loaded } = useConnections()
  const [adding, setAdding] = useState('')

  if (!card) return <StepFrame step="source" />
  const requests = requestIds(card)
  const labelOf = (kind: string) => sources.data?.find((one) => one.kind === kind)?.label ?? kind
  const free = (sources.data ?? []).filter((one) => !kinds.includes(one.kind))
  const setKinds = (next: string[]) => change((doc) => setAt(doc, ['requires'], next))

  return (
    <StepFrame step="source">
      <div className="grid gap-1.5 min-w-0">
        <span className="text-[12px] font-medium text-muted break-words hyphens-auto" id={`${ids}-kinds`}>
          {t('editor.source.worksWith')}
        </span>
        <div className="flex flex-wrap items-center gap-1.5" role="group" aria-labelledby={`${ids}-kinds`}>
          {kinds.map((kind) => (
            <span key={kind} className="chip inline-flex items-center gap-1 break-words hyphens-auto">
              {labelOf(kind)}
              {kinds.length > 1 && (
                <button type="button" className="text-muted hover:text-ink" disabled={!editable} onClick={() => setKinds(kinds.filter((one) => one !== kind))} aria-label={t('editor.source.removeKind', { kind: labelOf(kind) })}>
                  <X size={12} />
                </button>
              )}
            </span>
          ))}
          {free.length > 0 && (
            <span className="inline-flex flex-wrap items-center gap-1.5">
              <select className="input !h-8 !py-0 !w-auto max-w-full text-sm" value={adding} onChange={(event) => setAdding(event.target.value)} aria-label={t('editor.source.addKind')} disabled={!editable}>
                <option value="">{t('editor.source.addKind')}</option>
                {free.map((one) => (
                  <option key={one.kind} value={one.kind}>
                    {one.label}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="btn btn-flat !h-8"
                disabled={!adding || !editable}
                onClick={() => {
                  setKinds([...kinds, adding])
                  setAdding('')
                }}
              >
                {t('editor.source.add')}
              </button>
            </span>
          )}
        </div>
        <FieldProblems path={['requires']} />
      </div>

      <div className="grid gap-1 min-w-0">
        <label className="text-[12px] font-medium text-muted break-words hyphens-auto" htmlFor={`${ids}-with`}>
          {t('editor.source.probeWith')}
        </label>
        <select id={`${ids}-with`} className="input" value={chosen?.id ?? ''} disabled={!fitting.length} aria-describedby={`${ids}-with-help`} onChange={(event) => setIntegration(Number(event.target.value))}>
          {!fitting.length && <option value="">{t('editor.source.noConnection')}</option>}
          {fitting.map((one) => (
            <option key={one.id} value={one.id}>
              {one.name}
            </option>
          ))}
        </select>
        <span id={`${ids}-with-help`} className="text-[12px] text-faint break-words hyphens-auto">
          {t('editor.source.probeWithHelp')}
        </span>
      </div>
      {loaded && !fitting.length && (
        <div className="rounded-xl border border-warn/40 px-3 py-2 flex flex-wrap items-center gap-2 min-w-0" role="status" data-testid="card-no-connection">
          <p className="text-sm min-w-0 flex-1 basis-60 break-words hyphens-auto">{t('editor.source.noConnectionBody', { kinds: kinds.map(labelOf).join(', ') })}</p>
          {kinds[0] && (
            <Link className="btn" to={`/system/integrations?add=${encodeURIComponent(kinds[0])}`}>
              {t('editor.source.addIntegration')}
            </Link>
          )}
        </div>
      )}

      {requests.map((_, index) => (
        <Request key={index} index={index} count={requests.length} integrationId={chosen?.id ?? null} />
      ))}
      {requests.length < MAX_REQUESTS && (
        <button
          type="button"
          className="btn btn-flat justify-self-start"
          disabled={!editable}
          onClick={() => {
            const list = readAt(card, ['requests'])
            const at = Array.isArray(list) ? list.length : 0
            change((doc) => setAt(doc, ['requests', at], { id: freeId(requests), path: '/' }))
          }}
        >
          <Plus size={14} />
          {t('editor.source.addRequest')}
        </button>
      )}
    </StepFrame>
  )
}
