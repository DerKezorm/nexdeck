import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Pencil, Plus, Search, Trash2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { ApiError, del, get, post, put } from '../../api/client'
import { ServiceIcon } from '../../components/ServiceIcon'
import { Confirm, EmptyState, Field, Sheet } from '../../components/ui'
import { pickText } from '../../lib/cardText'
import {
  STARTER,
  problemsOf,
  problemText,
  sourceLine,
  type CardList,
  type CardProblem,
  type CustomCardRow,
} from '../../lib/customCards'

type Tab = 'cards' | 'integrations' | 'shop' | 'submissions'

/** From this many cards on, a search sits above the list (KARTEN-11 EC-5). */
const SEARCH_FROM = 20

/** What the sheet is editing: a new card (`slug` null) or a saved one. */
interface Draft {
  slug: string | null
  text: string
  /** The card was deleted by somebody else while this sheet had it open (KARTEN-11 EC-6). */
  gone: boolean
}

/** The columns of the list on a wide screen; on a phone each row stacks. */
const COLUMNS = 'gap-x-3 gap-y-1.5 items-center md:grid-cols-[minmax(0,1.6fr)_minmax(0,1.1fr)_minmax(0,1fr)_minmax(0,0.9fr)_auto_auto]'

const TABS: Tab[] = ['cards', 'integrations', 'shop', 'submissions']

/**
 * System > Custom cards (KARTEN-11): every card of the installation, where it stands, and who may place it.
 *
 * The editor with its steps comes with a later version. Until then "Build a card" and "Edit" open the text of the
 * card, and the server's check names every problem by line and field.
 */
