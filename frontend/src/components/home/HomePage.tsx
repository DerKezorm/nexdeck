import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Heading, House, Lightbulb, Pencil, Plus, Settings2, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, get, post, put } from '../../api/client'
import {
  freshId, lampColour, lampSender, lampSpots, MAX_TEXT, mergeWish, nextSpot, readingOrder, SETTLE_MS, snap, surfaceHeight, withLamps, withWish,
  type HomeAnswer, type HomeElement, type HomeHeading, type HomeLayout, type HomeLight, type LampInfo, type LampWish, type SwitchAnswer,
} from '../../lib/home'
import { Spinner } from '../ui'
import { LampDetails } from './LampDetails'
import { LightPicker } from './LightPicker'

interface Props {
  pageId: number
  editing: boolean
  canEdit: boolean
  /** May press what stands on the page: switch a lamp. */
  canAct: boolean
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
export function HomePage({ pageId, editing, canEdit, canAct, onAddPage, onSettings, onDone }: Props) {
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
  const askAgain = useRef(false)
  const flush = useCallback(() => {
    const run = inflight.current.then(async () => {
      const next = waiting.current
      if (!next) return
      window.clearTimeout(timer.current)
      try {
        const saved = await put<{ layout: HomeLayout; version: number }>(`/pages/${pageId}/home`, { elements: next.elements, version: version.current })
        if (waiting.current === next) waiting.current = null
        version.current = saved.version
        if (askAgain.current) {
          askAgain.current = false
          void refetch()
        }
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
    (id: string, patch: { x?: number; y?: number; text?: string }) => {
      if (!layout) return
      const changed = (element: HomeElement): HomeElement =>
        element.type === 'heading' ? { ...element, ...patch } : { ...element, x: patch.x ?? element.x, y: patch.y ?? element.y }
      save({ ...layout, elements: layout.elements.map((element) => (element.id === id ? changed(element) : element)) })
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
  // -- lamps from Home Assistant -------------------------------------------------

  const [picking, setPicking] = useState(false)
  /** What the picker knew of lamps just added, until the page has been asked about them. */
  const [known, setKnown] = useState<Record<string, LampInfo>>({})
  const placedLamps = new Set(elements.filter((element): element is HomeLight => element.type === 'light').map((element) => element.rid))
  const addLights = useCallback(
    (lights: LampInfo[]) => {
      setPicking(false)
      if (!layout || lights.length === 0) return
      const spots = lampSpots(layout.elements, lights.length)
      const added: HomeLight[] = []
      for (const [index, light] of lights.entries()) {
        added.push({ id: freshId([...layout.elements, ...added]), type: 'light', ...spots[index], rid: light.rid, entity_id: light.entity_id, name: light.name, style: 'pill' })
      }
      setKnown((now) => ({ ...now, ...Object.fromEntries(lights.map((light) => [light.rid, light])) }))
      askAgain.current = true
      save({ ...layout, elements: [...layout.elements, ...added] }, 0)
    },
    [layout, save],
  )
  const infoOf = (element: HomeLight): LampInfo | null => {
    const said = answer.data?.lights?.[element.id]
    if (said) return said.missing ? null : said
    return known[element.rid] ?? null
  }
  const missing = (element: HomeLight) => answer.data?.lights?.[element.id]?.missing === true

  // -- switching, dimming, colouring a lamp ---------------------------------------

  const queryClient = useQueryClient()
  /** What a lamp was just asked to do, shown until the server has answered (``withWish``). */
  const [wanted, setWanted] = useState<Record<string, LampWish>>({})
  const [details, setDetails] = useState<string | null>(null)
  /** How often each lamp has been asked, so an answer to an older wish does not clear a newer one. */
  const asks = useRef<Record<string, number>>({})
  const names = useRef<Record<string, string>>({})
  // ⚠️ One wish of a lamp after the other, and the newest winning (``lampSender``).
  // Two taps sent side by side could reach Home Assistant the wrong way round,
  // and dragging a slider would send a hundred calls a second.
  const senders = useRef<Record<string, ReturnType<typeof lampSender>>>({})
  const settle = useCallback((id: string, asked: number) => {
    if (asks.current[id] !== asked) return
    setWanted((now) => {
      const rest = { ...now }
      delete rest[id]
      return rest
    })
  }, [])
  const senderOf = useCallback(
    (id: string) => {
      const known = senders.current[id]
      if (known) return known
      const sender = lampSender(async (wish) => {
        const asked = asks.current[id]
        try {
          const answered = await post<SwitchAnswer>(`/pages/${pageId}/home/lights/${id}`, wish)
          queryClient.setQueryData<HomeAnswer>(['home', pageId], (old) => (old ? withLamps(old, { [id]: answered.light }) : old))
          if (sender.queued()) return
          // Not confirmed: Home Assistant named nothing that changed. The lamp may have been so
          // already, or it has not answered yet. What was asked shows a moment longer, then the
          // lamp as the server and the board's stream know it: taken back, if it never came.
          if (answered.confirmed) settle(id, asked)
          else window.setTimeout(() => settle(id, asked), SETTLE_MS)
        } catch (failure) {
          const code = failure instanceof ApiError ? failure.code : ''
          const name = names.current[id] ?? ''
          setNote({ text: t(`homePage.switchProblems.${code}`, { name, defaultValue: t('homePage.switchFailed', { name }) }), level: 'error' })
          settle(id, asked)
        }
      })
      senders.current[id] = sender
      return sender
    },
    [pageId, queryClient, settle, t],
  )
  const ask = useCallback(
    (element: HomeLight, info: LampInfo, wish: LampWish) => {
      asks.current[element.id] = (asks.current[element.id] ?? 0) + 1
      names.current[element.id] = info.name
      setWanted((now) => ({ ...now, [element.id]: now[element.id] ? mergeWish(now[element.id], wish) : wish }))
      senderOf(element.id).ask(wish)
    },
    [senderOf],
  )
  const standing = (element: HomeLight): LampInfo | null => {
    const info = infoOf(element)
    return info ? withWish(info, wanted[element.id]) : null
  }
  const detailed = elements.find((element): element is HomeLight => element.type === 'light' && element.id === details) ?? null
  const detailedInfo = detailed ? standing(detailed) : null

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
    else if (!held.moved && elements.find((element) => element.id === held.id)?.type === 'heading') setRenaming(held.id)
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
  const draw = (element: HomeElement) =>
    element.type === 'light' ? (
      <LampPill element={element} info={standing(element)} missing={missing(element)} arranging={arranging} wide={narrow} onRemove={() => remove(element.id)}
        onWish={canAct && !arranging ? (info, wish) => ask(element, info, wish) : undefined} onDetails={() => setDetails(element.id)} />
    ) : (
      <HeadingView element={element} arranging={arranging} renaming={renaming === element.id}
        onRename={(text) => { change(element.id, { text }); setRenaming(null) }} onCancel={() => setRenaming(null)}
        onStartRename={() => setRenaming(element.id)} onRemove={() => remove(element.id)} />
    )
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
            <div className="flex flex-wrap justify-center gap-2 mt-4">
              <button type="button" className="btn btn-accent" onClick={() => setPicking(true)}>
                <Lightbulb size={15} /> {t('homePage.addLight')}
              </button>
              <button type="button" className="btn" onClick={addHeading}>
                <Heading size={15} /> {t('homePage.addHeading')}
              </button>
            </div>
          )}
        </div>
      ) : narrow ? (
        <div className="grid gap-3 pb-6">
          {shown.map((element) => (
            <div key={element.id}>{draw(element)}</div>
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
                {draw(element)}
              </div>
            )
          })}
        </div>
      )}
      {arranging && <EditBar onLight={() => setPicking(true)} onHeading={addHeading} onAddPage={onAddPage} onSettings={onSettings} onDone={onDone} />}
      {detailed && detailedInfo && canAct && (
        <LampDetails info={detailedInfo} onWish={(wish) => ask(detailed, detailedInfo, wish)} onClose={() => setDetails(null)} />
      )}
      {canEdit && <LightPicker open={picking} pageId={pageId} placed={placedLamps} onClose={() => setPicking(false)} onAdd={addLights} />}
      {note && (
        <div className={`fixed left-1/2 -translate-x-1/2 bottom-36 md:bottom-24 z-50 glass-strong rounded-xl px-4 py-2.5 text-sm shadow-xl ${note.level === 'error' ? 'text-bad' : ''}`} role="status">
          {note.text}
        </div>
      )}
    </div>
  )
}

/** How long a finger rests on a pill before it opens the details. */
const HOLD_MS = 500
/** How far a pointer travels before a press becomes a drag. */
const DRAG_PX = 6

/**
 * A lamp as a pill, the first of the drawings on the board of sketches: its
 * light, its name, how bright. For those who may act on the board a tap
 * switches it, a drag sideways dims it, holding it (or a right click) opens
 * its details; arrow keys dim it too. A lamp Home Assistant cannot reach or
 * no longer has stays still.
 */
function LampPill({ element, info, missing, arranging, wide, onRemove, onWish, onDetails }: {
  element: HomeLight
  info: LampInfo | null
  missing: boolean
  arranging: boolean
  /** In the phone's list: as wide as the screen, a row to tap rather than a pill to aim at. */
  wide: boolean
  onRemove: () => void
  onWish?: (info: LampInfo, wish: LampWish) => void
  onDetails: () => void
}) {
  const { t } = useTranslation()
  const colour = lampColour(info)
  const name = info?.name || element.name || element.entity_id
  const state = missing ? t('homePage.gone')
    : !info ? ''
    : info.unavailable ? t('homePage.offline')
    : info.on ? (info.dims && info.pct !== null ? `${info.pct} %` : t('homePage.on'))
    : t('homePage.off')
  const lit = colour
    ? { borderColor: `color-mix(in srgb, ${colour} 50%, transparent)`, background: `color-mix(in srgb, ${colour} 14%, var(--nd-surface))`, boxShadow: `0 0 22px -8px ${colour}` }
    : undefined
  const press = useRef<{ pointer: number; x: number; y: number; from: number; width: number; dragging: boolean; held: boolean; timer?: number; sent?: number } | null>(null)
  /** Set when a press ended as a drag or a hold, so the click that follows it switches nothing. */
  const swallow = useRef(false)
  const [dimming, setDimming] = useState<number | null>(null)
  useEffect(() => () => window.clearTimeout(press.current?.timer), [])

  const shell = `glass relative overflow-hidden flex items-center gap-2.5 ${wide ? 'w-full h-12' : 'h-10 max-w-[256px]'} pl-1.5 pr-4 rounded-full text-left ${missing ? 'border-dashed opacity-60' : info?.unavailable ? 'opacity-55' : ''} ${arranging ? 'pr-1.5' : ''}`
  const title = [name, info?.area, missing ? t('homePage.missing') : info?.unavailable ? t('homePage.unavailable') : onWish ? t('homePage.lampHint') : ''].filter(Boolean).join(' · ')
  const inside = (
    <>
      {dimming !== null && (
        // While dragging, the pill fills to the brightness under the finger.
        <span aria-hidden className="absolute inset-y-0 left-0 pointer-events-none" style={{ width: `${dimming}%`, background: `color-mix(in srgb, ${colour ?? 'rgb(255, 196, 120)'} 30%, transparent)` }} />
      )}
      <span className="relative grid place-items-center w-7 h-7 rounded-full flex-none transition-colors duration-200" style={colour ? { background: colour, color: '#1b1206' } : { background: 'color-mix(in srgb, var(--nd-text) 9%, transparent)' }}>
        <Lightbulb size={15} className={colour ? '' : 'text-muted'} />
      </span>
      <span className="relative text-[13px] font-medium whitespace-nowrap min-w-0 truncate">{name}</span>
      {state && <span className={`relative num text-[11.5px] whitespace-nowrap flex-none ${colour ? '' : 'text-muted'}`}>{state}</span>}
    </>
  )
  if (onWish && info && !missing && !info.unavailable) {
    const down = (event: ReactPointerEvent<HTMLButtonElement>) => {
      if (event.button !== 0) return
      swallow.current = false
      const width = event.currentTarget.getBoundingClientRect().width || 200
      const held = { pointer: event.pointerId, x: event.clientX, y: event.clientY, from: info.on ? (info.pct ?? 100) : 0, width, dragging: false, held: false, timer: 0 }
      held.timer = window.setTimeout(() => {
        if (press.current !== held || held.dragging) return
        held.held = true
        swallow.current = true
        onDetails()
      }, HOLD_MS)
      press.current = held
    }
    const move = (event: ReactPointerEvent<HTMLButtonElement>) => {
      const held = press.current
      if (!held || held.pointer !== event.pointerId || held.held || !info.dims) return
      const dx = event.clientX - held.x
      if (!held.dragging) {
        if (Math.abs(dx) < DRAG_PX || Math.abs(dx) < Math.abs(event.clientY - held.y)) return
        held.dragging = true
        swallow.current = true
        window.clearTimeout(held.timer)
        try {
          event.currentTarget.setPointerCapture(event.pointerId)
        } catch {
          // A pointer that is already gone has nothing to capture.
        }
      }
      const pct = Math.min(100, Math.max(1, Math.round(held.from + (dx / held.width) * 100)))
      setDimming(pct)
      // A finger resting past the end moves on and on; the lamp hears each brightness once.
      if (pct === held.sent) return
      held.sent = pct
      onWish(info, { brightness_pct: pct })
    }
    const up = () => {
      window.clearTimeout(press.current?.timer)
      press.current = null
      setDimming(null)
    }
    const key = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
      if (!info.dims) return
      const step = event.key === 'ArrowRight' || event.key === 'ArrowUp' ? 10 : event.key === 'ArrowLeft' || event.key === 'ArrowDown' ? -10 : 0
      if (!step) return
      event.preventDefault()
      onWish(info, { brightness_pct: Math.min(100, Math.max(1, (info.on ? (info.pct ?? 100) : 0) + step)) })
    }
    return (
      <button
        type="button"
        className={`${shell} cursor-pointer touch-pan-y select-none transition-[background-color,border-color,box-shadow,transform] duration-200 hover:brightness-[1.04] active:scale-[0.97] focus-visible:outline-2 focus-visible:outline-[var(--nd-accent)]`}
        style={lit}
        data-lamp={element.entity_id}
        title={title}
        aria-pressed={info.on}
        aria-haspopup="dialog"
        onPointerDown={down}
        onPointerMove={move}
        onPointerUp={up}
        onPointerCancel={up}
        onKeyDown={key}
        onContextMenu={(event) => {
          event.preventDefault()
          up()
          onDetails()
        }}
        onClick={() => {
          if (swallow.current) {
            swallow.current = false
            return
          }
          onWish(info, { on: !info.on })
        }}
      >
        {inside}
      </button>
    )
  }
  return (
    <div className={shell} style={lit} data-lamp={element.entity_id} title={title}>
      {inside}
      {arranging && (
        <span className="relative flex items-center ml-1" data-element-tool>
          <button type="button" className="btn btn-icon btn-flat btn-danger h-6 w-6" onClick={onRemove} aria-label={t('homePage.removeLight')} title={t('homePage.removeLight')}>
            <Trash2 size={13} />
          </button>
        </span>
      )}
    </div>
  )
}

function HeadingView(props: {
  element: HomeHeading
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

function EditBar(props: { onLight: () => void; onHeading: () => void; onAddPage: () => void; onSettings: () => void; onDone: () => void }) {
  const { t } = useTranslation()
  return (
    <div className="fixed bottom-20 md:bottom-6 left-1/2 -translate-x-1/2 z-40 max-w-[calc(100vw-1rem)] glass-strong rounded-full px-2 py-1.5 flex items-center gap-1 shadow-2xl" data-no-picture>
      <button type="button" className="btn btn-flat whitespace-nowrap" onClick={props.onLight} aria-label={t('homePage.addLight')}>
        <Lightbulb size={15} /> <span className="hidden sm:inline">{t('homePage.addLight')}</span>
      </button>
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
