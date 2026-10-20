import { useQuery } from '@tanstack/react-query'
import { Check, Heading, House, Pencil, Plus, Settings2, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, get, put } from '../../api/client'
import { freshId, MAX_TEXT, nextSpot, readingOrder, snap, surfaceHeight, type HomeAnswer, type HomeElement, type HomeLayout } from '../../lib/home'
import { Spinner } from '../ui'

interface Props {
  pageId: number
  editing: boolean
  canEdit: boolean
  onAddPage: () => void
  onSettings: () => void
  onDone: () => void
}

/** While arranging, the surface shows its step as faint dots, so things can be lined up by eye. */
const SURFACE_DOTS = {
  backgroundImage: 'radial-gradient(color-mix(in srgb, var(--nd-text) 12%, transparent) 1px, transparent 1px)',
  backgroundSize: '16px 16px',
  outline: '1px dashed var(--nd-border-strong)',
  outlineOffset: '4px',
} as const

/** Below this width the surface is read as a list, top to bottom; nothing is dragged there. */
const NARROW = '(max-width: 639px)'

function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(() => window.matchMedia?.(NARROW)?.matches ?? false)
  useEffect(() => {
    const list = window.matchMedia?.(NARROW)
    if (!list) return
    const change = () => setNarrow(list.matches)
    list.addEventListener?.('change', change)
    return () => list.removeEventListener?.('change', change)
  }, [])
  return narrow
}

/**
 * A home page: a free surface of Home Assistant controls, not bound to the
 * grid of cards, so a light switch can be as small as a light switch. What
 * stands where belongs to the page and is saved for everyone, a moment after
 * the last change, the way a topology page saves its plan.
 */
