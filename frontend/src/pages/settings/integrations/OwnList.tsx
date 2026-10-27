/**
 * The connections already made: a summary that filters, a search, and the list.
 *
 * What needs a look stands first: failing connections, then those with a
 * newer release. The full error stands under its row; it used to be cut off
 * at the end of the line, and the end is where it says what to do.
 */
import { Bell, BellOff, ChevronDown, Lock, Pencil, Search as SearchIcon, Trash2, X } from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import type { AdapterSpec, Integration } from '../../../api/types'
import { CATEGORY_ORDER } from '../../../components/WidgetLibrary'
import { ServiceIcon } from '../../../components/ServiceIcon'
import { timeAgo } from '../../../lib/format'
import { FILTERS, grouped, rowsOf, storedView, storeView, visible, type OwnFilter, type OwnRow, type VersionReading } from './own'

/** The version a connection runs and how it stands against its project's newest release. */
function VersionColumn({ reading, loading }: { reading?: VersionReading; loading: boolean }) {
  const { t } = useTranslation()
  if (!reading) {
    // Only while the server is looking: a connection it does not read, or a look that failed, says nothing.
    return <span className="w-32 text-[11px] text-faint max-md:hidden">{loading ? t('settings.integrations.version.checking') : ''}</span>
  }
  return (
    <span className="w-32 min-w-0 grid text-[11px] leading-tight max-md:hidden" data-version={reading.state}>
      <span className="num truncate text-muted" title={reading.problem || undefined}>
        {reading.running ? (
          t('settings.integrations.version.runs', { version: reading.running })
        ) : (
          <span className="text-faint">{t(reading.unread ? 'settings.integrations.version.unread' : 'settings.integrations.version.notSaid')}</span>
        )}
      </span>
      {reading.state === 'behind' && (
        <a className="num text-warn font-medium truncate hover:underline" href={reading.url} target="_blank" rel="noreferrer noopener">
          {t(reading.major ? 'settings.integrations.version.newerMajor' : 'settings.integrations.version.newer', { version: reading.newest })}
        </a>
      )}
      {reading.state === 'current' && <span className="text-ok">{t('settings.integrations.version.current')}</span>}
      {reading.state === 'unknown' && reading.running && (
        <span className="text-faint truncate" title={reading.upstream ? t(reading.asked ? 'settings.integrations.version.noReleaseHelp' : 'settings.integrations.version.notAskedHelp') : undefined}>
          {!reading.upstream ? t('settings.integrations.version.noProject') : reading.asked ? t('settings.integrations.version.noRelease') : t('settings.integrations.version.notAsked')}
        </span>
      )}
    </span>
  )
}

interface RowActions {
  admin: boolean
  versionsLoading: boolean
  onBell: (integration: Integration) => void
  onEdit: (integration: Integration) => void
  onRemove: (integration: Integration) => void
  onBuildCard: (integration: Integration) => void
}

