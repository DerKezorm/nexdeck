/**
 * Cards that hold other cards: the tabs card, the group and key figures. A holder keeps
 * the numbers of cards of its own page in `options.cards`; those cards leave
 * the grid and are drawn inside it. Their data keeps coming as it did, they
 * are only drawn somewhere else. Removing the holder brings them back.
 */
import { createContext, useContext, type PointerEvent as ReactPointerEvent } from 'react'
import { create } from 'zustand'

import type { HeldSize } from './holding'
import type { Action, Pressed, WidgetView } from './types'

export const GROUP_KINDS = new Set(['core.tabs', 'core.group', 'core.figures'])

/** The numbers a holder keeps, as numbers, whatever came in. */
export function heldBy(widget: WidgetView): number[] {
  if (!GROUP_KINDS.has(widget.kind)) return []
  const cards = widget.options?.cards
  return Array.isArray(cards) ? cards.map(Number).filter((one) => Number.isInteger(one)) : []
}

/** Every card on a page that lives inside a holder or in the side bar, and so not on the grid. */
export function tucked(widgets: WidgetView[], side: number[] = []): Set<number> {
  const present = new Set(widgets.map((widget) => widget.id))
  const inside = new Set<number>()
  for (const widget of widgets) for (const id of heldBy(widget)) if (present.has(id) && id !== widget.id) inside.add(id)
  for (const id of side) if (present.has(id) && !GROUP_KINDS.has(widgets.find((widget) => widget.id === id)?.kind ?? '')) inside.add(id)
  return inside
}

/** The cards a holder shows, in its order, those that still exist and are not holders themselves. */
export function cardsOf(holder: WidgetView, widgets: WidgetView[]): WidgetView[] {
  const byId = new Map(widgets.map((widget) => [widget.id, widget]))
  return heldBy(holder)
    .map((id) => byId.get(id))
    .filter((widget): widget is WidgetView => Boolean(widget) && !GROUP_KINDS.has(widget!.kind) && widget!.id !== holder.id)
}

/**
 * What a held card needs while the board is arranged: the rows to draw on,
 * where a drag starts, and how a size is changed. Only while editing.
 */
export interface Holding {
  rowHeight: number
  gap: number
  /** The drop target the pointer is over during a drag: ``group:12``, ``side`` or ``board``. */
  over: string | null
  /** The card being dragged, which its holder draws faded. */
  dragging: number | null
  startDrag?: (event: ReactPointerEvent<HTMLElement>, widget: WidgetView) => void
  onHeldSize?: (widget: WidgetView, size: HeldSize) => void
  onSettings?: (widgetId: number) => void
  onRemove?: (widgetId: number) => void
  /** A new card straight into a holder: the library opens, and what is added lands there. */
  onAddInto?: (holderId: number) => void
}

/** What a holder needs from the page it stands on: the other cards, and the way to act on them. */
export interface PageCards {
  widgets: WidgetView[]
  canAct?: boolean
  editing?: boolean
  onAction?: (widgetId: number, action: Action) => Pressed
  /** The board's rows and gap, for a group that lays its cards out on rows of its own. */
  rowHeight?: number
  gap?: number
  holding?: Holding
}

export const PageCardsContext = createContext<PageCards>({ widgets: [] })

export function usePageCards(): PageCards {
  return useContext(PageCardsContext)
}

/** The cards of the page being edited, for the picker in a holder's settings. */
export const useEditedPage = create<{ widgets: WidgetView[]; setWidgets: (widgets: WidgetView[]) => void }>((set) => ({
  widgets: [],
  setWidgets: (widgets) => set({ widgets }),
}))

const FOLDED = 'nexdeck.folded'

function folded(): number[] {
  try {
    const value = JSON.parse(localStorage.getItem(FOLDED) ?? '[]') as unknown
    return Array.isArray(value) ? value.map(Number).filter((one) => Number.isInteger(one)) : []
  } catch {
    return []
  }
}

/**
 * Which groups this browser has folded away. A fold is somebody's view of
 * the board, not the board: it is kept here, never saved for everyone.
 */
export const useFolded = create<{ folded: number[]; toggle: (id: number) => void }>((set, get) => ({
  folded: folded(),
  toggle: (id) => {
    const next = get().folded.includes(id) ? get().folded.filter((one) => one !== id) : [...get().folded, id]
    set({ folded: next })
    try {
      localStorage.setItem(FOLDED, JSON.stringify(next))
    } catch {
      // Forgotten on the next load; the group opens again, which is the safe way round.
    }
  },
}))