export function HomePage({ pageId, editing, canEdit, onAddPage, onSettings, onDone }: Props) {
  const { t } = useTranslation()
  const narrow = useNarrow()
  const answer = useQuery({ queryKey: ['home', pageId], queryFn: () => get<HomeAnswer>(`/pages/${pageId}/home`) })
  const problem = answer.data?.problem ?? null
  const arranging = editing && canEdit

  // -- what stands where, saved a moment after the last change ----------------

  const [layout, setLayout] = useState<HomeLayout | null>(null)
  const version = useRef(0)
  const timer = useRef<number | undefined>(undefined)
  const waiting = useRef<HomeLayout | null>(null)
  const [note, setNote] = useState<{ text: string; level?: 'error' } | null>(null)

  useEffect(() => {
    const server = answer.data
    // ⚠️ Not over a change of our own still waiting to be saved; and only a
    // version that moved on, or the first one (see ``put_layouts``).
    if (!server || waiting.current) return
    if (layout === null || server.version > version.current) {
      version.current = server.version
      setLayout(server.layout)
    }
  }, [answer.data, layout])

  const refetch = answer.refetch
  // ⚠️ One save at a time. Adding a heading and naming it straight away are two
  // saves a moment apart; sent side by side, both carried the same version, the
  // server took the first and refused the second as somebody else's, and the
  // page threw away the name it had just been given.
  const inflight = useRef<Promise<void>>(Promise.resolve())
  const flush = useCallback(() => {
    const run = inflight.current.then(async () => {
      const next = waiting.current
      if (!next) return
      window.clearTimeout(timer.current)
      try {
        const saved = await put<{ layout: HomeLayout; version: number }>(`/pages/${pageId}/home`, { elements: next.elements, version: version.current })
        if (waiting.current === next) waiting.current = null
        version.current = saved.version
      } catch (failure) {
        waiting.current = null
        if (failure instanceof ApiError && failure.status === 409) {
          setNote({ text: t('homePage.movedOn') })
          version.current = 0
          setLayout(null)
          void refetch()
        } else setNote({ text: t('homePage.saveFailed'), level: 'error' })
      }
    })
    inflight.current = run
    return run
  }, [pageId, t, refetch])

  const save = useCallback(
    (next: HomeLayout, at = 500) => {
      setLayout(next)
      if (!canEdit) return
      waiting.current = next
      window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => void flush(), at)
    },
    [canEdit, flush],
  )
  // What waits is saved when the page goes, not lost.
  useEffect(() => () => void flush(), [flush])
  useEffect(() => {
    if (!note) return
    const gone = window.setTimeout(() => setNote(null), 6000)
    return () => window.clearTimeout(gone)
  }, [note])

  // -- changing what stands on it --------------------------------------------

  const [renaming, setRenaming] = useState<string | null>(null)
  const elements = layout?.elements ?? []

  const change = useCallback(
    (id: string, patch: Partial<HomeElement>) => {
      if (!layout) return
      save({ ...layout, elements: layout.elements.map((element) => (element.id === id ? { ...element, ...patch } : element)) })
    },
    [layout, save],
  )
  const remove = useCallback(
    (id: string) => {
      if (!layout) return
      save({ ...layout, elements: layout.elements.filter((element) => element.id !== id) }, 0)
    },
    [layout, save],
  )
  const addHeading = useCallback(() => {
    if (!layout) return
    const id = freshId(layout.elements)
    save({ ...layout, elements: [...layout.elements, { id, type: 'heading', ...nextSpot(layout.elements), text: t('homePage.newHeading') }] }, 0)
    setRenaming(id)
  }, [layout, save, t])

  // -- moving an element, by the pointer --------------------------------------

  const [dragged, setDragged] = useState<{ id: string; x: number; y: number } | null>(null)
  const grab = useRef<{ id: string; pointer: number; startX: number; startY: number; fromX: number; fromY: number; moved: boolean } | null>(null)

  const onPointerDown = (element: HomeElement) => (event: ReactPointerEvent<HTMLElement>) => {
    if (!arranging || narrow || event.button !== 0 || renaming === element.id) return
    if ((event.target as HTMLElement).closest('[data-element-tool]')) return
    grab.current = { id: element.id, pointer: event.pointerId, startX: event.clientX, startY: event.clientY, fromX: element.x, fromY: element.y, moved: false }
    try {
      event.currentTarget.setPointerCapture(event.pointerId)
    } catch {
      // A pointer that is already gone has nothing to capture.
    }
  }
  const onPointerMove = (event: ReactPointerEvent<HTMLElement>) => {
    const held = grab.current
    if (!held || held.pointer !== event.pointerId) return
    const dx = event.clientX - held.startX
    const dy = event.clientY - held.startY
    if (!held.moved && Math.hypot(dx, dy) < 4) return
    held.moved = true
    setDragged({ id: held.id, x: snap(held.fromX + dx), y: snap(held.fromY + dy) })
  }
  const onPointerUp = (event: ReactPointerEvent<HTMLElement>) => {
    const held = grab.current
    if (!held || held.pointer !== event.pointerId) return
    grab.current = null
    if (held.moved && dragged && dragged.id === held.id) change(held.id, { x: dragged.x, y: dragged.y })
    else if (!held.moved) setRenaming(held.id)
    setDragged(null)
  }

  // -- drawing ---------------------------------------------------------------

  if (answer.isLoading || (!layout && !answer.isError)) {
    return (
      <div className="flex items-center justify-center py-32">
        <Spinner />
      </div>
    )
  }
  if (answer.isError || !layout) {
    return (
      <div className="flex items-center justify-center p-6 py-32">
        <div className="glass rounded-2xl p-6 text-center max-w-md">
          <p className="font-medium">{t('homePage.loadFailed')}</p>
        </div>
      </div>
    )
  }

  const placed = (element: HomeElement) => (dragged && dragged.id === element.id ? { ...element, x: dragged.x, y: dragged.y } : element)
  const shown = narrow ? readingOrder(elements) : elements

  return (
    <div className="max-w-[1600px] mx-auto px-3 sm:px-4 pt-4" data-home-page>
      {problem && (
        <div className="glass rounded-2xl px-4 py-3 mb-4 border border-[color-mix(in_srgb,var(--nd-warn)_40%,transparent)] max-w-2xl" role="status" data-no-picture>
          <p className="text-sm font-medium">{t(`homePage.problems.${problem.code}`, { defaultValue: problem.message })}</p>
          {problem.hint && <p className="text-xs text-muted mt-0.5">{t(`homePage.hints.${problem.code}`, { defaultValue: problem.hint })}</p>}
        </div>
      )}
      {elements.length === 0 ? (
        <div className="glass rounded-2xl p-8 text-center max-w-xl mx-auto mt-10">
          <House className="mx-auto text-accent" size={28} />
          <h2 className="font-semibold mt-3">{t('homePage.emptyTitle')}</h2>
          <p className="text-sm text-muted mt-1">{canEdit ? t('homePage.emptyText') : t('homePage.emptyViewer')}</p>
          {arranging && (
            <button type="button" className="btn btn-accent mt-4" onClick={addHeading}>
              <Heading size={15} /> {t('homePage.addHeading')}
            </button>
          )}
        </div>
      ) : narrow ? (
        <div className="grid gap-3 pb-6">
          {shown.map((element) => (
            <ElementView key={element.id} element={element} arranging={arranging} renaming={renaming === element.id}
              onRename={(text) => { change(element.id, { text }); setRenaming(null) }} onCancel={() => setRenaming(null)}
              onStartRename={() => setRenaming(element.id)} onRemove={() => remove(element.id)} />
          ))}
        </div>
      ) : (
        <div
          className={`relative ${arranging ? 'rounded-2xl' : ''}`}
          style={{ height: surfaceHeight(elements.map(placed)), ...(arranging ? SURFACE_DOTS : {}) }}
          data-home-surface
        >
          {elements.map((raw) => {
            const element = placed(raw)
            return (
              <div
                key={element.id}
                className={`absolute ${arranging ? 'cursor-grab active:cursor-grabbing touch-none select-none' : ''} ${dragged?.id === element.id ? 'z-10 opacity-90' : ''}`}
                style={{ left: element.x, top: element.y }}
                onPointerDown={onPointerDown(raw)}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onPointerCancel={() => { grab.current = null; setDragged(null) }}
                data-element={element.id}
              >
                <ElementView element={element} arranging={arranging} renaming={renaming === element.id}
                  onRename={(text) => { change(element.id, { text }); setRenaming(null) }} onCancel={() => setRenaming(null)}
                  onStartRename={() => setRenaming(element.id)} onRemove={() => remove(element.id)} />
              </div>
            )
          })}
        </div>
      )}
      {arranging && <EditBar onHeading={addHeading} onAddPage={onAddPage} onSettings={onSettings} onDone={onDone} />}
      {note && (
        <div className={`fixed left-1/2 -translate-x-1/2 bottom-36 md:bottom-24 z-50 glass-strong rounded-xl px-4 py-2.5 text-sm shadow-xl ${note.level === 'error' ? 'text-bad' : ''}`} role="status">
          {note.text}
        </div>
      )}
    </div>
  )
}