function Row({ row, admin, versionsLoading, onBell, onEdit, onRemove, onBuildCard }: { row: OwnRow } & RowActions) {
  const { t } = useTranslation()
  const { integration, failing, behind, reading, missing } = row
  const status = !integration.enabled ? 'unknown' : failing ? 'bad' : integration.last_ok_at || integration.demo ? 'ok' : 'unknown'
  const lastOk = integration.last_ok_at ? timeAgo(Date.parse(integration.last_ok_at) / 1000) : ''
  const meta: ReactNode[] = [
    <span key="label">{integration.label}</span>,
    integration.widget_count ? (
      <span key="cards">{t('settings.integrations.list.cards', { count: integration.widget_count })}</span>
    ) : (
      <span key="cards" className="text-faint">
        {t('settings.integrations.list.noCard')}
      </span>
    ),
  ]
  // ⚠️ Only an administrator builds a card here: the link leads to the library of a board.
  if (!integration.widget_count && admin) {
    meta.push(
      <button key="build" type="button" className="text-accent hover:underline" onClick={() => onBuildCard(integration)}>
        {t('settings.integrations.list.buildCard')}
      </button>,
    )
  }
  if (!integration.enabled) meta.push(<span key="off" className="text-faint">{t('settings.integrations.list.off')}</span>)
  if (integration.muted) meta.push(<span key="muted" className="text-faint">{t('settings.integrations.list.muted')}</span>)
  if (failing && lastOk) meta.push(<span key="since" className="text-faint">{t('settings.integrations.list.lastOk', { ago: lastOk })}</span>)
  return (
    <li
      className={`relative grid grid-cols-[24px_minmax(0,1fr)_8rem_10px_auto] max-md:grid-cols-[22px_minmax(0,1fr)_10px_auto] items-center gap-3 max-md:gap-2.5 pl-3.5 pr-2 py-2 min-h-[52px] hover:bg-surface-hover ${
        failing ? "bg-bad/5 before:content-[''] before:absolute before:left-0 before:top-2.5 before:bottom-2.5 before:w-[3px] before:rounded-r before:bg-bad" : ''
      }`}
      data-failing={failing || undefined}
    >
      <ServiceIcon icon={integration.icon} fallback={`/api/v1/integrations/${integration.id}/favicon`} size={22} />
      <div className="min-w-0">
        <div className="flex items-center gap-1.5 min-w-0 text-[13.5px] font-medium">
          <span className={`truncate ${integration.enabled ? '' : 'text-muted'}`}>{integration.name}</span>
          {integration.demo && <span className="chip !py-0 text-[10px]">demo</span>}
          {integration.admin_only && (
            <span className="chip !py-0 text-[10px] items-center" title={t('settings.integrations.adminOnlyHelp')}>
              <Lock size={9} />
              {t('settings.integrations.adminOnlyChip')}
            </span>
          )}
          {integration.beta && <span className="chip !py-0 text-[10px]">beta</span>}
          {missing && (
            <span className="chip !py-0 text-[10px] !text-bad" title={t('settings.integrations.missingHelp')} data-testid="integration-missing">
              {t('settings.integrations.missing')}
            </span>
          )}
        </div>
        <div className="text-xs text-muted truncate mt-px max-md:flex max-md:flex-wrap max-md:overflow-visible">
          {meta.map((part, index) => (
            <span key={index} className="whitespace-nowrap">
              {index > 0 && <span className="text-faint mx-1.5">·</span>}
              {part}
            </span>
          ))}
        </div>
        {/* On a phone the version column has no room; a newer version gets a line of its own. */}
        {behind && reading && (
          <div className="num text-xs text-warn mt-px md:hidden">{t('settings.integrations.list.newerRuns', { newest: reading.newest, running: reading.running })}</div>
        )}
        {failing && <div className="text-xs text-bad mt-0.5 leading-snug break-words">{integration.last_error}</div>}
      </div>
      {admin && integration.enabled && !integration.demo ? <VersionColumn reading={reading} loading={versionsLoading} /> : <span className="max-md:hidden" />}
      <span className="dot" data-status={status} />
      {admin ? (
        <span className="flex gap-0.5">
          <button
            type="button"
            // Muted is the crossed bell in the colour of a warning, not a pressed button: the row says "muted" in words.
            className={`btn btn-icon btn-flat h-[30px] w-[30px] aria-pressed:bg-transparent aria-pressed:border-transparent ${integration.muted ? 'text-warn' : 'text-faint'}`}
            onClick={() => onBell(integration)}
            aria-pressed={integration.muted}
            aria-label={t(integration.muted ? 'settings.integrations.unmute' : 'settings.integrations.mute', { name: integration.name })}
            title={t(integration.muted ? 'settings.integrations.mutedHelp' : 'settings.integrations.notifyHelp')}
          >
            {integration.muted ? <BellOff size={15} /> : <Bell size={15} />}
          </button>
          <button
            type="button"
            className="btn btn-icon btn-flat h-[30px] w-[30px] text-faint"
            onClick={() => onEdit(integration)}
            aria-label={t('settings.integrations.list.editOne', { name: integration.name })}
            disabled={missing}
            title={missing ? t('settings.integrations.missingHelp') : t('common.edit')}
          >
            <Pencil size={15} />
          </button>
          <button
            type="button"
            className="btn btn-icon btn-flat h-[30px] w-[30px] text-faint hover:text-bad"
            onClick={() => onRemove(integration)}
            aria-label={t('settings.integrations.list.removeOne', { name: integration.name })}
            title={t('common.delete')}
          >
            <Trash2 size={15} />
          </button>
        </span>
      ) : (
        <span />
      )}
    </li>
  )
}

