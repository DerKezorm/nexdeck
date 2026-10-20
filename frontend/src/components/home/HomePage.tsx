import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Grid3x3, Heading, House, Lightbulb, Palette, Pencil, Plus, Settings2, Thermometer, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, get, post, put } from '../../api/client'
import {
  alignTo, climateSpots, controlWidth, freshId, isResizable, isWide, resizeTo, LAMP_STYLES, lampSender, lampSpots, MAX_TEXT, mergeWish, nextSpot, phoneGroups, SETTLE_MS, snap, stepTarget, surfaceHeight, withClimates, withLamps, withWish,
  type Box, type ClimateAnswer, type ClimateInfo, type Guide, type ClimateSensor, type ClimateView, type ClimateWish, type HomeAnswer, type HomeClimate, type HomeElement, type HomeHeading,
  type HomeLayout, type HomeLight, type LampInfo, type LampStyle, type LampWish, type SwitchAnswer,
} from '../../lib/home'
import { Spinner } from '../ui'
import { ClimateControl } from './ClimateControl'
import { ClimateDetails } from './ClimateDetails'
import { ClimatePicker } from './ClimatePicker'
import { LampDetails } from './LampDetails'
import { lampFace } from './LampFace'
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

/** While arranging without guides, the surface only shows its edge. */
const SURFACE_PLAIN = { outline: '1px dashed var(--nd-border-strong)', outlineOffset: '4px' } as const

/** While arranging, the surface shows its step as faint dots, so things can be lined up by eye. */
const SURFACE_DOTS = {
  backgroundImage: 'radial-gradient(color-mix(in srgb, var(--nd-text) 12%, transparent) 1px, transparent 1px)',
  backgroundSize: '16px 16px',
  outline: '1px dashed var(--nd-border-strong)',
  outlineOffset: '4px',
} as const

/** Whether guides are on while arranging, kept in the browser: a convenience of whoever arranges. */
const GUIDES = 'nexdeck.homeGuides'

