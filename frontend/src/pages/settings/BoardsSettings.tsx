import { useQuery } from '@tanstack/react-query'
// Three lines, the handle every list on a phone is dragged by. Lucide calls
// it Menu; here it is a grip and nothing else.
import { ChevronDown, ChevronRight, Menu, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'

import { ApiError, del, get, patch, post, put } from '../../api/client'
import type { BoardSummary } from '../../api/types'
import { Confirm, Field, Toast } from '../../components/ui'
import { moved } from '../../lib/reorder'
import { useAuth } from '../../stores/auth'
import { SettingsCard } from './SettingsCard'

/** The order a list would have if the held row were let go at `y`.

    ⚠️ By how many of the other rows the pointer is past, not by "which row
    contains the pointer". Containment leaves dead ground: the gaps between
    rows, and everything below the last one. A drag that runs off the end of
    the list lands nowhere instead of at the end, and that is what a drag
    downwards does the moment it passes the bottom row.

    Counting is also the part that does not care about order. The boxes come
    from the DOM, which can be one frame behind the order this is measuring;
    how many midpoints sit above `y` is the same number either way, and only
    the slicing needs the true order.
*/
function orderIfDroppedAt(rows: BoardSummary[], y: number, heldId: number, boxes: Map<number, HTMLLIElement>): BoardSummary[] {
  const held = rows.find((one) => one.id === heldId)
  if (!held) return rows
  const others = rows.filter((one) => one.id !== heldId)
  const place = others.filter((one) => {
    const box = boxes.get(one.id)?.getBoundingClientRect()
    return box ? y >= box.top + box.height / 2 : false
  }).length
  return [...others.slice(0, place), held, ...others.slice(place)]
}

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
  /** The order while a finger is still on the list. Null when nothing is
      being dragged, and the answer from the server is what is shown again. */
  const [dragged, setDragged] = useState<BoardSummary[] | null>(null)
  const [holding, setHolding] = useState<number | null>(null)
  //: One entry per row, so a drag can ask where the rows actually are.
  const rowRefs = useRef(new Map<number, HTMLLIElement>())
  const rows = dragged ?? boards.data ?? []

  /** Send the whole order back.

      ⚠️ One call, not one per board. Two boards swapping places sent as two
      writes can land either way round, and the loser of that race is a menu
      in an order nobody asked for. */
  const save = (order: BoardSummary[]) => {
    setReordering(true)
    void put('/boards/order', { slugs: order.map((one) => one.slug) })
      .then(() => boards.refetch())
      .catch((failure) => setToast({ text: failure instanceof ApiError ? failure.message : t('errors.network'), level: 'error' }))
      .finally(() => {
        setReordering(false)
        setDragged(null)
      })
  }


  /** While a row is held, the window has the drag, not the handle.

      ⚠️ The handle used to capture the pointer, which is the usual way. It
      does not survive this list: reordering moves the handle's own node in the
      DOM, and a moved node loses the capture. From the second step on the
      events went to whatever sat under the cursor, so the row followed only
      when the pointer happened to cross its own handle again. That looked
      exactly like "downwards it moves one place and then stops". */
  useEffect(() => {
    if (holding === null) return
    const id = holding
    const follow = (event: PointerEvent) => {
      const y = event.clientY
      // The updater form, so every move sees the order the last one left,
      // whether or not React has re-rendered in between. Returning the same
      // array when nothing moved keeps this from redrawing on every pixel.
      setDragged((current) => {
        if (!current) return current
        const order = orderIfDroppedAt(current, y, id, rowRefs.current)
        return order.every((one, place) => one.id === current[place].id) ? current : order
      })
    }
    const letGo = () => setHolding(null)
    window.addEventListener('pointermove', follow)
    window.addEventListener('pointerup', letGo)
    window.addEventListener('pointercancel', letGo)
    return () => {
      window.removeEventListener('pointermove', follow)
      window.removeEventListener('pointerup', letGo)
      window.removeEventListener('pointercancel', letGo)
    }
  }, [holding])

  /** Let go: write the new order, or forget it when nothing actually moved.

      One place for both ways in, the drag and the arrow keys, so a row that
      ends up where it started never costs a write. */
  useEffect(() => {
    if (holding !== null || dragged === null || reordering) return
    const saved = boards.data ?? []
    if (dragged.every((one, place) => one.id === saved[place]?.id)) setDragged(null)
    else save(dragged)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [holding, dragged, reordering])

  /** The same move, from the keyboard.

      ⚠️ Not a nicety. Dragging is the only way a pointer can reorder this
      list, and until the two arrow buttons were replaced by this handle they
      were the only way anything else could. A list that can be sorted by mouse
      alone is a list a switch, a voice control or a keyboard cannot sort. */
  const nudge = (index: number, by: number) => {
    const target = index + by
    if (reordering || target < 0 || target >= rows.length) return
    setDragged(moved(rows, index, target))
  }
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
          {rows.map((board, index) => {
            const open = expanded.includes(board.id)
            const mine = board.owner_id === me?.id
            const mayEdit = board.permission === 'owner' || board.permission === 'edit'
            return (
              <li
                key={board.id}
                ref={(element) => {
                  if (element) rowRefs.current.set(board.id, element)
                  else rowRefs.current.delete(board.id)
                }}
                className={`rounded-xl border text-sm ${holding === board.id ? 'border-accent bg-surface-hover' : 'border-line'}`}
              >
                <div className="flex items-center gap-2 p-2.5">
                  {/* The arrow opens the pages; the name still leads to the
                      board. Two jobs, two targets. */}
                  <button
                    className="btn btn-icon h-7 w-7 border-0 bg-transparent"
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
                    className="btn btn-icon h-7 w-7 border-0 bg-transparent cursor-grab touch-none active:cursor-grabbing disabled:opacity-25"
                    disabled={reordering}
                    aria-label={t('board.moveWithHandle', { name: board.name })}
                    title={t('board.moveWithHandle', { name: board.name })}
                    onPointerDown={(event) => {
                      // ⚠️ No setPointerCapture. React moves this very node
                      // while the list reorders, and a moved node loses the
                      // capture: after the first step the drag went deaf, and
                      // only answered again when the pointer happened to pass
                      // over the handle. The window listens instead.
                      event.preventDefault()
                      setDragged(rows)
                      setHolding(board.id)
                    }}
                    onKeyDown={(event) => {
                      // Ctrl, Alt and Meta with an arrow belong to the browser
                      // and the window manager: word-wise movement, workspace
                      // switching. Taking those would cost more than sorting a
                      // list is worth.
                      if (event.ctrlKey || event.altKey || event.metaKey) return
                      if (event.key === 'ArrowUp') nudge(index, -1)
                      else if (event.key === 'ArrowDown') nudge(index, 1)
                      else return
                      event.preventDefault()
                    }}
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
        <textarea className="input mb-2" rows={8} value={yamlText} onChange={(e) => setYamlText(e.target.value)} placeholder="nexdeck: 1&#10;board:&#10;  name: …" />
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
