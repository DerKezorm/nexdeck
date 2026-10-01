/**
 * Cards that hold other cards: the tabs card and the group. A holder keeps
 * the numbers of cards of its own page in `options.cards`; those cards leave
 * the grid and are drawn inside it. Their data keeps coming as it did, they
 * are only drawn somewhere else. Removing the holder brings them back.
 */
import { createContext, useContext } from 'react'
import { create } from 'zustand'

import type { Action, WidgetView } from './types'

export const GROUP_KINDS = new Set(['core.tabs', 'core.group'])

/** The numbers a holder keeps, as numbers, whatever came in. */
export function heldBy(widget: WidgetView): number[] {
  if (!GROUP_KINDS.has(widget.kind)) return []
  const cards = widget.options?.cards
  return Array.isArray(cards) ? cards.map(Number).filter((one) => Number.isInteger(one)) : []
}

/** Every card on a page that lives inside a holder, and so not on the grid. */
export function tucked(widgets: WidgetView[]): Set<number> {
  const present = new Set(widgets.map((widget) => widget.id))
  const inside = new Set<number>()
  for (const widget of widgets) for (const id of heldBy(widget)) if (present.has(id) && id !== widget.id) inside.add(id)
  return inside
}

/** The cards a holder shows, in its order, those that still exist and are not holders themselves. */
export function cardsOf(holder: WidgetView, widgets: WidgetView[]): WidgetView[] {
  const byId = new Map(widgets.map((widget) => [widget.id, widget]))
  return heldBy(holder)
    .map((id) => byId.get(id))
    .filter((widget): widget is WidgetView => Boolean(widget) && !GROUP_KINDS.has(widget!.kind) && widget!.id !== holder.id)
}

/** What a holder needs from the page it stands on: the other cards, and the way to act on them. */
export interface PageCards {
  widgets: WidgetView[]
  canAct?: boolean
  editing?: boolean
  onAction?: (widgetId: number, action: Action) => void
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