function useGuides(): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState(() => {
    try {
      return localStorage.getItem(GUIDES) !== 'off'
    } catch {
      return true
    }
  })
  const change = (next: boolean) => {
    setOn(next)
    try {
      localStorage.setItem(GUIDES, next ? 'on' : 'off')
    } catch {
      // Storage may be unavailable; the choice then lasts as long as the page.
    }
  }
  return [on, change]
}

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
    (id: string, patch: { x?: number; y?: number; text?: string; style?: LampStyle; sensor?: ClimateSensor | null; width?: number }) => {
      if (!layout) return
      const changed = (element: HomeElement): HomeElement =>
        element.type === 'heading'
          ? { ...element, x: patch.x ?? element.x, y: patch.y ?? element.y, text: patch.text ?? element.text }
          : element.type === 'climate'
            ? { ...element, x: patch.x ?? element.x, y: patch.y ?? element.y, sensor: patch.sensor !== undefined ? patch.sensor : element.sensor, width: patch.width ?? element.width }
            : { ...element, x: patch.x ?? element.x, y: patch.y ?? element.y, style: patch.style ?? element.style, width: patch.width ?? element.width }
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
    (lights: LampInfo[], style: LampStyle = 'pill') => {
      setPicking(false)
      if (!layout || lights.length === 0) return
      const spots = lampSpots(layout.elements, lights.length, style)
      const added: HomeLight[] = []
      for (const [index, light] of lights.entries()) {
        added.push({ id: freshId([...layout.elements, ...added]), type: 'light', ...spots[index], rid: light.rid, entity_id: light.entity_id, name: light.name, style })
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

  // -- thermostats from Home Assistant -----------------------------------------

  const [pickingClimates, setPickingClimates] = useState(false)
  const [knownClimates, setKnownClimates] = useState<Record<string, ClimateInfo>>({})
  const placedClimates = new Set(elements.filter((element): element is HomeClimate => element.type === 'climate').map((element) => element.rid))
  const addClimates = useCallback(
    (climates: ClimateInfo[]) => {
      setPickingClimates(false)
      if (!layout || climates.length === 0) return
      const spots = climateSpots(layout.elements, climates.length)
      const added: HomeClimate[] = []
      for (const [index, climate] of climates.entries()) {
        added.push({ id: freshId([...layout.elements, ...added]), type: 'climate', ...spots[index], rid: climate.rid, entity_id: climate.entity_id, name: climate.name, style: 'pill', sensor: null })
      }
      setKnownClimates((now) => ({ ...now, ...Object.fromEntries(climates.map((climate) => [climate.rid, climate])) }))
      askAgain.current = true
      save({ ...layout, elements: [...layout.elements, ...added] }, 0)
    },
    [layout, save],
  )
  const climateOf = (element: HomeClimate): ClimateView | null => {
    const said = answer.data?.climates?.[element.id]
    if (said) return said.missing ? null : said
    const known = knownClimates[element.rid]
    return known ? { ...known, reading: known.current, sensor: null } : null
  }
  const climateMissing = (element: HomeClimate) => answer.data?.climates?.[element.id]?.missing === true
  const chooseSensor = useCallback(
    (element: HomeClimate, sensor: ClimateSensor | null) => {
      // The reading comes from the server: ask the page again once the choice is saved.
      askAgain.current = true
      change(element.id, { sensor })
    },
    [change],
  )

  // A target is gathered: each tap moves it a step, and one second after the
  // last one it goes out, so five taps are one call (``set_temperature``).
  const [targets, setTargets] = useState<Record<string, number>>({})
  const targetTimers = useRef<Record<string, number>>({})
  const climateAsks = useRef<Record<string, number>>({})
  const climateChain = useRef<Record<string, Promise<void>>>({})
  const settleTarget = useCallback((id: string, asked: number) => {
    if (climateAsks.current[id] !== asked) return
    setTargets((now) => {
      const rest = { ...now }
      delete rest[id]
      return rest
    })
  }, [])
  const tell = useCallback(
    (id: string, name: string, wish: ClimateWish, after?: (answered: ClimateAnswer | null) => void) => {
      const run = (climateChain.current[id] ?? Promise.resolve()).then(async () => {
        try {
          const answered = await post<ClimateAnswer>(`/pages/${pageId}/home/climates/${id}`, wish)
          queryClient.setQueryData<HomeAnswer>(['home', pageId], (old) => (old ? withClimates(old, { [id]: answered.climate }) : old))
          after?.(answered)
        } catch (failure) {
          const code = failure instanceof ApiError ? failure.code : ''
          setNote({ text: t(`homePage.climateProblems.${code}`, { name, defaultValue: t('homePage.climateFailed', { name }) }), level: 'error' })
          after?.(null)
        }
      })
      climateChain.current[id] = run
    },
    [pageId, queryClient, t],
  )
  const stepClimate = useCallback(
    (element: HomeClimate, info: ClimateView, steps: number) => {
      const from = targets[element.id] ?? info.target ?? info.reading ?? (info.min + info.max) / 2
      const next = stepTarget(info, from, steps)
      const asked = (climateAsks.current[element.id] ?? 0) + 1
      climateAsks.current[element.id] = asked
      setTargets((now) => ({ ...now, [element.id]: next }))
      window.clearTimeout(targetTimers.current[element.id])
      targetTimers.current[element.id] = window.setTimeout(() => {
        tell(element.id, info.name, { target: next }, (answered) => {
          if (!answered || answered.confirmed) settleTarget(element.id, asked)
          else window.setTimeout(() => settleTarget(element.id, asked), SETTLE_MS)
        })
      }, GATHER_MS)
    },
    [targets, tell, settleTarget],
  )
  useEffect(() => () => Object.values(targetTimers.current).forEach((timer) => window.clearTimeout(timer)), [])
  const [climateDetails, setClimateDetails] = useState<string | null>(null)
  const detailedClimate = elements.find((element): element is HomeClimate => element.type === 'climate' && element.id === climateDetails) ?? null
  const detailedClimateInfo = detailedClimate ? climateOf(detailedClimate) : null

  const addHeading = useCallback(() => {
    if (!layout) return
    const id = freshId(layout.elements)
    save({ ...layout, elements: [...layout.elements, { id, type: 'heading', ...nextSpot(layout.elements), text: t('homePage.newHeading') }] }, 0)
    setRenaming(id)
  }, [layout, save, t])

  // -- moving an element, by the pointer --------------------------------------

  const [guidesOn, setGuidesOn] = useGuides()
  const surface = useRef<HTMLDivElement>(null)
  const [dragged, setDragged] = useState<{ id: string; x: number; y: number; width?: number } | null>(null)
  const [guides, setGuides] = useState<Guide[]>([])
  const grab = useRef<{
    id: string; pointer: number; startX: number; startY: number; fromX: number; fromY: number; moved: boolean
    /** Moving the element, or dragging its width at the grip. */
    resizing: boolean
    own: Box
    others: Box[]
  } | null>(null)

  /** Every element's box as it is drawn, measured when a drag begins: the guides line up with what the eye sees. */
  const boxes = (id: string): { own: Box; others: Box[] } => {
    const origin = surface.current?.getBoundingClientRect()
    let own: Box = { x: 0, y: 0, width: 0, height: 0 }
    const others: Box[] = []
    for (const node of surface.current?.querySelectorAll<HTMLElement>('[data-element]') ?? []) {
      const rect = node.getBoundingClientRect()
      const box = { x: rect.left - (origin?.left ?? 0), y: rect.top - (origin?.top ?? 0), width: rect.width, height: rect.height }
      if (node.dataset.element === id) own = box
      else others.push(box)
    }
    return { own, others }
  }
  const onPointerDown = (element: HomeElement) => (event: ReactPointerEvent<HTMLElement>) => {
    if (!arranging || narrow || event.button !== 0 || renaming === element.id) return
    const target = event.target as HTMLElement
    if (target.closest('[data-element-tool]')) return
    const resizing = Boolean(target.closest('[data-resize]')) && isResizable(element)
    grab.current = { id: element.id, pointer: event.pointerId, startX: event.clientX, startY: event.clientY, fromX: element.x, fromY: element.y, moved: false, resizing, ...boxes(element.id) }
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
    if (held.resizing) {
      const element = elements.find((one) => one.id === held.id)
      const from = element && element.type !== 'heading' ? (controlWidth(element) ?? held.own.width) : held.own.width
      const sized = guidesOn ? resizeTo({ ...held.own, width: from }, from + dx, held.others) : resizeTo({ ...held.own, width: from }, from + dx, [])
      setDragged({ id: held.id, x: held.fromX, y: held.fromY, width: sized.width })
      setGuides(sized.guides)
      return
    }
    const raw = { ...held.own, x: held.fromX + dx, y: held.fromY + dy }
    const stepped = { x: snap(raw.x), y: snap(raw.y) }
    if (!guidesOn) {
      setDragged({ id: held.id, ...stepped })
      return
    }
    // The box as drawn moves by the same amount as the element's corner.
    const drawn = { ...raw, x: held.own.x + dx, y: held.own.y + dy }
    const lined = alignTo(drawn, { x: stepped.x + held.own.x - held.fromX, y: stepped.y + held.own.y - held.fromY }, held.others)
    setDragged({ id: held.id, x: Math.max(0, lined.x - (held.own.x - held.fromX)), y: Math.max(0, lined.y - (held.own.y - held.fromY)) })
    setGuides(lined.guides)
  }
  const onPointerUp = (event: ReactPointerEvent<HTMLElement>) => {
    const held = grab.current
    if (!held || held.pointer !== event.pointerId) return
    grab.current = null
    if (held.moved && dragged && dragged.id === held.id) {
      change(held.id, held.resizing && dragged.width !== undefined ? { width: dragged.width } : { x: dragged.x, y: dragged.y })
    } else if (!held.moved && !held.resizing && elements.find((element) => element.id === held.id)?.type === 'heading') setRenaming(held.id)
    setDragged(null)
    setGuides([])
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

  const placed = (element: HomeElement): HomeElement =>
    dragged && dragged.id === element.id ? { ...element, x: dragged.x, y: dragged.y, ...(dragged.width !== undefined && element.type !== 'heading' ? { width: dragged.width } : {}) } : element
  const draw = (element: HomeElement) =>
    element.type === 'climate' ? (
      <ClimateControl element={element} info={climateOf(element)} missing={climateMissing(element)} arranging={arranging} wide={narrow} pageId={pageId} width={controlWidth(element)}
        target={targets[element.id] ?? climateOf(element)?.target ?? null} setting={targets[element.id] !== undefined}
        onStep={canAct ? (steps) => { const info = climateOf(element); if (info) stepClimate(element, info, steps) } : undefined}
        onDetails={() => setClimateDetails(element.id)} onRemove={() => remove(element.id)} onSensor={(sensor) => chooseSensor(element, sensor)} />
    ) : element.type === 'light' ? (
      <LampControl element={element} info={standing(element)} missing={missing(element)} arranging={arranging} wide={narrow && isWide(element)} width={controlWidth(element)}
        onRemove={() => remove(element.id)} onStyle={(style) => change(element.id, { style })}
        onWish={canAct && !arranging ? (info, wish) => ask(element, info, wish) : undefined} onDetails={() => setDetails(element.id)} />
    ) : (
      <HeadingView element={element} arranging={arranging} renaming={renaming === element.id}
        onRename={(text) => { change(element.id, { text }); setRenaming(null) }} onCancel={() => setRenaming(null)}
        onStartRename={() => setRenaming(element.id)} onRemove={() => remove(element.id)} />
    )

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
              <button type="button" className="btn" onClick={() => setPickingClimates(true)}>
                <Thermometer size={15} /> {t('homePage.addClimate')}
              </button>
              <button type="button" className="btn" onClick={addHeading}>
                <Heading size={15} /> {t('homePage.addHeading')}
              </button>
            </div>
          )}
        </div>
      ) : narrow ? (
        // Each heading with the lamps that stand under it on the surface (``phoneGroups``).
        <div className="grid gap-5 pb-6">
          {phoneGroups(elements).map((group) => (
            <section key={group.heading?.id ?? 'top'} className="grid gap-3" data-phone-group={group.heading?.id ?? ''}>
              {group.heading && draw(group.heading)}
              {group.devices.length > 0 && (
                <div className="flex flex-wrap items-start gap-3">
                  {group.devices.map((device) => (
                    <div key={device.id} className={isWide(device) ? 'w-full' : ''}>{draw(device)}</div>
                  ))}
                </div>
              )}
            </section>
          ))}
        </div>
      ) : (
        <div
          ref={surface}
          className={`relative ${arranging ? 'rounded-2xl' : ''}`}
          style={{ height: surfaceHeight(elements.map(placed)), ...(arranging ? (guidesOn ? SURFACE_DOTS : SURFACE_PLAIN) : {}) }}
          data-home-surface
          data-guides={arranging && guidesOn ? '' : undefined}
        >
          {guides.map((guide, index) => (
            <span key={index} className="home-guide" data-guide={guide.axis}
              style={guide.axis === 'x' ? { left: guide.at, top: guide.from - 8, width: 1, height: guide.to - guide.from + 16 } : { top: guide.at, left: guide.from - 8, height: 1, width: guide.to - guide.from + 16 }} />
          ))}
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
      {arranging && <EditBar onLight={() => setPicking(true)} onClimate={() => setPickingClimates(true)} onHeading={addHeading} guides={guidesOn} onGuides={() => setGuidesOn(!guidesOn)}
        onAddPage={onAddPage} onSettings={onSettings} onDone={onDone} />}
      {detailed && detailedInfo && canAct && (
        <LampDetails info={detailedInfo} onWish={(wish) => ask(detailed, detailedInfo, wish)} onClose={() => setDetails(null)} />
      )}
      {detailedClimate && detailedClimateInfo && (
        <ClimateDetails info={detailedClimateInfo} target={targets[detailedClimate.id] ?? detailedClimateInfo.target} setting={targets[detailedClimate.id] !== undefined}
          onStep={canAct ? (steps) => stepClimate(detailedClimate, detailedClimateInfo, steps) : null}
          onWish={canAct ? (wish) => tell(detailedClimate.id, detailedClimateInfo.name, wish) : null}
          onClose={() => setClimateDetails(null)} />
      )}
      {canEdit && <ClimatePicker open={pickingClimates} pageId={pageId} placed={placedClimates} onClose={() => setPickingClimates(false)} onAdd={addClimates} />}
      {canEdit && <LightPicker open={picking} pageId={pageId} placed={placedLamps} onClose={() => setPicking(false)} onAdd={addLights} />}
      {note && (
        <div className={`fixed left-1/2 -translate-x-1/2 bottom-36 md:bottom-24 z-50 glass-strong rounded-xl px-4 py-2.5 text-sm shadow-xl ${note.level === 'error' ? 'text-bad' : ''}`} role="status">
          {note.text}
        </div>
      )}
    </div>
  )
}

