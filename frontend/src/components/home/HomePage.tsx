import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Blinds, ChartLine, Check, DoorOpen, Sparkles, ToggleRight, Droplets, Grid3x3, Heading, House, Lightbulb, MessageSquareWarning, Palette, Pencil, Plus, Radar, Settings2, Thermometer, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, get, post, put } from '../../api/client'
import {
  alignTo, byHand, climateSpots, controlWidth, freshId, isResizable, isWide, resizeTo, LAMP_STYLES, lampSender, lampSpots, MAX_TEXT, mergeWish, nextSpot, phoneGroups, SETTLE_MS, snap, STAT_HEIGHTS, STAT_WIDTHS, statSize, statSpots, stepTarget,
  surfaceHeight, withActions, withClimates, withCovers, isScalable, scaleOf, scaleTo,
  type ActionAnswer, type HomeScene, type HomeScenes, type HomeSwitch, type HomeSwitches, type SceneColour, withLamps, withWish, heightOf, widthOf, pageHints, sensorSpots, type Check as HintCheck, type ReadingRow,
  type CoverAnswer, type CoverScene, type CoverWish, type HomeCover, type HomeCovers,
  type Box, type ClimateAnswer, type ClimateInfo, type ClimateStyle, type Guide, type ClimateSensor, type ClimateView, type ClimateWish, type HomeAnswer, type HomeClimate, type HomeElement, type HomeHeading,
  type HomeLayout, type HomeLight, type HomeStat, type LampInfo, type LampStyle, type LampWish, type StatStyle, type SwitchAnswer,
} from '../../lib/home'
import { Spinner } from '../ui'
import { ClimateControl } from './ClimateControl'
import { ClimateDetails } from './ClimateDetails'
import { ClimatePicker } from './ClimatePicker'
import { LampDetails } from './LampDetails'
import { lampFace } from './LampFace'
import { LightPicker } from './LightPicker'
import { Felt } from './Felt'
import { Rename } from './Rename'
import { StatCard } from './StatCard'
import { StatPicker } from './StatPicker'
import { ActionPicker, type FreshAction } from './ActionPicker'
import { CoverControl, CoverDetails } from './CoverControl'
import { CoverPicker, defaultScenes, type FreshCover } from './CoverPicker'
import { CoversCard } from './CoversCard'
import { SceneControl, ScenesCard } from './SceneControl'
import { ContactsCard, HintsCard, ReadingsCard } from './SensorCards'
import { ContactControl, ReadingControl, useNow } from './SensorControl'
import { SensorPicker, type FreshSensor } from './SensorPicker'
import { SwitchControl, SwitchesCard } from './SwitchControl'

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
    (id: string, patch: {
      x?: number; y?: number; text?: string; style?: LampStyle | ClimateStyle | StatStyle | string; sensor?: ClimateSensor | null; width?: number
      height?: number; sensors?: ClimateSensor[]; title?: string; rows?: ReadingRow[]; checks?: HintCheck[]; label?: string; name?: string
      scenes?: CoverScene[]; scale?: number; colour?: SceneColour; confirm?: boolean
    }) => {
      if (!layout) return
      const changed = (element: HomeElement): HomeElement =>
        element.type === 'heading'
          ? { ...element, x: patch.x ?? element.x, y: patch.y ?? element.y, text: patch.text ?? element.text }
          : element.type === 'contact' || element.type === 'contacts' || element.type === 'reading' || element.type === 'readings' || element.type === 'hints' ||
            element.type === 'cover' || element.type === 'covers' || element.type === 'scene' || element.type === 'scenes' || element.type === 'switch' ||
            element.type === 'switches'
            ? ({
                ...element, x: patch.x ?? element.x, y: patch.y ?? element.y, width: patch.width ?? element.width,
                ...('style' in element && patch.style ? { style: patch.style } : {}),
                ...((element.type === 'contacts' || element.type === 'covers' || element.type === 'scenes' || element.type === 'switches') && patch.sensors ? { sensors: patch.sensors } : {}),
                ...(element.type === 'scene' && patch.colour ? { colour: patch.colour } : {}),
                ...((element.type === 'switch' || element.type === 'switches') && patch.confirm !== undefined ? { confirm: patch.confirm } : {}),
                ...(element.type === 'covers' && patch.scenes ? { scenes: patch.scenes } : {}),
                ...(patch.scale !== undefined && (element.type === 'contact' || element.type === 'reading' || element.type === 'cover' || element.type === 'scene' ||
                  element.type === 'switch') ? { scale: patch.scale } : {}),
                ...(element.type === 'readings' && patch.rows ? { rows: patch.rows } : {}),
                ...('title' in element && patch.title !== undefined ? { title: patch.title } : {}),
                ...(element.type === 'hints' && patch.checks ? { checks: patch.checks } : {}),
                ...((element.type === 'contact' || element.type === 'cover' || element.type === 'scene' || element.type === 'switch') && patch.label !== undefined ? { label: patch.label } : {}),
                ...(element.type === 'reading' && patch.name !== undefined ? { name: patch.name } : {}),
              } as HomeElement)
          : element.type === 'stat'
            ? { ...element, x: patch.x ?? element.x, y: patch.y ?? element.y, style: (patch.style as StatStyle | undefined) ?? element.style, width: patch.width ?? element.width,
                height: patch.height ?? element.height, sensors: patch.sensors ?? element.sensors, title: patch.title ?? element.title }
          : element.type === 'climate'
            ? { ...element, x: patch.x ?? element.x, y: patch.y ?? element.y, sensor: patch.sensor !== undefined ? patch.sensor : element.sensor, width: patch.width ?? element.width,
                style: (patch.style as ClimateStyle | undefined) ?? element.style, label: patch.label ?? element.label, scale: patch.scale ?? element.scale }
            : { ...element, x: patch.x ?? element.x, y: patch.y ?? element.y, style: (patch.style as LampStyle | undefined) ?? element.style, width: patch.width ?? element.width, label: patch.label ?? element.label,
                scale: patch.scale ?? element.scale }
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
    // The page's own name where it has one, in the drawing, the details and what is said when switching fails.
    return info ? withWish(element.label ? { ...info, name: element.label } : info, wanted[element.id]) : null
  }
  const detailed = elements.find((element): element is HomeLight => element.type === 'light' && element.id === details) ?? null
  const detailedInfo = detailed ? standing(detailed) : null

  // -- thermostats from Home Assistant -----------------------------------------

  const [pickingClimates, setPickingClimates] = useState(false)
  const [knownClimates, setKnownClimates] = useState<Record<string, ClimateInfo>>({})
  const placedClimates = new Set(elements.filter((element): element is HomeClimate => element.type === 'climate').map((element) => element.rid))
  const addClimates = useCallback(
    (climates: ClimateInfo[], style: ClimateStyle = 'pill') => {
      setPickingClimates(false)
      if (!layout || climates.length === 0) return
      const spots = climateSpots(layout.elements, climates.length, style)
      const added: HomeClimate[] = []
      for (const [index, climate] of climates.entries()) {
        added.push({ id: freshId([...layout.elements, ...added]), type: 'climate', ...spots[index], rid: climate.rid, entity_id: climate.entity_id, name: climate.name, style, sensor: null })
      }
      setKnownClimates((now) => ({ ...now, ...Object.fromEntries(climates.map((climate) => [climate.rid, climate])) }))
      askAgain.current = true
      save({ ...layout, elements: [...layout.elements, ...added] }, 0)
    },
    [layout, save],
  )
  /** A thermostat as Home Assistant has it. */
  const climateFromHa = (element: HomeClimate): ClimateView | null => {
    const said = answer.data?.climates?.[element.id]
    if (said) return said.missing ? null : said
    const known = knownClimates[element.rid]
    return known ? { ...known, reading: known.current, sensor: null } : null
  }
  /** A thermostat as the page shows it: by the page's own name where it has one. */
  const climateOf = (element: HomeClimate): ClimateView | null => {
    const info = climateFromHa(element)
    return info && element.label ? { ...info, name: element.label } : info
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
  /**
   * A new target for a thermostat, shown at once and sent after ``after``
   * milliseconds of quiet, or not yet (null) while a finger still moves it.
   */
  const aimClimate = useCallback(
    (element: HomeClimate, info: ClimateView, next: number, after: number | null) => {
      const asked = (climateAsks.current[element.id] ?? 0) + 1
      climateAsks.current[element.id] = asked
      setTargets((now) => ({ ...now, [element.id]: next }))
      window.clearTimeout(targetTimers.current[element.id])
      if (after === null) return
      targetTimers.current[element.id] = window.setTimeout(() => {
        tell(element.id, info.name, { target: next }, (answered) => {
          if (!answered || answered.confirmed) settleTarget(element.id, asked)
          else window.setTimeout(() => settleTarget(element.id, asked), SETTLE_MS)
        })
      }, after)
    },
    [tell, settleTarget],
  )
  const stepClimate = useCallback(
    (element: HomeClimate, info: ClimateView, steps: number) => {
      const from = targets[element.id] ?? info.target ?? info.reading ?? (info.min + info.max) / 2
      aimClimate(element, info, stepTarget(byHand(info), from, steps), GATHER_MS)
    },
    [targets, aimClimate],
  )
  useEffect(() => () => Object.values(targetTimers.current).forEach((timer) => window.clearTimeout(timer)), [])
  const [climateDetails, setClimateDetails] = useState<string | null>(null)
  const detailedClimate = elements.find((element): element is HomeClimate => element.type === 'climate' && element.id === climateDetails) ?? null
  const detailedClimateInfo = detailedClimate ? climateOf(detailedClimate) : null

  // -- statistics cards ------------------------------------------------------

  /** The picker: null closed, 'new' to add cards, or the id of the card whose sensors are changed. */
  const [statPicking, setStatPicking] = useState<string | null>(null)
  const addStats = useCallback(
    (cards: { style: StatStyle; sensors: ClimateSensor[]; title: string }[]) => {
      setStatPicking(null)
      if (!layout || cards.length === 0) return
      const spots = statSpots(layout.elements, cards.length, cards[0].style)
      const added: HomeStat[] = []
      for (const [index, card] of cards.entries()) {
        added.push({ id: freshId([...layout.elements, ...added]), type: 'stat', ...spots[index], style: card.style, sensors: card.sensors, title: card.title })
      }
      save({ ...layout, elements: [...layout.elements, ...added] }, 0)
    },
    [layout, save],
  )
  const statCard = elements.find((element): element is HomeStat => element.type === 'stat' && element.id === statPicking) ?? null

  // -- doors, windows, temperature and humidity ------------------------------

  const now = useNow()
  /** The sensor picker: what it picks, and the card whose sensors are changed, if one is. */
  const [sensorPicking, setSensorPicking] = useState<{ mode: 'contacts' | 'readings'; card: string | null } | null>(null)
  const addSensors = useCallback(
    (fresh: FreshSensor[]) => {
      setSensorPicking(null)
      if (!layout || fresh.length === 0) return
      const sample = { ...fresh[0], id: 'new', x: 0, y: 0 } as HomeElement
      const spots = sensorSpots(layout.elements, fresh.length, { width: widthOf(sample), height: heightOf(sample) })
      const added: HomeElement[] = []
      for (const [index, one] of fresh.entries()) added.push({ ...one, id: freshId([...layout.elements, ...added]), ...spots[index] } as HomeElement)
      askAgain.current = true
      save({ ...layout, elements: [...layout.elements, ...added] }, 0)
    },
    [layout, save],
  )
  const addHints = useCallback(() => {
    if (!layout) return
    save({ ...layout, elements: [...layout.elements, { id: freshId(layout.elements), type: 'hints', ...nextSpot(layout.elements), title: '', checks: ['heating', 'humid'] }] }, 0)
  }, [layout, save])
  const sensorCard = elements.find((element) => (element.type === 'contacts' || element.type === 'readings') && element.id === sensorPicking?.card) ?? null

  // -- shutters and blinds ------------------------------------------------------

  /** The cover picker: null closed, 'new' to add, or the id of the card whose covers change. */
  const [coverPicking, setCoverPicking] = useState<string | null>(null)
  const coverCard = elements.find((element): element is HomeCovers => element.type === 'covers' && element.id === coverPicking) ?? null
  const addCovers = useCallback(
    (fresh: FreshCover[]) => {
      setCoverPicking(null)
      if (!layout || fresh.length === 0) return
      const sample = { ...fresh[0], id: 'new', x: 0, y: 0 } as HomeElement
      const spots = sensorSpots(layout.elements, fresh.length, { width: widthOf(sample), height: heightOf(sample) })
      const added: HomeElement[] = []
      for (const [index, one] of fresh.entries()) added.push({ ...one, id: freshId([...layout.elements, ...added]), ...spots[index] } as HomeElement)
      askAgain.current = true
      save({ ...layout, elements: [...layout.elements, ...added] }, 0)
    },
    [layout, save],
  )
  /** Positions asked of covers and not yet answered, by entity id: shown at once, as a lamp shows a wish. */
  const [coverAims, setCoverAims] = useState<Record<string, number>>({})
  const aimCover = useCallback((entity: string, position: number | undefined) => {
    setCoverAims((now) => {
      const rest = { ...now }
      if (position === undefined) delete rest[entity]
      else rest[entity] = position
      return rest
    })
  }, [])
  const [coverDetails, setCoverDetails] = useState<{ element: string; entity: string } | null>(null)
  const tellCover = useCallback(
    async (element: HomeCover | HomeCovers, wish: CoverWish) => {
      const targets = element.type === 'cover' ? [element.entity_id] : wish.member ? [wish.member] : element.sensors.map((one) => one.entity_id)
      const scene = 'scene' in wish && element.type === 'covers' ? element.scenes?.[wish.scene]?.position : undefined
      const going = 'position' in wish ? wish.position : 'action' in wish && wish.action !== 'stop' ? (wish.action === 'open' ? 100 : 0) : scene
      if (going !== undefined) for (const entity of targets) aimCover(entity, going)
      try {
        const answered = await post<CoverAnswer>(`/pages/${pageId}/home/covers/${element.id}`, wish)
        queryClient.setQueryData<HomeAnswer>(['home', pageId], (old) => (old ? withCovers(old, answered.covers) : old))
        if (answered.refused.length) {
          const first = answered.refused[0]
          setNote({ text: t(`homePage.covers.problems.${first.code}`, { defaultValue: first.message }), level: 'error' })
        }
      } catch (failure) {
        const code = failure instanceof ApiError ? failure.code : ''
        setNote({ text: t(`homePage.covers.problems.${code}`, { defaultValue: failure instanceof ApiError ? failure.message : t('homePage.covers.failed') }), level: 'error' })
      } finally {
        // A real cover takes its time: the stream tells where it goes from here.
        window.setTimeout(() => targets.forEach((entity) => aimCover(entity, undefined)), going !== undefined ? SETTLE_MS : 0)
      }
    },
    [aimCover, pageId, queryClient, t],
  )
  const coverStates = answer.data?.covers ?? {}

  // -- scenes, scripts and switches ---------------------------------------------

  const [actionPicking, setActionPicking] = useState<{ mode: 'scenes' | 'switches'; card: string | null } | null>(null)
  const actionCard = elements.find((element): element is HomeScenes | HomeSwitches => (element.type === 'scenes' || element.type === 'switches') && element.id === actionPicking?.card) ?? null
  const addActions = useCallback(
    (fresh: FreshAction[]) => {
      setActionPicking(null)
      if (!layout || fresh.length === 0) return
      const sample = { ...fresh[0], id: 'new', x: 0, y: 0 } as HomeElement
      const spots = sensorSpots(layout.elements, fresh.length, { width: widthOf(sample), height: heightOf(sample) })
      const added: HomeElement[] = []
      for (const [index, one] of fresh.entries()) added.push({ ...one, id: freshId([...layout.elements, ...added]), ...spots[index] } as HomeElement)
      askAgain.current = true
      save({ ...layout, elements: [...layout.elements, ...added] }, 0)
    },
    [layout, save],
  )
  /** On or off asked of switches and not yet answered, by entity id: "switching …" meanwhile. */
  const [switchWanted, setSwitchWanted] = useState<Record<string, boolean>>({})
  const tellAction = useCallback(
    async (element: HomeScene | HomeScenes | HomeSwitch | HomeSwitches, body: { on?: boolean; member?: string; stop?: boolean }) => {
      const switching = element.type === 'switch' || element.type === 'switches'
      const targets = element.type === 'scene' || element.type === 'switch' ? [element.entity_id] : body.member ? [body.member] : element.sensors.map((one) => one.entity_id)
      if (switching && body.on !== undefined) setSwitchWanted((now) => ({ ...now, ...Object.fromEntries(targets.map((entity) => [entity, body.on as boolean])) }))
      try {
        const answered = await post<ActionAnswer>(`/pages/${pageId}/home/${switching ? 'switches' : 'scenes'}/${element.id}`, body)
        queryClient.setQueryData<HomeAnswer>(['home', pageId], (old) => (old ? withActions(old, answered.actions) : old))
        if (answered.refused.length) {
          const first = answered.refused[0]
          setNote({ text: t(`homePage.switches.problems.${first.code}`, { defaultValue: first.message }), level: 'error' })
        }
      } catch (failure) {
        const code = failure instanceof ApiError ? failure.code : ''
        setNote({ text: t(`homePage.switches.problems.${code}`, { defaultValue: failure instanceof ApiError ? failure.message : t('homePage.switches.failed') }), level: 'error' })
      } finally {
        if (switching) {
          setSwitchWanted((now) => {
            const rest = { ...now }
            for (const entity of targets) delete rest[entity]
            return rest
          })
        }
      }
    },
    [pageId, queryClient, t],
  )
  const actionStates = answer.data?.actions ?? {}
  const detailedCoverElement = elements.find((element): element is HomeCover | HomeCovers => (element.type === 'cover' || element.type === 'covers') && element.id === coverDetails?.element) ?? null
  const said = answer.data?.sensors ?? {}

  const addHeading = useCallback(() => {
    if (!layout) return
    const id = freshId(layout.elements)
    save({ ...layout, elements: [...layout.elements, { id, type: 'heading', ...nextSpot(layout.elements), text: t('homePage.newHeading') }] }, 0)
    setRenaming(id)
  }, [layout, save, t])

  // -- moving an element, by the pointer --------------------------------------

  const [guidesOn, setGuidesOn] = useGuides()
  const surface = useRef<HTMLDivElement>(null)
  const pageBox = useRef<HTMLDivElement>(null)
  // Not before the page is drawn: while it loads, there is nothing to watch yet.
  useMenusInView(pageBox, arranging && Boolean(layout))
  const [dragged, setDragged] = useState<{ id: string; x: number; y: number; width?: number; height?: number; scale?: number } | null>(null)
  // Not while an element is dragged: it is placed anew once it is let go.
  useToolsOutside(surface, arranging && !dragged ? layout?.elements ?? null : null)
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
    const resizing = Boolean(target.closest('[data-resize]')) && (isResizable(element) || element.type === 'stat' || isScalable(element))
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
      if (element && isScalable(element)) {
        // A drawing grows and shrinks as a whole, by the farther of the two ways the corner is dragged.
        const scale = scaleTo(scaleOf(element), held.own.width, Math.abs(dx) > Math.abs(dy) ? dx : dy * (held.own.width / (held.own.height || 1)))
        setDragged({ id: held.id, x: held.fromX, y: held.fromY, scale })
        setGuides([])
        return
      }
      if (element?.type === 'stat') {
        // A card is dragged at its corner: width and height, on the step, inside their bounds; its right edge lines up with others.
        const from = statSize(element)
        const sized = guidesOn ? resizeTo({ ...held.own, width: from.width }, from.width + dx, held.others) : { width: snap(from.width + dx), guides: [] }
        const width = Math.min(STAT_WIDTHS[1], Math.max(STAT_WIDTHS[0], Math.round(sized.width)))
        const height = Math.min(STAT_HEIGHTS[1], Math.max(STAT_HEIGHTS[0], snap(from.height + dy)))
        setDragged({ id: held.id, x: held.fromX, y: held.fromY, width, height })
        setGuides(width === Math.round(sized.width) ? sized.guides : [])
        return
      }
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
      change(held.id, held.resizing && dragged.scale !== undefined ? { scale: dragged.scale }
        : held.resizing && dragged.width !== undefined ? { width: dragged.width, ...(dragged.height !== undefined ? { height: dragged.height } : {}) } : { x: dragged.x, y: dragged.y })
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
    dragged && dragged.id === element.id
      ? { ...element, x: dragged.x, y: dragged.y, ...(dragged.width !== undefined && element.type !== 'heading' ? { width: dragged.width } : {}),
          ...(dragged.height !== undefined && element.type === 'stat' ? { height: dragged.height } : {}),
          ...(dragged.scale !== undefined && isScalable(element) ? { scale: dragged.scale } : {}) }
      : element
  /** What the surface of an element is, so its glass and its tilt are made again when its style changes. */
  const lookOf = (element: HomeElement) => `${element.type}:${'style' in element ? element.style : ''}:${narrow ? 'phone' : 'surface'}`
  const sized = (element: HomeElement) => ({ arranging, wide: narrow && element.type !== 'heading' && isWide(element), width: controlWidth(element), onRemove: () => remove(element.id) })
  const actionHaName = (element: HomeScene | HomeSwitch) => {
    const said = actionStates[element.entity_id]
    return said && !said.missing && said.name ? said.name : element.name
  }
  const draw = (element: HomeElement) =>
    element.type === 'scene' ? (
      <SceneControl element={element} said={actionStates[element.entity_id]} {...sized(element)} onSetOff={canAct ? (stop) => void tellAction(element, stop ? { stop: true } : {}) : null}
        onStyle={(style) => change(element.id, { style })} onColour={(colour) => change(element.id, { colour })} haName={actionHaName(element)} onLabel={(label) => change(element.id, { label })} />
    ) : element.type === 'scenes' ? (
      <ScenesCard element={element} actions={actionStates} {...sized(element)} onSetOff={canAct ? (member) => void tellAction(element, { member }) : null}
        onStyle={(style) => change(element.id, { style })} onSensors={() => setActionPicking({ mode: 'scenes', card: element.id })} onTitle={(title) => change(element.id, { title })} />
    ) : element.type === 'switch' ? (
      <SwitchControl element={element} said={actionStates[element.entity_id]} wanted={switchWanted[element.entity_id]} {...sized(element)} pageId={pageId}
        onSwitch={canAct ? (on) => void tellAction(element, { on }) : null} onStyle={(style) => change(element.id, { style })} onConfirm={(confirm) => change(element.id, { confirm })}
        haName={actionHaName(element)} onLabel={(label) => change(element.id, { label })} />
    ) : element.type === 'switches' ? (
      <SwitchesCard element={element} actions={actionStates} wanted={switchWanted} {...sized(element)} pageId={pageId}
        onSwitch={canAct ? (on, member) => void tellAction(element, member ? { on, member } : { on }) : null} onConfirm={(confirm) => change(element.id, { confirm })}
        onSensors={() => setActionPicking({ mode: 'switches', card: element.id })} onTitle={(title) => change(element.id, { title })} />
    ) : element.type === 'cover' ? (
      <CoverControl element={element} said={coverStates[element.entity_id]} aim={coverAims[element.entity_id]} {...sized(element)}
        onWish={canAct ? (wish) => void tellCover(element, wish) : null} onAim={(position) => aimCover(element.entity_id, position)}
        onDetails={() => setCoverDetails({ element: element.id, entity: element.entity_id })} onStyle={(style) => change(element.id, { style })}
        haName={(() => { const said = coverStates[element.entity_id]; return said && !said.missing && said.name ? said.name : element.name })()}
        onLabel={(label) => change(element.id, { label })} />
    ) : element.type === 'covers' ? (
      <CoversCard element={element} covers={coverStates} aims={coverAims} {...sized(element)} onWish={canAct ? (wish) => void tellCover(element, wish) : null}
        onDetails={(entity) => setCoverDetails({ element: element.id, entity })}
        onStyle={(style) => change(element.id, { style, ...(style === 'scenes' && !element.scenes ? { scenes: defaultScenes(t) } : {}) })}
        onSensors={() => setCoverPicking(element.id)} onTitle={(title) => change(element.id, { title })} />
    ) : element.type === 'contact' ? (
      <ContactControl element={element} said={said[element.entity_id]} now={now} {...sized(element)} onStyle={(style) => change(element.id, { style })}
        onLabel={(label) => change(element.id, { label })} />
    ) : element.type === 'reading' ? (
      <ReadingControl element={element} temperatureSaid={element.temperature ? said[element.temperature.entity_id] : undefined}
        humiditySaid={element.humidity ? said[element.humidity.entity_id] : undefined} {...sized(element)} onStyle={(style) => change(element.id, { style })}
        onLabel={(name) => change(element.id, { name })} />
    ) : element.type === 'contacts' ? (
      <ContactsCard element={element} sensors={said} now={now} {...sized(element)} onStyle={(style) => change(element.id, { style })}
        onSensors={() => setSensorPicking({ mode: 'contacts', card: element.id })} onTitle={(title) => change(element.id, { title })} />
    ) : element.type === 'readings' ? (
      <ReadingsCard element={element} sensors={said} {...sized(element)} onSensors={() => setSensorPicking({ mode: 'readings', card: element.id })}
        onRows={(rows) => change(element.id, { rows })} onTitle={(title) => change(element.id, { title })} />
    ) : element.type === 'hints' ? (
      <HintsCard element={element} hints={pageHints(elements, answer.data, element.checks)} now={now} {...sized(element)} onChecks={(checks) => change(element.id, { checks })}
        onTitle={(title) => change(element.id, { title })} />
    ) : element.type === 'stat' ? (
      <StatCard element={element} pageId={pageId} arranging={arranging} wide={narrow && isWide(element)} size={statSize(element)}
        onRemove={() => remove(element.id)} onStyle={(style) => change(element.id, { style })} onSensors={() => setStatPicking(element.id)} onTitle={(title) => change(element.id, { title })} />
    ) : element.type === 'climate' ? (
      <ClimateControl element={element} info={climateOf(element)} missing={climateMissing(element)} arranging={arranging} wide={narrow} pageId={pageId} width={controlWidth(element)}
        target={targets[element.id] ?? climateOf(element)?.target ?? null} setting={targets[element.id] !== undefined}
        onStep={canAct ? (steps) => { const info = climateOf(element); if (info) stepClimate(element, info, steps) } : undefined}
        onAim={canAct ? (value, send) => { const info = climateOf(element); if (info) aimClimate(element, info, value, send ? 0 : null) } : undefined}
        onDetails={() => setClimateDetails(element.id)} onRemove={() => remove(element.id)} onSensor={(sensor) => chooseSensor(element, sensor)}
        onStyle={(style) => change(element.id, { style })} haName={climateFromHa(element)?.name || element.name} onLabel={(label) => change(element.id, { label })} />
    ) : element.type === 'light' ? (
      <LampControl element={element} info={standing(element)} missing={missing(element)} arranging={arranging} wide={narrow && isWide(element)} width={controlWidth(element)}
        onRemove={() => remove(element.id)} onStyle={(style) => change(element.id, { style })}
        onWish={canAct && !arranging ? (info, wish) => ask(element, info, wish) : undefined} onDetails={() => setDetails(element.id)}
        haName={infoOf(element)?.name || element.name} onLabel={(label) => change(element.id, { label })} />
    ) : (
      <HeadingView element={element} arranging={arranging} renaming={renaming === element.id}
        onRename={(text) => { change(element.id, { text }); setRenaming(null) }} onCancel={() => setRenaming(null)}
        onStartRename={() => setRenaming(element.id)} onRemove={() => remove(element.id)} />
    )

  return (
    <div ref={pageBox} className="max-w-[1600px] mx-auto px-3 sm:px-4 pt-4" data-home-page>
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
              <button type="button" className="btn" onClick={() => setStatPicking('new')}>
                <ChartLine size={15} /> {t('homePage.stats.add')}
              </button>
              <button type="button" className="btn" onClick={() => setActionPicking({ mode: 'scenes', card: null })}>
                <Sparkles size={15} /> {t('homePage.scenes.add')}
              </button>
              <button type="button" className="btn" onClick={() => setActionPicking({ mode: 'switches', card: null })}>
                <ToggleRight size={15} /> {t('homePage.switches.add')}
              </button>
              <button type="button" className="btn" onClick={() => setCoverPicking('new')}>
                <Blinds size={15} /> {t('homePage.covers.add')}
              </button>
              <button type="button" className="btn" onClick={() => setSensorPicking({ mode: 'contacts', card: null })}>
                <DoorOpen size={15} /> {t('homePage.sensors.addContacts')}
              </button>
              <button type="button" className="btn" onClick={() => setSensorPicking({ mode: 'readings', card: null })}>
                <Droplets size={15} /> {t('homePage.sensors.addReadings')}
              </button>
              <button type="button" className="btn" onClick={addHeading}>
                <Heading size={15} /> {t('homePage.addHeading')}
              </button>
            </div>
          )}
        </div>
      ) : narrow ? (
        // Each heading with the lamps that stand under it on the surface (``phoneGroups``).
        <div className="grid grid-cols-[minmax(0,1fr)] gap-5 pb-6">
          {phoneGroups(elements).map((group) => (
            <section key={group.heading?.id ?? 'top'} className="grid grid-cols-[minmax(0,1fr)] gap-3" data-phone-group={group.heading?.id ?? ''}>
              {group.heading && draw(group.heading)}
              {group.devices.length > 0 && (
                <div className="flex flex-wrap items-start gap-3">
                  {group.devices.map((device) => (
                    // ``min-w-0``: a chart drawn at the card's own width must not push the card past the screen.
                    <div key={device.id} className={isWide(device) ? 'w-full min-w-0' : ''}><Scaled element={device}><Felt arranging={arranging} look={lookOf(device)}>{draw(device)}</Felt></Scaled></div>
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
          data-arranging={arranging ? '' : undefined}
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
                <Scaled element={element}><Felt arranging={arranging} look={lookOf(element)}>{draw(element)}</Felt></Scaled>
                {arranging && isScalable(element) && <span className="home-grip home-grip-corner" data-resize="scale" aria-hidden title={t('homePage.stats.dragSize')} />}
              </div>
            )
          })}
        </div>
      )}
      {arranging && <EditBar onLight={() => setPicking(true)} onClimate={() => setPickingClimates(true)} onStat={() => setStatPicking('new')} onCover={() => setCoverPicking('new')}
        onScene={() => setActionPicking({ mode: 'scenes', card: null })} onSwitch={() => setActionPicking({ mode: 'switches', card: null })}
        onSensor={(kind) => (kind === 'hints' ? addHints() : setSensorPicking({ mode: kind, card: null }))} onHeading={addHeading} guides={guidesOn} onGuides={() => setGuidesOn(!guidesOn)}
        onAddPage={onAddPage} onSettings={onSettings} onDone={onDone} />}
      {detailed && detailedInfo && canAct && (
        <LampDetails info={detailedInfo} onWish={(wish) => ask(detailed, detailedInfo, wish)} onClose={() => setDetails(null)} />
      )}
      {detailedClimate && detailedClimateInfo && (
        <ClimateDetails info={detailedClimateInfo} target={targets[detailedClimate.id] ?? detailedClimateInfo.target} setting={targets[detailedClimate.id] !== undefined}
          onStep={canAct ? (steps) => stepClimate(detailedClimate, detailedClimateInfo, steps) : null}
          onSlide={canAct ? (value) => aimClimate(detailedClimate, detailedClimateInfo, value, GATHER_MS) : null}
          onWish={canAct ? (wish) => tell(detailedClimate.id, detailedClimateInfo.name, wish) : null}
          onClose={() => setClimateDetails(null)} history={{ pageId, elementId: detailedClimate.id }} />
      )}
      {detailedCoverElement && coverDetails && (
        <CoverDetails name={(() => {
          const said = coverStates[coverDetails.entity]
          const own = detailedCoverElement.type === 'cover' ? detailedCoverElement.label : ''
          return own || (said && !said.missing && said.name) || coverDetails.entity
        })()} said={coverStates[coverDetails.entity]} aim={coverAims[coverDetails.entity]}
          onWish={canAct ? (wish) => void tellCover(detailedCoverElement, detailedCoverElement.type === 'covers' ? { ...wish, member: coverDetails.entity } : wish) : null}
          onClose={() => setCoverDetails(null)} />
      )}
      {canEdit && <ActionPicker mode={actionPicking?.mode ?? null} pageId={pageId} card={actionCard} onClose={() => setActionPicking(null)} onAdd={addActions}
        onChange={(id, patch) => { setActionPicking(null); askAgain.current = true; change(id, patch) }} />}
      {canEdit && <CoverPicker open={coverPicking !== null} pageId={pageId} card={coverCard} onClose={() => setCoverPicking(null)} onAdd={addCovers}
        onChange={(id, patch) => { setCoverPicking(null); askAgain.current = true; change(id, patch) }} />}
      {canEdit && (
        <SensorPicker mode={sensorPicking?.mode ?? null} pageId={pageId} card={sensorCard as Parameters<typeof SensorPicker>[0]['card']} onClose={() => setSensorPicking(null)} onAdd={addSensors}
          onChange={(id, patch) => { setSensorPicking(null); askAgain.current = true; change(id, patch) }} />
      )}
      {canEdit && <StatPicker open={statPicking !== null} pageId={pageId} card={statCard} onClose={() => setStatPicking(null)} onAdd={addStats}
        onChange={(id, patch) => { setStatPicking(null); change(id, patch) }} />}
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
function LampControl({ element, info, missing, arranging, wide, width, onRemove, onStyle, onWish, onDetails, haName, onLabel }: {
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
  /** Home Assistant's name, for the pencil's field. */
  haName: string
  onLabel: (label: string) => void
}) {
  const { t } = useTranslation()
  const name = element.label || info?.name || element.name || element.entity_id
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
        <span className="home-tools" data-element-tool>
          <button type="button" className="btn btn-icon h-6 w-6 rounded-full glass-strong" onClick={() => setChoosing((open) => !open)}
            aria-label={t('homePage.chooseStyle')} title={t('homePage.chooseStyle')} aria-haspopup="menu" aria-expanded={choosing}>
            <Palette size={12} />
          </button>
          <Rename label={element.label ?? ''} fallback={haName} onLabel={onLabel} />
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

function EditBar(props: { onLight: () => void; onClimate: () => void; onStat: () => void; onCover: () => void; onScene: () => void; onSwitch: () => void; onSensor: (kind: 'contacts' | 'readings' | 'hints') => void; onHeading: () => void; guides: boolean; onGuides: () => void; onAddPage: () => void; onSettings: () => void; onDone: () => void }) {
  const { t } = useTranslation()
  return (
    // Two bars side by side: what goes onto the page, and the page and the board themselves.
    // As wide as the window, so the two wrap onto two rows where side by side they do not fit; clicks go through between them.
    <div className="fixed bottom-20 md:bottom-6 inset-x-2 z-40 flex flex-wrap items-center justify-center gap-2 pointer-events-none" data-no-picture data-edit-bar>
      <div className="glass-strong rounded-full px-2 py-1.5 flex items-center gap-1 shadow-2xl pointer-events-auto" role="toolbar" aria-label={t('homePage.barAdd')} data-bar="add">
      <button type="button" className="btn btn-flat whitespace-nowrap" onClick={props.onLight} aria-label={t('homePage.addLight')}>
        <Lightbulb size={15} /> <span className="hidden sm:inline">{t('homePage.addLight')}</span>
      </button>
      <button type="button" className="btn btn-flat whitespace-nowrap" onClick={props.onClimate} aria-label={t('homePage.addClimate')}>
        <Thermometer size={15} /> <span className="hidden sm:inline">{t('homePage.addClimate')}</span>
      </button>
      <button type="button" className="btn btn-flat whitespace-nowrap" onClick={props.onStat} aria-label={t('homePage.stats.add')}>
        <ChartLine size={15} /> <span className="hidden sm:inline">{t('homePage.stats.add')}</span>
      </button>
      <button type="button" className="btn btn-flat whitespace-nowrap" onClick={props.onCover} aria-label={t('homePage.covers.add')}>
        <Blinds size={15} /> <span className="hidden xl:inline">{t('homePage.covers.add')}</span>
      </button>
      <button type="button" className="btn btn-flat whitespace-nowrap" onClick={props.onScene} aria-label={t('homePage.scenes.add')}>
        <Sparkles size={15} /> <span className="hidden xl:inline">{t('homePage.scenes.add')}</span>
      </button>
      <button type="button" className="btn btn-flat whitespace-nowrap" onClick={props.onSwitch} aria-label={t('homePage.switches.add')}>
        <ToggleRight size={15} /> <span className="hidden xl:inline">{t('homePage.switches.add')}</span>
      </button>
      <SensorMenu onSensor={props.onSensor} />
      <button type="button" className="btn btn-flat whitespace-nowrap" onClick={props.onHeading} aria-label={t('homePage.addHeading')}>
        <Heading size={15} /> <span className="hidden sm:inline">{t('homePage.addHeading')}</span>
      </button>
      </div>
      <div className="glass-strong rounded-full px-2 py-1.5 flex items-center gap-1 shadow-2xl pointer-events-auto" role="toolbar" aria-label={t('homePage.barBoard')} data-bar="board">
      <button type="button" className={`btn btn-flat whitespace-nowrap ${props.guides ? 'text-accent' : ''}`} onClick={props.onGuides} aria-pressed={props.guides}
        aria-label={t('homePage.guides')} title={t('homePage.guidesHelp')}>
        <Grid3x3 size={15} /> <span className="hidden xl:inline">{t('homePage.guides')}</span>
      </button>
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
    </div>
  )
}

/** The bar's sensor button: doors and windows, temperature and humidity, or a hints card. */
function SensorMenu({ onSensor }: { onSensor: (kind: 'contacts' | 'readings' | 'hints') => void }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const pick = (kind: 'contacts' | 'readings' | 'hints') => {
    setOpen(false)
    onSensor(kind)
  }
  return (
    <span className="relative">
      <button type="button" className={`btn btn-flat whitespace-nowrap ${open ? 'text-accent' : ''}`} onClick={() => setOpen((now) => !now)} aria-label={t('homePage.sensors.add')}
        aria-haspopup="menu" aria-expanded={open}>
        <Radar size={15} /> <span className="hidden sm:inline">{t('homePage.sensors.add')}</span>
      </button>
      {open && (
        <span className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 glass-strong rounded-xl p-1.5 shadow-2xl grid gap-0.5 w-56" role="menu" aria-label={t('homePage.sensors.add')}>
          <button type="button" role="menuitem" className="flex items-center gap-2 text-left text-[13px] px-2.5 py-1.5 rounded-lg hover:bg-[var(--nd-surface-hover)]" onClick={() => pick('contacts')}>
            <DoorOpen size={14} /> {t('homePage.sensors.addContacts')}
          </button>
          <button type="button" role="menuitem" className="flex items-center gap-2 text-left text-[13px] px-2.5 py-1.5 rounded-lg hover:bg-[var(--nd-surface-hover)]" onClick={() => pick('readings')}>
            <Droplets size={14} /> {t('homePage.sensors.addReadings')}
          </button>
          <button type="button" role="menuitem" className="flex items-center gap-2 text-left text-[13px] px-2.5 py-1.5 rounded-lg hover:bg-[var(--nd-surface-hover)]" onClick={() => pick('hints')}>
            <MessageSquareWarning size={14} /> {t('homePage.sensors.addHints')}
          </button>
        </span>
      )}
    </span>
  )
}

/**
 * A drawn element at its own size: zoomed as a whole, so its footprint on the
 * surface grows with it and the guides measure what the eye sees. Its tools
 * keep their size (``[data-scaled] [data-element-tool]`` in app.css).
 */
function Scaled({ element, children }: { element: HomeElement; children: ReactNode }) {
  const scale = scaleOf(element)
  if (scale === 1) return <>{children}</>
  return <div style={{ zoom: scale, '--home-scale': scale } as CSSProperties} data-scaled={scale}>{children}</div>
}

/** The menus and fields that open beside an element while arranging: its style, its sensor, its colour, its name. */
export const MENUS = '[role="menu"], [data-rename]'
/** Room kept above a menu turned upwards, for the bar at the top of the page. */
const TOP_ROOM = 56

/**
 * Every menu of an element opens where it can be read: below the element,
 * and above it where below it would run under the bar at the foot of the
 * screen or out of the window; always over the bar.
 *
 * ⚠️ Without it the style menu of a cover near the foot of the page opened
 * under the bar and could not be chosen from (seen 20.10.2026). One place
 * for all of them rather than each menu on its own: there are a dozen.
 */
export function useMenusInView(box: React.RefObject<HTMLElement | null>, active: boolean) {
  useEffect(() => {
    const root = box.current
    if (!root || !active || typeof MutationObserver === 'undefined') return
    const place = (menu: HTMLElement) => {
      menu.style.zIndex = '45'
      const rect = menu.getBoundingClientRect()
      if (!rect.height) return
      const bar = document.querySelector('[data-edit-bar]')?.getBoundingClientRect()
      const floor = Math.min(window.innerHeight, bar && bar.height ? bar.top : window.innerHeight) - 8
      const anchor = (menu.offsetParent as HTMLElement | null)?.getBoundingClientRect()
      const upTop = (anchor?.top ?? rect.top) - rect.height - 8
      if (rect.bottom > floor && upTop >= TOP_ROOM) {
        menu.style.top = 'auto'
        menu.style.bottom = '100%'
        menu.style.marginTop = '0'
        menu.style.marginBottom = '8px'
        menu.dataset.up = ''
      }
    }
    const watch = new MutationObserver((records) => {
      for (const record of records) {
        for (const node of record.addedNodes) {
          if (!(node instanceof HTMLElement)) continue
          if (node.matches(MENUS)) place(node)
          node.querySelectorAll<HTMLElement>(MENUS).forEach(place)
        }
      }
    })
    watch.observe(root, { childList: true, subtree: true })
    return () => watch.disconnect()
  }, [box, active])
}

/** Where the tools of an element can stand, in the order they are tried: above its corner first. */
export const TOOL_SIDES = ['above', 'corner', 'right', 'below', 'left'] as const
export type ToolSide = (typeof TOOL_SIDES)[number]
type Rect = { left: number; top: number; right: number; bottom: number }

function overlap(a: Rect, b: Rect): number {
  const width = Math.min(a.right, b.right) - Math.max(a.left, b.left)
  const height = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)
  return width > 0 && height > 0 ? width * height : 0
}

/**
 * The first side where the tools cover nothing (no element, no tools already
 * placed, nothing outside the page); where every side covers something, the
 * one that covers least.
 */
export function pickToolSide(candidates: Record<ToolSide, Rect>, obstacles: Rect[], bounds: Rect): ToolSide {
  let best: ToolSide = TOOL_SIDES[0]
  let least = Infinity
  for (const side of TOOL_SIDES) {
    const box = candidates[side]
    const outside = (box.right - box.left) * (box.bottom - box.top) - overlap(box, bounds)
    const covered = outside + obstacles.reduce((sum, other) => sum + overlap(box, other), 0)
    if (covered === 0) return side
    if (covered < least) {
      least = covered
      best = side
    }
  }
  return best
}

/**
 * The style, name and remove buttons of an element stand outside its drawing,
 * where they cover neither it nor the elements beside it: each side is tried
 * on the page and measured, so zoomed drawings and nested cards need no sums.
 *
 * ⚠️ On the drawing itself they hid what a small one shows, a tile's "off"
 * among them (seen 20.10.2026). Plainly above every element would not do:
 * pills stacked closely would get them over the pill above.
 */
export function useToolsOutside(box: React.RefObject<HTMLElement | null>, elements: unknown) {
  useEffect(() => {
    const root = box.current
    if (!root || !elements) return
    let frame = 0
    const place = () => {
      frame = 0
      const bounds = root.getBoundingClientRect()
      if (!bounds.width) return
      const holders = [...root.querySelectorAll<HTMLElement>('[data-element]')]
      const obstacles: Rect[] = holders.map((holder) => holder.getBoundingClientRect())
      holders.forEach((holder, index) => {
        const tools = holder.querySelector<HTMLElement>('.home-tools')
        if (!tools) return
        const others = obstacles.filter((_, at) => at !== index)
        const candidates = {} as Record<ToolSide, Rect>
        for (const side of TOOL_SIDES) {
          holder.dataset.tools = side
          candidates[side] = tools.getBoundingClientRect()
        }
        const side = pickToolSide(candidates, others, { left: bounds.left, top: bounds.top - 8, right: bounds.right, bottom: bounds.bottom + 8 })
        holder.dataset.tools = side
        obstacles.push(candidates[side])
      })
    }
    const soon = () => {
      if (!frame) frame = requestAnimationFrame(place)
    }
    soon()
    // Drawings change size when their state arrives, a name gets longer, a style is chosen.
    const sizes = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(soon)
    root.querySelectorAll('[data-element]').forEach((holder) => sizes?.observe(holder))
    window.addEventListener('resize', soon)
    return () => {
      if (frame) cancelAnimationFrame(frame)
      sizes?.disconnect()
      window.removeEventListener('resize', soon)
    }
  }, [box, elements])
}
