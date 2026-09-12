import { useQuery } from '@tanstack/react-query'
// Three lines, the handle every list on a phone is dragged by. Lucide calls
// it Menu; here it is a grip and nothing else.
import { ChevronDown, ChevronRight, Menu, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'

import { ApiError, del, get, patch, post, put } from '../../api/client'
import type { BoardSummary } from '../../api/types'
import { Confirm, Field, Toast } from '../../components/ui'
import { useHandleReorder } from '../../lib/useHandleReorder'
import { useAuth } from '../../stores/auth'
import { SettingsCard } from './SettingsCard'

export function BoardsSettings() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const me = useAuth((state) => state.user)
  const admin = me?.role === 'admin'
  /** Off by default: an administrator may open every board, and a list of
      ten colleagues' boards is not his overview. */
  const [showAll, setShowAll] = useState(false)
  const boards = useQuery({ queryKey: ['boards', showAll], queryFn: () => get<BoardSummary[]>(showAll ? '/boards?all_boards=true' : '/boards') })
  const [name, setName] = useState('')
  const [yamlText, setYamlText] = useState('')
  const [error, setError] = useState('')
  const [removing, setRemoving] = useState<BoardSummary | null>(null)
  const [removingPage, setRemovingPage] = useState<{ board: BoardSummary; page: BoardSummary['pages'][number] } | null>(null)
  const [reordering, setReordering] = useState(false)
  const [toast, setToast] = useState<{ text: string; level: 'ok' | 'error' } | null>(null)

  /** Send the whole order back.

      ⚠️ One call, not one per board. Two boards swapping places sent as two
      writes can land either way round, and the loser of that race is a menu
      in an order nobody asked for. */
  const save = (order: BoardSummary[]) => {
    setReordering(true)
    void put('/boards/order', { slugs: order.map((one) => one.slug) })
      .then(() => boards.refetch())
      .catch((failure) => setToast({ text: failure instanceof ApiError ? failure.message : t('errors.network'), level: 'error' }))
      .finally(() => setReordering(false))
  }

  /** The handle does the dragging and the arrow keys, in one place shared
      with every other list that is sorted this way. */
  const order = useHandleReorder(boards.data ?? [], (one) => one.slug, save)
  const rows = order.rows

  /** Which boards show their pages. Closed by default: the list is the answer
      to "which boards do I have", the pages are the second question. */
  const [expanded, setExpanded] = useState<number[]>([])
  return (
    <>
      <SettingsCard title={t('settings.boards.title')} description={t('settings.boards.help')}>
        {admin && (
          <label className="mb-3 flex items-center gap-2 text-sm text-muted">
            <input type="checkbox" className="accent-accent" checked={showAll} onChange={(event) => setShowAll(event.target.checked)} />
            {t('board.showAll')}
          </label>
        )}
        <ul className="space-y-1.5 mb-4">
          {rows.map((board) => {
            const open = expanded.includes(board.id)
            const mine = board.owner_id === me?.id
            const mayEdit = board.permission === 'owner' || board.permission === 'edit'
            return (
              <li
                key={board.id}
                ref={order.rowRef(board.slug)}
                className={`rounded-xl border text-sm ${order.holding === board.slug ? 'border-accent bg-surface-hover' : 'border-line'}`}
              >
                <div className="flex items-center gap-2 p-2.5">
                  {/* The arrow opens the pages; the name still leads to the
                      board. Two jobs, two targets. */}
                  <button
                    className="btn btn-icon h-7 w-7 btn-flat"
                    onClick={() => setExpanded((current) => (open ? current.filter((id) => id !== board.id) : [...current, board.id]))}
                    aria-expanded={open}
                    aria-label={t(open ? 'board.hidePages' : 'board.showPages', { name: board.name })}
                    title={t(open ? 'board.hidePages' : 'board.showPages', { name: board.name })}
                  >
                    {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  </button>
                  {/* The handle. ⚠️ `touch-action: none` is what makes it work
                      with a finger at all: without it the browser reads the
                      first millimetre of the drag as a page scroll and takes
                      the gesture away, and the row stays where it is. */}
                  <button
                    className="btn btn-icon h-7 w-7 btn-flat cursor-grab touch-none active:cursor-grabbing disabled:opacity-25"
                    disabled={reordering}
                    aria-label={t('board.moveWithHandle', { name: board.name })}
                    title={t('board.moveWithHandle', { name: board.name })}
                    {...order.handleProps(board.slug)}
                  >
                    <Menu size={15} />
                  </button>
                  <Link to={`/b/${board.slug}`} className="flex-1 font-medium truncate hover:text-accent">
                    {board.name}
                    {/* Whose board this is. Left out when it is mine: a list in
                        which every line says "mine" says nothing. */}
                    {!mine && board.owner_name && <span className="ml-2 text-[11px] font-normal text-faint">{t('board.ownedBy', { name: board.owner_name })}</span>}
                  </Link>
                  <span className="text-[11px] text-faint">{t('board.pageCount', { count: board.pages.length })}</span>
                  <span className="text-[11px] text-faint">{t('board.widgetCount', { count: board.widget_count })}</span>
                  {/* An administrator holds every board at the owner level.
                      Saying "owner" on somebody else's board would be a lie;
                      the chip says why he may act instead. */}
                  <span className="chip !py-0 text-[10px]">
                    {mine ? t('board.level.owner') : admin ? t('users.role.admin') : t(`board.level.${board.permission}`, { defaultValue: board.permission })}
                  </span>
                  {/* What stands in the menu at the top. Everything else is
                      still here and still has its address. */}
                  {mayEdit && !board.provisioned && (
                    <label className="flex items-center gap-1.5 text-[11px] text-muted" title={t('board.inMenuHelp')}>
                      <input
                        type="checkbox"
                        className="accent-accent"
                        checked={board.in_menu}
                        onChange={(event) =>
                          void patch(`/boards/${board.slug}`, { in_menu: event.target.checked })
                            .then(() => boards.refetch())
                            .catch((failure) => setToast({ text: failure instanceof ApiError ? failure.message : t('errors.network'), level: 'error' }))
                        }
                      />
                      {t('board.inMenu')}
                    </label>
                  )}
                  {board.provisioned && <span className="chip !py-0 text-[10px]">file</span>}
                  {/* Only the owner deletes, and never a board that comes from a
                      file: that one would be back after the next read. */}
                  {board.permission === 'owner' && !board.provisioned && (
                    <button className="btn btn-icon h-7 w-7 btn-danger" onClick={() => setRemoving(board)} aria-label={t('common.delete')} title={t('common.delete')}>
                      <Trash2 size={14} />
                    </button>
                  )}
                </div>

                {open && (
                  <ul className="border-t border-line px-2.5 py-2 space-y-1">
                    {board.pages.map((page) => (
                      <li key={page.id} className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-surface-hover">
                        <Link to={`/b/${board.slug}/${page.slug}`} className="flex-1 truncate text-muted hover:text-accent">
                          {page.name}
                        </Link>
                        <span className="text-[11px] text-faint">{t('board.widgetCount', { count: page.widget_count })}</span>
                        {/* A board keeps its last page: the server refuses, and
                            a button that only ever fails is worse than none. */}
                        {mayEdit && !board.provisioned && (
                          <button
                            className="btn btn-icon h-7 w-7 btn-danger"
                            disabled={board.pages.length <= 1}
                            onClick={() => setRemovingPage({ board, page })}
                            aria-label={t('board.deletePageTitle', { name: page.name })}
                            title={board.pages.length <= 1 ? t('board.lastPage') : t('board.deletePage')}
                          >
                            <Trash2 size={13} />
                          </button>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            )
          })}
        </ul>
        <Field label={t('board.newName')} htmlFor="nb-name">
          <div className="flex gap-2">
            <input id="nb-name" className="input" value={name} onChange={(e) => setName(e.target.value)} />
            <button className="btn btn-accent flex-none" disabled={!name.trim()} onClick={() => void post<{ slug: string }>('/boards', { name: name.trim() }).then((created) => navigate(`/b/${created.slug}`))}>
              {t('common.create')}
            </button>
          </div>
        </Field>
      </SettingsCard>
      <SettingsCard title={t('board.import')} description={t('board.importHelp')}>
        <textarea className="input mb-2" rows={8} aria-label={t('board.import')} value={yamlText} onChange={(e) => setYamlText(e.target.value)} placeholder="nexdeck: 1&#10;board:&#10;  name: …" />
        {error && (
          <p className="text-sm text-bad mb-2" role="alert">
            {error}
          </p>
        )}
        <button
          className="btn"
          disabled={!yamlText.trim()}
          onClick={() => {
            setError('')
            void post<{ slug: string }>('/boards/import', { yaml_text: yamlText })
              .then((created) => navigate(`/b/${created.slug}`))
              .catch((failure) => setError(failure instanceof ApiError ? failure.message : t('errors.network')))
          }}
        >
          {t('board.importRun')}
        </button>
        <p className="text-[11px] text-faint mt-3">{t('settings.boards.provisioning')}</p>
      </SettingsCard>
      <Confirm
        open={removingPage !== null}
        title={t('board.deletePageTitle', { name: removingPage?.page.name ?? '' })}
        body={removingPage && removingPage.page.widget_count > 0 ? t('board.deletePageBody', { count: removingPage.page.widget_count }) : t('board.deletePageEmpty')}
        danger
        onCancel={() => setRemovingPage(null)}
        onConfirm={() => {
          const target = removingPage
          setRemovingPage(null)
          if (!target) return
          void del(`/pages/${target.page.id}`)
            .then(() => boards.refetch())
            .then(() => setToast({ text: t('common.saved'), level: 'ok' }))
            .catch((failure) => setToast({ text: failure instanceof ApiError ? failure.message : t('errors.network'), level: 'error' }))
        }}
      />
      <Confirm
        open={removing !== null}
        title={t('board.remove', { name: removing?.name ?? '' })}
        body={t('board.removeBody', { count: removing?.widget_count ?? 0 })}
        danger
        onCancel={() => setRemoving(null)}
        onConfirm={() => {
          const target = removing
          setRemoving(null)
          if (!target) return
          void del(`/boards/${target.slug}`)
            .then(() => boards.refetch())
            .then(() => setToast({ text: t('common.saved'), level: 'ok' }))
            .catch((failure) => setToast({ text: failure instanceof ApiError ? failure.message : t('errors.network'), level: 'error' }))
        }}
      />
      {toast && (
        <Toast level={toast.level} onClose={() => setToast(null)}>
          {toast.text}
        </Toast>
      )}
    </>
  )
}