/** How long the taps on a thermostat's plus and minus are gathered before the target goes out. */
const GATHER_MS = 1000

/** How long a finger rests on a lamp before it opens the details. */
const HOLD_MS = 500
/** How far a pointer travels before a press becomes a drag. */
const DRAG_PX = 6

/**
 * A lamp, drawn in its style (``lampFace``). For those who may act on the
 * board a tap switches it, a drag sideways dims it, holding it (or a right
 * click) opens its details; arrow keys dim it too. A lamp Home Assistant
 * cannot reach or no longer has stays still. While the page is arranged it
 * carries two tools: its style, and taking it off the page.
 */
function LampControl({ element, info, missing, arranging, wide, width, onRemove, onStyle, onWish, onDetails }: {
  element: HomeLight
  info: LampInfo | null
  missing: boolean
  arranging: boolean
  /** In the phone's list a pill, a chip or a slider runs the width of the screen. */
  wide: boolean
  /** The width of a pill, a chip or a slider (``controlWidth``). */
  width: number | null
  onRemove: () => void
  onStyle: (style: LampStyle) => void
  onWish?: (info: LampInfo, wish: LampWish) => void
  onDetails: () => void
}) {
  const { t } = useTranslation()
  const name = info?.name || element.name || element.entity_id
  const state = missing ? t('homePage.gone')
    : !info ? ''
    : info.unavailable ? t('homePage.offline')
    : info.on ? (info.dims && info.pct !== null ? `${info.pct} %` : t('homePage.on'))
    : t('homePage.off')
  const press = useRef<{ pointer: number; x: number; y: number; from: number; width: number; dragging: boolean; held: boolean; timer?: number; sent?: number } | null>(null)
  /** Set when a press ended as a drag or a hold, so the click that follows it switches nothing. */
  const swallow = useRef(false)
  const [dimming, setDimming] = useState<number | null>(null)
  const [choosing, setChoosing] = useState(false)
  const tools = useRef<HTMLDivElement>(null)
  useEffect(() => () => window.clearTimeout(press.current?.timer), [])
  // The style menu closes as menus do: Escape, or a press anywhere else.
  useEffect(() => {
    if (!choosing) return
    const away = (event: PointerEvent) => {
      if (!tools.current?.contains(event.target as Node)) setChoosing(false)
    }
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setChoosing(false)
    }
    window.addEventListener('pointerdown', away, true)
    window.addEventListener('keydown', key)
    return () => {
      window.removeEventListener('pointerdown', away, true)
      window.removeEventListener('keydown', key)
    }
  }, [choosing])

  const quiet = missing || Boolean(info?.unavailable)
  const face = lampFace({ style: element.style, info, name, state, quiet, dimming, wide, width })
  const title = [name, info?.area, missing ? t('homePage.missing') : info?.unavailable ? t('homePage.unavailable') : onWish ? t('homePage.lampHint') : ''].filter(Boolean).join(' · ')
  const label = [name, state].filter(Boolean).join(', ')

  if (onWish && info && !quiet) {
    const down = (event: ReactPointerEvent<HTMLButtonElement>) => {
      if (event.button !== 0) return
      swallow.current = false
      // A drag across the whole drawing is the whole range; a small drawing gets a pill's worth to travel.
      const width = Math.max(160, event.currentTarget.getBoundingClientRect().width || 0)
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
        className={`lamp-control ${face.className} cursor-pointer touch-pan-y select-none`}
        style={face.style}
        data-lamp={element.entity_id}
        data-style={element.style}
        title={title}
        aria-label={label}
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
        {face.children}
      </button>
    )
  }
  return (
    // ⚠️ The tools stand beside the drawing, not in it: a pill and a slider clip what reaches past their edge.
    <div ref={tools} className={`relative ${wide ? 'w-full' : 'w-fit'}`}>
      <div className={`lamp-control ${face.className}`} style={face.style} data-lamp={element.entity_id} data-style={element.style} title={title} aria-label={label}>
        {face.children}
      </div>
      {arranging && width !== null && !wide && <span className="home-grip" data-resize aria-hidden title={t('homePage.dragWidth')} />}
      {arranging && (
        <span className="absolute -top-3 -right-3 z-10 flex gap-1" data-element-tool>
          <button type="button" className="btn btn-icon h-6 w-6 rounded-full glass-strong" onClick={() => setChoosing((open) => !open)}
            aria-label={t('homePage.chooseStyle')} title={t('homePage.chooseStyle')} aria-haspopup="menu" aria-expanded={choosing}>
            <Palette size={12} />
          </button>
          <button type="button" className="btn btn-icon btn-danger h-6 w-6 rounded-full glass-strong" onClick={onRemove} aria-label={t('homePage.removeLight')} title={t('homePage.removeLight')}>
            <Trash2 size={12} />
          </button>
        </span>
      )}
      {arranging && choosing && (
        <div className="absolute left-0 top-full mt-2 z-30 glass-strong rounded-xl p-1.5 shadow-2xl grid grid-cols-2 gap-1 w-64" role="menu" aria-label={t('homePage.chooseStyle')} data-element-tool>
          {LAMP_STYLES.map((style) => (
            <button key={style} type="button" role="menuitemradio" aria-checked={element.style === style}
              className={`text-left text-[13px] px-2.5 py-1.5 rounded-lg ${element.style === style ? 'bg-[var(--nd-accent-soft)] text-accent font-medium' : 'hover:bg-[var(--nd-surface-hover)]'}`}
              onClick={() => {
                setChoosing(false)
                onStyle(style)
              }}>
              {t(`homePage.styles.${style}`)}
            </button>
          ))}
        </div>
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

function EditBar(props: { onLight: () => void; onClimate: () => void; onHeading: () => void; guides: boolean; onGuides: () => void; onAddPage: () => void; onSettings: () => void; onDone: () => void }) {
  const { t } = useTranslation()
  return (
    <div className="fixed bottom-20 md:bottom-6 left-1/2 -translate-x-1/2 z-40 max-w-[calc(100vw-1rem)] glass-strong rounded-full px-2 py-1.5 flex items-center gap-1 shadow-2xl" data-no-picture>
      <button type="button" className="btn btn-flat whitespace-nowrap" onClick={props.onLight} aria-label={t('homePage.addLight')}>
        <Lightbulb size={15} /> <span className="hidden sm:inline">{t('homePage.addLight')}</span>
      </button>
      <button type="button" className="btn btn-flat whitespace-nowrap" onClick={props.onClimate} aria-label={t('homePage.addClimate')}>
        <Thermometer size={15} /> <span className="hidden sm:inline">{t('homePage.addClimate')}</span>
      </button>
      <button type="button" className="btn btn-flat whitespace-nowrap" onClick={props.onHeading} aria-label={t('homePage.addHeading')}>
        <Heading size={15} /> <span className="hidden sm:inline">{t('homePage.addHeading')}</span>
      </button>
      <button type="button" className={`btn btn-flat whitespace-nowrap ${props.guides ? 'text-accent' : ''}`} onClick={props.onGuides} aria-pressed={props.guides}
        aria-label={t('homePage.guides')} title={t('homePage.guidesHelp')}>
        <Grid3x3 size={15} /> <span className="hidden xl:inline">{t('homePage.guides')}</span>
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