export function CustomCardsSettings() {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const cards = useQuery({ queryKey: ['custom-cards'], queryFn: () => get<CardList>('/cards') })
  const [tab, setTab] = useState<Tab>('cards')
  const [query, setQuery] = useState('')
  const [draft, setDraft] = useState<Draft | null>(null)
  const [problems, setProblems] = useState<CardProblem[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [removing, setRemoving] = useState<CustomCardRow | null>(null)
  const [openBoards, setOpenBoards] = useState<string | null>(null)

  const rows = cards.data?.cards ?? []
  const limit = cards.data?.limit ?? 200
  const lang = i18n.language
  const nameOf = (card: CustomCardRow) => pickText(card.name, lang) || card.slug

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle || rows.length < SEARCH_FROM) return rows
    return rows.filter((card) => `${nameOf(card)} ${card.slug} ${sourceLine(card)}`.toLowerCase().includes(needle))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, query, lang])

  const changed = async () => {
    await Promise.all([queryClient.invalidateQueries({ queryKey: ['custom-cards'] }), queryClient.invalidateQueries({ queryKey: ['cards-library'] })])
  }
  const fail = (failure: unknown) => setError(failure instanceof ApiError ? failure.message : t('errors.network'))

  const openNew = () => {
    setProblems([])
    setError('')
    setDraft({ slug: null, text: STARTER, gone: false })
  }

  const openEdit = async (card: CustomCardRow) => {
    setProblems([])
    setError('')
    try {
      const full = await get<CustomCardRow & { yaml: string }>(`/cards/${encodeURIComponent(card.slug)}`)
      setDraft({ slug: card.slug, text: full.yaml, gone: false })
    } catch (failure) {
      fail(failure)
    }
  }

  const save = async (asNew: boolean) => {
    if (!draft) return
    setBusy(true)
    setError('')
    setProblems([])
    try {
      if (draft.slug === null || asNew) await post('/cards', { yaml: draft.text })
      else await put(`/cards/${encodeURIComponent(draft.slug)}`, { yaml: draft.text })
      await changed()
      setDraft(null)
    } catch (failure) {
      if (failure instanceof ApiError && failure.code === 'card_deleted') setDraft({ ...draft, gone: true })
      else if (problemsOf(failure).length) setProblems(problemsOf(failure))
      else fail(failure)
    } finally {
      setBusy(false)
    }
  }

  const share = async (card: CustomCardRow, allowed: boolean) => {
    setError('')
    try {
      await put(`/cards/${encodeURIComponent(card.slug)}/users`, { allowed })
      await changed()
    } catch (failure) {
      fail(failure)
    }
  }

  const copy = async (card: CustomCardRow) => {
    setError('')
    try {
      await post(`/cards/${encodeURIComponent(card.slug)}/copy`)
      await changed()
    } catch (failure) {
      fail(failure)
    }
  }

  const remove = async (card: CustomCardRow) => {
    setError('')
    try {
      await del(`/cards/${encodeURIComponent(card.slug)}`)
      await changed()
    } catch (failure) {
      fail(failure)
    }
  }

  const counts: Partial<Record<Tab, number>> = { cards: rows.length, integrations: 0 }

  return (
    <>
      <div className="glass rounded-2xl p-5 mb-4">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
          <h2 className="font-semibold text-[15px]">{t('cards.title')}</h2>
          <button className="btn btn-accent" onClick={openNew}>
            <Plus size={15} /> {t('cards.build')}
          </button>
        </div>
        <div className="flex flex-wrap gap-1.5 mb-4" role="tablist" aria-label={t('cards.title')}>
          {TABS.map((one) => (
            <button
              key={one}
              role="tab"
              aria-selected={tab === one}
              className={`flex items-center gap-2 h-9 px-3 rounded-xl border text-sm transition-colors ${tab === one ? 'border-accent/50 bg-accent-soft text-accent font-medium' : 'border-line text-muted hover:text-ink hover:bg-surface-hover'}`}
              onClick={() => setTab(one)}
            >
              {t(`cards.tabs.${one}`)}
              {counts[one] !== undefined && <span className="chip !py-0 text-[11px]">{counts[one]}</span>}
            </button>
          ))}
        </div>

        {error && (
          <p className="text-sm text-bad mb-3" role="alert">
            {error}
          </p>
        )}

        {tab !== 'cards' && <p className="text-sm text-muted">{t('cards.later')}</p>}

        {tab === 'cards' && cards.isSuccess && rows.length === 0 && (
          <EmptyState
            title={t('cards.title')}
            body={t('cards.lead')}
            action={
              <div className="flex flex-wrap justify-center gap-2">
                <button className="btn btn-accent" onClick={openNew}>
                  <Plus size={15} /> {t('cards.build')}
                </button>
                <button className="btn" onClick={() => setTab('shop')}>
                  {t('cards.openShop')}
                </button>
              </div>
            }
          />
        )}

        {tab === 'cards' && rows.length > 0 && (
          <>
            {rows.length >= SEARCH_FROM && (
              <div className="relative mb-3">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
                <input className="input input-icon" aria-label={t('cards.search')} placeholder={t('cards.search')} value={query} onChange={(event) => setQuery(event.target.value)} />
              </div>
            )}
            <div className={'hidden md:grid ' + COLUMNS + ' text-[11px] uppercase tracking-wide text-faint pb-1 border-b border-line'} aria-hidden="true">
              <span>{t('cards.col.card')}</span>
              <span>{t('cards.col.source')}</span>
              <span>{t('cards.col.from')}</span>
              <span>{t('cards.col.placed')}</span>
              <span>{t('cards.col.users')}</span>
              <span />
            </div>
            <ul className="divide-y divide-line">
              {shown.map((card) => (
                <li key={card.slug} className={'grid py-3 ' + COLUMNS}>
                  <div className="min-w-0">
                    <div className="text-sm font-medium truncate">{nameOf(card)}</div>
                    <div className="text-[11px] text-muted truncate">
                      <span className="chip !py-0 mr-1.5">{t(`cards.form.${card.form}`)}</span>
                      {card.slug}
                    </div>
                  </div>
                  <div className="min-w-0 flex items-center gap-1.5 text-sm">
                    <span className="md:hidden text-[11px] text-faint">{t('cards.col.source')}</span>
                    {card.requires[0] && <ServiceIcon icon={card.requires[0].icon} size={16} />}
                    <span className="truncate">{sourceLine(card)}</span>
                  </div>
                  <div className="min-w-0 text-sm">
                    <span className="md:hidden text-[11px] text-faint mr-1.5">{t('cards.col.from')}</span>
                    {card.origin === 'shop' ? t('cards.fromShop', { version: card.shop_version || card.version }) : t('cards.local')}
                    {card.author && <span className="block text-[11px] text-muted truncate">{card.author}</span>}
                  </div>
                  <div className="min-w-0 text-sm">
                    <span className="md:hidden text-[11px] text-faint mr-1.5">{t('cards.col.placed')}</span>
                    {card.boards.length === 0 ? (
                      <span className="text-muted">{t('cards.notPlaced')}</span>
                    ) : (
                      <button className="text-accent hover:underline" aria-expanded={openBoards === card.slug} onClick={() => setOpenBoards(openBoards === card.slug ? null : card.slug)}>
                        {t('cards.boards', { count: card.boards.length })}
                      </button>
                    )}
                    {openBoards === card.slug && (
                      <ul className="mt-1 text-[12px]" aria-label={t('cards.boardsOf', { name: nameOf(card) })}>
                        {card.boards.map((board) => (
                          <li key={board.id}>
                            <Link to={`/b/${board.slug}`} className="text-accent hover:underline">
                              {board.name}
                            </Link>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="md:hidden text-[11px] text-faint">{t('cards.col.users')}</span>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={card.users_may_place}
                      aria-label={t('cards.usersMayPlaceNamed', { name: nameOf(card) })}
                      onClick={() => void share(card, !card.users_may_place)}
                      className={`relative flex-none w-10 h-6 rounded-full transition-colors ${card.users_may_place ? 'bg-accent' : 'bg-[color-mix(in_srgb,var(--nd-text)_18%,transparent)]'}`}
                    >
                      <span className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform ${card.users_may_place ? 'translate-x-4' : ''}`} />
                    </button>
                  </div>
                  <div className="flex items-center justify-end gap-0.5">
                    <button className="btn btn-icon btn-flat" onClick={() => void openEdit(card)} aria-label={t('cards.editNamed', { name: nameOf(card) })} title={t('cards.edit')}>
                      <Pencil size={15} />
                    </button>
                    <button className="btn btn-icon btn-flat" onClick={() => void copy(card)} aria-label={t('cards.copyNamed', { name: nameOf(card) })} title={t('cards.copy')}>
                      <Copy size={15} />
                    </button>
                    <button className="btn btn-icon btn-flat btn-danger" onClick={() => setRemoving(card)} aria-label={t('cards.deleteNamed', { name: nameOf(card) })} title={t('cards.delete')}>
                      <Trash2 size={15} />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
            <p className="text-xs text-muted mt-3">{t('cards.footer', { count: rows.length, limit })}</p>
          </>
        )}
      </div>

      {draft && (
        <Sheet
          open
          onClose={() => setDraft(null)}
          wide
          title={draft.slug === null ? t('cards.newTitle') : t('cards.editTitle', { name: draft.slug })}
          footer={
            <>
              <button className="btn" onClick={() => setDraft(null)}>
                {t('common.cancel')}
              </button>
              {draft.gone ? (
                <button className="btn btn-accent" onClick={() => void save(true)} disabled={busy}>
                  {t('cards.saveAsNew')}
                </button>
              ) : (
                <button className="btn btn-accent" onClick={() => void save(false)} disabled={busy || !draft.text.trim()}>
                  {t('common.save')}
                </button>
              )}
            </>
          }
        >
          {draft.gone && (
            <div className="rounded-lg border border-warn/40 px-3 py-2 mb-3 text-sm" role="alert">
              <strong>{t('cards.deletedMeanwhile')}</strong>
              <p className="text-muted">{t('cards.deletedBody')}</p>
            </div>
          )}
          {error && (
            <p className="text-sm text-bad mb-3 rounded-lg border border-bad/40 px-3 py-2" role="alert">
              {error}
            </p>
          )}
          {problems.length > 0 && (
            <div className="rounded-lg border border-bad/40 px-3 py-2 mb-3" role="alert">
              <div className="text-sm font-medium text-bad mb-1">{t('cards.problems')}</div>
              <ul className="text-[13px] space-y-1">
                {problems.map((problem, index) => (
                  <li key={index}>
                    <span className="text-faint">{problem.line ? t('cards.line', { line: problem.line }) : problem.path}</span>
                    {problem.line && problem.path ? <span className="text-faint"> · {problem.path}</span> : null}
                    {' · '}
                    <span>{problemText(t, problem)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <Field label={t('cards.yaml')} help={t('cards.yamlHelp')} htmlFor="card-yaml">
            <textarea
              id="card-yaml"
              className="input font-mono text-[12.5px] leading-relaxed"
              rows={22}
              spellCheck={false}
              value={draft.text}
              onChange={(event) => setDraft({ ...draft, text: event.target.value })}
            />
          </Field>
        </Sheet>
      )}

      <Confirm
        open={removing !== null}
        title={t('cards.deleteTitle', { name: removing ? nameOf(removing) : '' })}
        body={removing && removing.boards.length === 0 ? t('cards.deleteBodyNone') : t('cards.deleteBody', { count: removing?.boards.length ?? 0 })}
        danger
        confirmLabel={t('cards.delete')}
        onCancel={() => setRemoving(null)}
        onConfirm={() => {
          const card = removing
          setRemoving(null)
          if (card) void remove(card)
        }}
      />
    </>
  )
}
