import { useQuery } from '@tanstack/react-query'
import { Activity, Calendar, Download, HardDrive, Hash, Image, Info, Library, List, Play, Server, Users, type LucideIcon } from 'lucide-react'
import { useId } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { get } from '../../../api/client'
import { Spinner } from '../../../components/ui'
import { deleteAt, setAt } from '../../../lib/cardDocument'
import { suggestionsFor, wordsKey, type CardSuggestion, type SuggestionIcon } from '../../../lib/cardSuggestions'
import type { CardSource } from '../../../lib/customCards'
import { useConnections } from '../connections'
import { FailureNote } from '../FailureNote'
import { useCardEditor, useCardField } from '../store'
import { AnswerTable } from './AnswerTable'
import { GuidedFrame, StepNav } from './GuidedWay'
import { useReplaceGuard } from './ReplaceGuard'
import { askFor, useAnswerTable, useGuidedAnswer } from './useGuided'

const ICONS: Record<SuggestionIcon, LucideIcon> = {
  list: List,
  number: Hash,
  pictures: Image,
  server: Server,
  play: Play,
  calendar: Calendar,
  storage: HardDrive,
  download: Download,
  health: Activity,
  info: Info,
  library: Library,
  people: Users,
}

/**
 * Step 2, Data (U4, U5): what nexdeck knows of the service, in words people use; one pick asks the service and shows
 * the answer as a table right below. "Own address" takes any path for those who know the service's API, and is open
 * from the start for a service nexdeck has no suggestions for.
 */
export function DataStep() {
  const { t } = useTranslation()
  const ids = useId()
  const { kind, requestId, path, suggestion, probe } = useGuidedAnswer()
  const { chosen, loaded } = useConnections()
  const guard = useReplaceGuard()
  const [ownPath, setOwnPath] = useCardField<string>(['requests', 0, 'path'])
  const sources = useQuery({ queryKey: ['cards-sources'], queryFn: () => get<CardSource[]>('/cards/sources'), staleTime: 60_000 })
  const table = useAnswerTable()
  const service = sources.data?.find((one) => one.kind === kind)?.label ?? kind ?? ''
  const offered = suggestionsFor(kind)
  const asked = path && path !== '/'
  const ownOpen = !offered.length || (Boolean(asked) && !suggestion)

  const pick = (one: CardSuggestion) => {
    if (suggestion?.id === one.id && path === one.path) return
    // A suggestion makes the card's display again: what the guided way cannot show is asked about first.
    guard.ask(() => {
      useCardEditor.getState().change((doc) => {
        setAt(doc, ['requests'], [{ id: one.id, path: one.path, every: one.every }])
        // Examples of another answer would not fit this one.
        deleteAt(doc, ['demo'])
      })
      askFor(one.id, one.path, chosen?.id ?? null)
    })
  }

  /** Ask the path in the field; a new path makes the display again, so the same question comes first. */
  const askOwn = () => {
    if (useCardEditor.getState().shapedPath === path) return askFor(requestId, path, chosen?.id ?? null)
    guard.ask(() => askFor(requestId, path, chosen?.id ?? null))
  }

  return (
    <GuidedFrame id="data" title={t('editor.guided.data.title')} lead={t(offered.length ? 'editor.guided.data.lead' : 'editor.guided.data.leadOwn', { service })}>
      {loaded && !chosen && (
        <div className="rounded-xl border border-warn/40 px-3 py-2 flex flex-wrap items-center gap-2 min-w-0" role="status" data-testid="card-no-connection">
          <p className="text-sm min-w-0 flex-1 basis-60 break-words hyphens-auto">{t('editor.guided.data.noConnection', { service })}</p>
          {kind && (
            <Link className="btn" to={`/system/integrations?add=${encodeURIComponent(kind)}`}>
              {t('editor.guided.service.add')}
            </Link>
          )}
        </div>
      )}

      {offered.length > 0 && (
        <div className="grid gap-2 min-w-0" role="group" aria-label={t('editor.guided.data.title')}>
          {offered.map((one) => {
            const Icon = ICONS[one.icon]
            const pressed = suggestion?.id === one.id
            return (
              <button
                key={one.id}
                type="button"
                aria-pressed={pressed}
                className={`grid grid-cols-[auto_minmax(0,1fr)_auto] gap-3 items-center text-left rounded-2xl border px-3.5 py-3 min-w-0 ${pressed ? 'border-accent ring-[3px] ring-accent/20' : 'border-line hover:border-line-strong hover:bg-surface-hover'}`}
                onClick={() => pick(one)}
              >
                <span className="w-9 h-9 rounded-xl grid place-items-center bg-accent-soft text-accent" aria-hidden="true">
                  <Icon size={18} />
                </span>
                <span className="min-w-0">
                  <span className="block font-semibold text-sm break-words hyphens-auto">{t(wordsKey(kind ?? '', one, 'title'))}</span>
                  <span className="block text-[12.5px] text-muted break-words hyphens-auto">{t(wordsKey(kind ?? '', one, 'text'))}</span>
                </span>
                <span className="text-[12px] text-faint">{pressed ? t('editor.guided.data.picked') : t('editor.guided.data.pick')}</span>
              </button>
            )
          })}
        </div>
      )}

      <details className="rounded-xl border border-dashed border-line-strong px-3.5 py-2.5 min-w-0" open={ownOpen || undefined}>
        <summary className="cursor-pointer text-sm text-muted font-medium break-words hyphens-auto">{t('editor.guided.data.own')}</summary>
        <div className="grid gap-1 mt-2.5 min-w-0">
          <label className="text-[12px] font-medium text-muted break-words hyphens-auto" htmlFor={`${ids}-path`}>
            {t('editor.guided.data.path')}
          </label>
          <span className="flex flex-wrap sm:flex-nowrap gap-2 items-center min-w-0">
            <input
              id={`${ids}-path`}
              className="input font-mono min-w-0 flex-1 basis-40"
              value={ownPath ?? ''}
              placeholder="/api/…"
              spellCheck={false}
              onChange={(event) => setOwnPath(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && asked) askOwn()
              }}
            />
            <button type="button" className="btn btn-accent flex-none" disabled={!asked || !chosen || probe?.status === 'loading'} onClick={askOwn}>
              {t('editor.guided.data.ask')}
            </button>
          </span>
          <span className="text-[12px] text-faint break-words hyphens-auto">{t('editor.guided.data.pathHint')}</span>
        </div>
      </details>

      {probe?.status === 'loading' && (
        <p className="flex items-center gap-2 text-sm text-muted" role="status">
          <Spinner /> {t('editor.guided.data.asking', { service })}
        </p>
      )}
      {probe?.status === 'failed' && probe.path === path && <FailureNote failure={probe} />}
      {table && <AnswerTable table={table} />}

      {guard.dialog}
      <StepNav />
    </GuidedFrame>
  )
}
