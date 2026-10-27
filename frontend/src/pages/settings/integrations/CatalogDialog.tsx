/**
 * "Add an integration": the catalog in a window of its own.
 *
 * Two hundred services stood as a wall of buttons under the own list, and
 * the page was mostly catalog for somebody who had set everything up long
 * ago. Now the search has the focus as the window opens, Enter takes the
 * first hit, the categories stand on the left (chips on a phone), and the
 * generic JSON connection waits at the bottom for whatever is not there.
 *
 * Loaded only when opened: nobody needs it to read the page.
 */
import { Search as SearchIcon, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'

import type { AdapterSpec, Integration } from '../../../api/types'
import { ServiceIcon } from '../../../components/ServiceIcon'
import { Toggle } from '../../../components/ui'
import { CATEGORY_ORDER } from '../../../components/WidgetLibrary'
import { tAdapter } from '../../../i18n/texts'
import { useFocusTrap } from '../../../lib/useFocusTrap'
import { FoundInNetwork } from './FoundInNetwork'
import { entries, firstSentence, markIn, search, sections, within, type CatalogEntry } from './catalog'

/** The connection for whatever has no adapter of its own. */
export const GENERIC = 'jsonapi'

export interface CatalogDialogProps {
  adapters: AdapterSpec[]
  integrations: Integration[]
  /** What the search starts with: the words somebody typed in the own list. */
  initialQuery?: string
  onClose: () => void
  /** A service was chosen: the sheet to set up a connection of this kind. */
  onPick: (kind: string) => void
  /** "Connect" on a service found in the network: the sheet with kind and address filled in. Without it, nothing found is shown. */
  onConnect?: (kind: string, address: string) => void
}

function Name({ label, query }: { label: string; query: string }) {
  const at = markIn(label, query)
  if (!at) return <>{label}</>
  return (
    <>
      {label.slice(0, at[0])}
      <mark className="bg-accent/30 text-inherit rounded-[3px] px-px">{label.slice(at[0], at[1])}</mark>
      {label.slice(at[1])}
    </>
  )
}

function Tile({ entry, query, first, onPick }: { entry: CatalogEntry; query: string; first: boolean; onPick: (kind: string) => void }) {
  const { t } = useTranslation()
  const { adapter, connected } = entry
  return (
    <button
      type="button"
      onClick={() => onPick(adapter.kind)}
      data-first={first || undefined}
      className={`flex items-start gap-[11px] min-w-0 px-3 py-[11px] rounded-xl border text-left bg-ink/[0.03] transition-colors hover:border-accent/45 hover:bg-surface-hover active:scale-[0.99] ${first ? 'border-accent/55' : 'border-line'}`}
    >
      <ServiceIcon icon={adapter.icon} size={32} />
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-1.5 text-[13.5px] font-semibold leading-tight">
          <Name label={adapter.label} query={query} />
          {adapter.beta && <span className="chip !py-0 text-[10px] font-normal">beta</span>}
          {connected > 0 && (
            <span className="chip !py-0 text-[10px] font-normal bg-ok/15 text-ok">
              {connected > 1 ? t('settings.integrations.catalog.connectedMany', { count: connected }) : t('settings.integrations.catalog.connected')}
            </span>
          )}
        </span>
        {adapter.description && <span className="mt-[3px] text-xs text-muted leading-snug line-clamp-2">{firstSentence(tAdapter(adapter.description))}</span>}
      </span>
    </button>
  )
}

function Head({ children, count }: { children: ReactNode; count: number }) {
  return (
    <h3 className="sticky -top-4 max-md:-top-3.5 z-[2] -mx-5 max-md:-mx-3.5 mb-2 px-5 max-md:px-3.5 pt-2.5 pb-1.5 flex items-baseline gap-2 text-[11px] uppercase tracking-[0.06em] font-semibold text-faint bg-[linear-gradient(var(--nd-surface-strong)_75%,transparent)]">
      {children}
      <span className="num tracking-normal">{count}</span>
    </h3>
  )
}

const GRID = 'grid grid-cols-[repeat(auto-fill,minmax(232px,1fr))] max-md:grid-cols-1 gap-2 max-md:gap-1.5 mb-[18px]'

export default function CatalogDialog({ adapters, integrations, initialQuery = '', onClose, onPick, onConnect }: CatalogDialogProps) {
  const { t } = useTranslation()
  const [query, setQuery] = useState(initialQuery)
  const [section, setSection] = useState('all')
  const [hideBeta, setHideBeta] = useState(false)
  const panel = useRef<HTMLDivElement>(null)
  const field = useRef<HTMLInputElement>(null)
  const main = useRef<HTMLDivElement>(null)
  const nav = useRef<HTMLElement>(null)
  const categoryName = (category: string) => t(`library.category.${category}`, { defaultValue: category })

  const all = useMemo(() => entries(adapters, integrations, CATEGORY_ORDER, (category) => t(`library.category.${category}`, { defaultValue: category })), [adapters, integrations, t])
  const hits = useMemo(() => search(all, query, hideBeta), [all, query, hideBeta])
  const shown = within(hits, section)
  const sectionName = (id: string) => (id === 'all' ? t('settings.integrations.catalog.all') : id === 'connected' ? t('settings.integrations.catalog.connectedNav') : categoryName(id))

  useEffect(() => {
    // A dialog may sit on top of this one later (the sheet); Escape closes the top one only.
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.stopPropagation()
      onClose()
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [onClose])
  useFocusTrap(true, panel)
  // After the trap, which puts the focus on the first button: the search is where typing starts.
  useEffect(() => {
    field.current?.focus({ preventScroll: true })
  }, [])

  const choose = (id: string) => {
    setSection(id)
    if (main.current) main.current.scrollTop = 0
    // On a phone the chosen chip slides into view, without the page behind moving along.
    const row = nav.current
    const chip = row?.querySelector<HTMLElement>(`[data-section="${id}"]`)
    if (row && chip && row.scrollWidth > row.clientWidth) {
      const left = chip.offsetLeft - row.offsetLeft
      if (left < row.scrollLeft + 14) row.scrollLeft = left - 14
      else if (left + chip.offsetWidth > row.scrollLeft + row.clientWidth - 14) row.scrollLeft = left + chip.offsetWidth - row.clientWidth + 14
    }
  }

  const typed = query.trim()
  let body: ReactNode
  if (!shown.length) {
    body = (
      <div className="py-10 px-2.5 text-center text-muted">
        {typed ? (section !== 'all' && hits.length ? t('settings.integrations.catalog.nothingIn', { query: typed, name: sectionName(section) }) : t('settings.integrations.catalog.nothing', { query: typed })) : t('settings.integrations.catalog.empty')}
        <div className="mt-3 flex flex-wrap justify-center gap-2">
          {section !== 'all' && hits.length > 0 && (
            <button type="button" className="btn btn-xs" onClick={() => choose('all')}>
              {t('settings.integrations.catalog.allHits', { count: hits.length })}
            </button>
          )}
          <button type="button" className="btn btn-xs" onClick={() => onPick(GENERIC)}>
            {t('settings.integrations.catalog.genericButton')}
          </button>
        </div>
      </div>
    )
  } else if (section === 'all' && !typed) {
    const groups = [...new Set(shown.map((entry) => entry.adapter.category))]
    body = groups.map((category) => {
      const list = shown.filter((entry) => entry.adapter.category === category)
      return (
        <section key={category} aria-label={categoryName(category)}>
          <Head count={list.length}>{categoryName(category)}</Head>
          <div className={GRID}>
            {list.map((entry) => (
              <Tile key={entry.adapter.kind} entry={entry} query="" first={false} onPick={onPick} />
            ))}
          </div>
        </section>
      )
    })
  } else {
    body = (
      <>
        {typed ? (
          <p className="text-[12.5px] text-muted mb-3.5">
            {t('settings.integrations.catalog.hits', { count: shown.length })}
            {section !== 'all' && ` ${t('settings.integrations.catalog.inSection', { name: sectionName(section) })}`}
            {'. '}
            {t('settings.integrations.catalog.hint')}
          </p>
        ) : (
          <Head count={shown.length}>{sectionName(section)}</Head>
        )}
        <div className={GRID}>
          {shown.map((entry, index) => (
            <Tile key={entry.adapter.kind} entry={entry} query={typed} first={index === 0 && Boolean(typed)} onPick={onPick} />
          ))}
        </div>
      </>
    )
  }

  // Rendered at the body, like every dialog: a glass surface with a backdrop filter would otherwise confine it.
  return createPortal(
    <div className="overlay fixed inset-0 z-50 flex items-center justify-center p-6 max-md:p-0 max-md:pt-2.5 max-md:items-stretch" role="dialog" aria-modal="true" aria-labelledby="catalog-title">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-[5px]" onMouseDown={onClose} aria-hidden="true" />
      <div
        ref={panel}
        className="relative glass-strong w-[min(1120px,100%)] h-[min(820px,100%)] max-md:h-full flex flex-col rounded-[20px] max-md:rounded-b-none overflow-hidden border border-line-strong shadow-2xl rise"
      >
        <header className="px-5 pt-[18px] pb-3.5 max-md:px-3.5 max-md:pt-3.5 max-md:pb-2.5 border-b border-line">
          <div className="flex items-start gap-3 mb-3.5 max-md:mb-2.5">
            <div className="flex-1 min-w-0">
              <h2 id="catalog-title" className="text-[17px] font-semibold tracking-tight">
                {t('settings.integrations.add')}
              </h2>
              <p className="text-[13px] text-muted mt-0.5 max-md:hidden">{t('settings.integrations.catalog.intro', { count: all.length })}</p>
            </div>
            <button type="button" className="btn btn-icon btn-flat" onClick={onClose} aria-label={t('common.close')}>
              <X size={16} />
            </button>
          </div>
          <div className="flex items-center gap-4 max-md:flex-wrap max-md:gap-2">
            <label className="relative flex-1 max-md:basis-full">
              <SearchIcon size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint pointer-events-none" />
              <input
                ref={field}
                className="input input-icon !h-[42px] !text-[15px] !rounded-xl pr-9"
                value={query}
                placeholder={t('settings.integrations.catalog.search')}
                aria-label={t('settings.integrations.catalog.searchLabel')}
                autoComplete="off"
                onChange={(event) => {
                  setQuery(event.target.value)
                  if (main.current) main.current.scrollTop = 0
                }}
                onKeyDown={(event) => {
                  // The first hit is the one that is marked; with nothing typed there is none to mean.
                  if (event.key === 'Enter' && typed && shown[0]) {
                    event.preventDefault()
                    onPick(shown[0].adapter.kind)
                  }
                }}
              />
              {query && (
                <button
                  type="button"
                  className="absolute right-2 top-1/2 -translate-y-1/2 h-6 w-6 grid place-items-center rounded-md text-faint hover:text-ink"
                  onClick={() => {
                    setQuery('')
                    field.current?.focus()
                  }}
                  aria-label={t('settings.integrations.list.clear')}
                >
                  <X size={14} />
                </button>
              )}
            </label>
            <span className="inline-flex items-center gap-2 text-[13px] text-muted whitespace-nowrap">
              <Toggle checked={hideBeta} onChange={setHideBeta} labelledBy="catalog-beta" />
              <span id="catalog-beta">{t('settings.integrations.catalog.hideBeta')}</span>
            </span>
          </div>
        </header>
        <div className="flex-1 min-h-0 grid md:grid-cols-[224px_minmax(0,1fr)] max-md:grid-rows-[auto_minmax(0,1fr)]">
          <nav
            ref={nav}
            aria-label={t('settings.integrations.catalog.sections')}
            className="flex flex-col gap-px overflow-y-auto scroll px-2.5 pt-3 pb-4 border-r border-line max-md:flex-row max-md:gap-1.5 max-md:overflow-x-auto max-md:overflow-y-hidden max-md:px-3.5 max-md:py-2.5 max-md:border-r-0 max-md:border-b scrollbar-none"
          >
            {sections(all, hits).map((one, index) => (
              <span key={one.id} className="contents">
                {index === 2 && <span className="h-px bg-line mx-1.5 my-2 flex-none max-md:hidden" />}
                <button
                  type="button"
                  data-section={one.id}
                  aria-pressed={section === one.id}
                  onClick={() => choose(one.id)}
                  className={`flex items-center gap-2 w-full min-h-[34px] px-2.5 py-1.5 rounded-[9px] text-left text-[13.5px] text-muted hover:bg-surface-hover hover:text-ink aria-pressed:bg-accent-soft aria-pressed:text-accent aria-pressed:font-semibold max-md:flex-none max-md:w-auto max-md:min-h-8 max-md:px-3 max-md:rounded-full max-md:border max-md:border-line max-md:text-[13px] max-md:whitespace-nowrap max-md:aria-pressed:border-accent/45 ${
                    one.count ? '' : 'opacity-45'
                  }`}
                >
                  {sectionName(one.id)}
                  <span className="num ml-auto max-md:ml-0.5 text-[11.5px] font-normal text-faint">{one.count}</span>
                </button>
              </span>
            ))}
          </nav>
          <div ref={main} className="overflow-y-auto scroll px-5 pt-4 pb-7 max-md:px-3.5 max-md:pt-3.5 max-md:pb-6">
            {/* What runs here already and is not connected: above everything, while all categories are shown. */}
            {section === 'all' && onConnect && <FoundInNetwork query={typed} onConnect={onConnect} />}
            {body}
          </div>
        </div>
        <footer className="border-t border-line px-5 py-2.5 max-md:px-3.5 flex items-center gap-3 text-[12.5px] text-muted">
          <span className="max-md:hidden">{t('settings.integrations.catalog.generic')}</span>
          <button type="button" className="btn btn-xs ml-auto max-md:ml-0 max-md:w-full max-md:h-8" onClick={() => onPick(GENERIC)}>
            {t('settings.integrations.catalog.genericButton')}
          </button>
        </footer>
      </div>
    </div>,
    document.body,
  )
}