function Rows({ rows, ...actions }: { rows: OwnRow[] } & RowActions) {
  return (
    <ul className="divide-y divide-line">
      {rows.map((row) => (
        <Row key={row.integration.id} row={row} {...actions} />
      ))}
    </ul>
  )
}

export interface OwnListProps extends Omit<RowActions, 'versionsLoading'> {
  integrations: Integration[]
  adapters: AdapterSpec[]
  versions?: Record<string, VersionReading>
  versionsLoading: boolean
  /** "Search the catalog for this": an administrator's way on when nothing of their own matches. */
  onSearchCatalog?: (query: string) => void
}

export function OwnList({ integrations, adapters, versions, versionsLoading, onSearchCatalog, ...actions }: OwnListProps) {
  const { t } = useTranslation()
  const [filter, setFilter] = useState<OwnFilter>('all')
  const [query, setQuery] = useState('')
  const [view, setView] = useState(storedView)
  const [closed, setClosed] = useState<Set<string>>(() => new Set())
  const categoryName = (category: string) => t(`library.category.${category}`, { defaultValue: category })

  const rows = useMemo(() => rowsOf(integrations, adapters, versions), [integrations, adapters, versions])
  const shown = visible(rows, filter, query, categoryName)
  const cards = rows.reduce((sum, row) => sum + row.integration.widget_count, 0)
  const choose = (next: 'list' | 'category') => {
    setView(next)
    storeView(next)
  }
  const flip = (category: string) =>
    setClosed((before) => {
      const after = new Set(before)
      if (!after.delete(category)) after.add(category)
      return after
    })
  const rowActions = { ...actions, versionsLoading }

  if (!integrations.length) return <p className="text-sm text-muted">{t('settings.integrations.empty')}</p>

  return (
    <>
      <div className="flex flex-wrap gap-1.5 mb-3" role="group" aria-label={t('settings.integrations.list.filters')}>
        {FILTERS.map((one) => {
          const count = rows.filter(one.test).length
          if (!count && one.id !== 'all') return null
          const on = filter === one.id
          return (
            <button
              key={one.id}
              type="button"
              aria-pressed={on}
              onClick={() => setFilter(on ? 'all' : one.id)}
              className={`inline-flex items-center gap-1.5 h-[30px] px-3 rounded-full border text-[12.5px] whitespace-nowrap transition-colors ${
                on ? 'bg-accent-soft border-accent/45 text-ink' : 'border-line bg-ink/[0.04] text-muted hover:text-ink hover:border-line-strong'
              }`}
            >
              <b className={`num font-semibold ${one.tone === 'bad' ? 'text-bad' : one.tone === 'warn' ? 'text-warn' : 'text-ink'}`}>{count}</b>
              {t(`settings.integrations.list.filter.${one.id}`, { count })}
              {on && one.id !== 'all' && <X size={12} className="text-faint" aria-hidden="true" />}
            </button>
          )
        })}
      </div>
      <div className="flex items-center gap-2.5 mb-2.5 max-md:flex-wrap">
        <label className="relative flex-1 max-w-[340px] max-md:max-w-none max-md:basis-full">
          <SearchIcon size={15} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-faint pointer-events-none" />
          <input
            className="input input-icon pr-8"
            value={query}
            placeholder={t('settings.integrations.list.search')}
            aria-label={t('settings.integrations.list.search')}
            autoComplete="off"
            onChange={(event) => setQuery(event.target.value)}
          />
          {query && (
            <button type="button" className="absolute right-1.5 top-1/2 -translate-y-1/2 h-6 w-6 grid place-items-center rounded-md text-faint hover:text-ink" onClick={() => setQuery('')} aria-label={t('settings.integrations.list.clear')}>
              <X size={14} />
            </button>
          )}
        </label>
        <span className="ml-auto text-xs text-faint whitespace-nowrap max-md:hidden">{t('settings.integrations.list.order')}</span>
        <span className="inline-flex flex-none p-[3px] rounded-[10px] bg-ink/[0.07]" role="group" aria-label={t('settings.integrations.list.view')}>
          {(['list', 'category'] as const).map((one) => (
            <button
              key={one}
              type="button"
              aria-pressed={view === one}
              onClick={() => choose(one)}
              className="px-2.5 py-1 rounded-lg text-[12.5px] text-muted aria-pressed:bg-surface-strong aria-pressed:text-ink aria-pressed:shadow-sm"
            >
              {t(`settings.integrations.list.${one === 'list' ? 'asList' : 'byCategory'}`)}
            </button>
          ))}
        </span>
      </div>
      {!shown.length ? (
        <div className="rounded-[14px] border border-line px-4 py-7 text-center text-[13.5px] text-muted">
          {query.trim() ? (
            <>
              {t('settings.integrations.list.noMatch', { query: query.trim() })}
              {onSearchCatalog && (
                <div className="mt-2.5">
                  <button type="button" className="btn btn-xs" onClick={() => onSearchCatalog(query.trim())}>
                    {t('settings.integrations.list.searchCatalog', { query: query.trim() })}
                  </button>
                </div>
              )}
            </>
          ) : (
            t('settings.integrations.list.nothingHere')
          )}
        </div>
      ) : view === 'list' ? (
        <div className="rounded-[14px] border border-line overflow-hidden bg-bg/20">
          <Rows rows={shown} {...rowActions} />
        </div>
      ) : (
        grouped(shown, CATEGORY_ORDER).map((group) => {
          const open = !closed.has(group.category)
          return (
            <section key={group.category} className="rounded-[14px] border border-line overflow-hidden mb-2 bg-bg/20" aria-label={categoryName(group.category)}>
              <button type="button" className="w-full flex items-center gap-2 px-3.5 py-2.5 text-left text-[13.5px] font-semibold hover:bg-surface-hover" aria-expanded={open} onClick={() => flip(group.category)}>
                <ChevronDown size={15} className={`text-faint transition-transform ${open ? '' : '-rotate-90'}`} />
                {categoryName(group.category)}
                <span className="num text-xs font-normal text-faint">({group.rows.length})</span>
                <span className="ml-auto flex gap-1.5">
                  {group.failing > 0 && <span className="chip !py-0 text-[10.5px] bg-bad/15 text-bad">{t('settings.integrations.list.groupFailing', { count: group.failing })}</span>}
                  {group.updates > 0 && <span className="chip !py-0 text-[10.5px] bg-warn/15 text-warn">{t('settings.integrations.list.groupUpdates', { count: group.updates })}</span>}
                </span>
              </button>
              {open && (
                <div className="border-t border-line">
                  <Rows rows={group.rows} {...rowActions} />
                </div>
              )}
            </section>
          )
        })
      )}
      <p className="mt-2.5 text-xs text-faint">
        {shown.length === rows.length
          ? t('settings.integrations.list.footAll', { count: rows.length, cards: t('settings.integrations.list.cards', { count: cards }) })
          : t('settings.integrations.list.footSome', { shown: shown.length, count: rows.length, cards: t('settings.integrations.list.cards', { count: cards }) })}
      </p>
    </>
  )
}