function ElementView(props: {
  element: HomeElement
  arranging: boolean
  renaming: boolean
  onRename: (text: string) => void
  onCancel: () => void
  onStartRename: () => void
  onRemove: () => void
}) {
  const { t } = useTranslation()
  const { element, arranging, renaming } = props
  const [draft, setDraft] = useState(element.text)
  useEffect(() => setDraft(element.text), [element.text, renaming])
  const label = 'text-[12px] font-semibold uppercase tracking-[0.08em] text-muted whitespace-nowrap'
  if (renaming) {
    const done = () => {
      const text = draft.trim()
      if (text) props.onRename(text)
      else props.onCancel()
    }
    return (
      <input
        className={`input h-8 w-64 ${label} normal-case tracking-normal`}
        autoFocus
        maxLength={MAX_TEXT}
        value={draft}
        aria-label={t('homePage.headingName')}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={done}
        onKeyDown={(event) => {
          if (event.key === 'Enter') done()
          if (event.key === 'Escape') props.onCancel()
        }}
      />
    )
  }
  return (
    <div className={`group flex items-center gap-2 min-h-8 ${arranging ? 'pl-2 pr-1 rounded-lg border border-dashed border-[var(--nd-accent)] bg-[color-mix(in_srgb,var(--nd-bg)_40%,transparent)]' : ''}`}>
      <h2 className={`${label} m-0`}>
        {element.text}
      </h2>
      {arranging && (
        <span className="flex items-center" data-element-tool>
          <button type="button" className="btn btn-icon btn-flat h-6 w-6" onClick={props.onStartRename} aria-label={t('homePage.renameHeading')} title={t('homePage.renameHeading')}>
            <Pencil size={13} />
          </button>
          <button type="button" className="btn btn-icon btn-flat btn-danger h-6 w-6" onClick={props.onRemove} aria-label={t('homePage.removeHeading')} title={t('homePage.removeHeading')}>
            <Trash2 size={13} />
          </button>
        </span>
      )}
    </div>
  )
}

function EditBar(props: { onHeading: () => void; onAddPage: () => void; onSettings: () => void; onDone: () => void }) {
  const { t } = useTranslation()
  return (
    <div className="fixed bottom-20 md:bottom-6 left-1/2 -translate-x-1/2 z-40 max-w-[calc(100vw-1rem)] glass-strong rounded-full px-2 py-1.5 flex items-center gap-1 shadow-2xl" data-no-picture>
      <button type="button" className="btn btn-flat whitespace-nowrap" onClick={props.onHeading} aria-label={t('homePage.addHeading')}>
        <Heading size={15} /> <span className="hidden sm:inline">{t('homePage.addHeading')}</span>
      </button>
      <span className="w-px h-5 bg-line mx-0.5" aria-hidden="true" />
      <button type="button" className="btn btn-flat whitespace-nowrap" onClick={props.onAddPage} aria-label={t('board.addPage')}>
        <Plus size={15} /> <span className="hidden lg:inline">{t('board.addPage')}</span>
      </button>
      <button type="button" className="btn btn-flat whitespace-nowrap" onClick={props.onSettings} aria-label={t('board.settings')}>
        <Settings2 size={15} /> <span className="hidden lg:inline">{t('board.settings')}</span>
      </button>
      <button type="button" className="btn btn-accent rounded-full" onClick={props.onDone}>
        <Check size={15} /> {t('common.done')}
      </button>
    </div>
  )
}
