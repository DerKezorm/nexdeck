import { memo, useCallback, useMemo, useState, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Responsive, WidthProvider, type Layout, type Layouts } from 'react-grid-layout'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'

import type { Action, Breakpoint, LayoutItem, WidgetData, WidgetView } from '../lib/types'
import { WidgetCard } from './WidgetCard'

const ResponsiveGrid = WidthProvider(Responsive)

/**
 * Two screens and one arrangement.
 *
 * ⚠️ There used to be three layouts, one per screen size, each saved on its
 * own. The tablet's and the phone's were written once, when a card was added,
 * and never again: arranging the board on a monitor left both where they
 * were. Measured on 10.09.2026 on a board of 25 cards: on the phone 6 stood
 * where they stood on the monitor, one was 15 places off, and 19 were half the
 * width of the screen, lists included. Nobody arranges a board three times.
 *
 * So from 700 pixels up the board is the arrangement itself, only narrower or
 * wider, and a wall tablet shows what was arranged at the desk. Below that the
 * same arrangement is stacked, see `stackedFor`. The `md` and `sm` layouts the
 * server still keeps are not read.
 */
export const BREAKPOINTS = { lg: 700, sm: 0 }
export const COLUMNS = { lg: 12, sm: 4 }
type Screen = keyof typeof COLUMNS
export const ROW_HEIGHT = 68
export const GAP = 12

interface Props {
  widgets: WidgetView[]
  layouts: Record<Breakpoint, LayoutItem[]>
  data: Record<number, WidgetData | undefined>
  series?: Record<number, Record<string, number[]>>
  editing?: boolean
  canAct?: boolean
  onLayoutChange?: (breakpoint: Breakpoint, layout: LayoutItem[]) => void
  onAction?: (widgetId: number, action: Action) => void
  onRefresh?: (widgetId: number) => void
  onSettings?: (widgetId: number) => void
  onRemove?: (widgetId: number) => void
  compact?: boolean
  /** On, every card moves up to fill space. Off, cards stay where they are dropped and gaps are allowed. */
  autoCompact?: boolean
}

/** One press of an arrow key: one cell, or one cell of size with Shift. */
function moved(item: LayoutItem, key: string, resize: boolean, cols: number, floor: [number, number]): LayoutItem | null {
  const step: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }
  const move = step[key]
  if (!move) return null
  const [dx, dy] = move
  if (resize) {
    const w = Math.min(cols, Math.max(floor[0], item.w + dx))
    const h = Math.max(floor[1], item.h + dy)
    return w === item.w && h === item.h ? null : { ...item, w, h }
  }
  const x = Math.max(0, Math.min(cols - item.w, item.x + dx))
  const y = Math.max(0, item.y + dy)
  return x === item.x && y === item.y ? null : { ...item, x, y }
}

/** What is saved of a card's place: position and size, nothing the grid adds. */
function plain({ i, x, y, w, h }: Layout | LayoutItem): LayoutItem {
  return { i, x, y, w, h }
}

/** The board: one arrangement, drawn as it is on a wide screen and stacked on a narrow one. */
export function BoardGrid(props: Props) {
  const { widgets, layouts, data, series, editing, canAct, onLayoutChange, onAction, onRefresh, onSettings, onRemove, compact, autoCompact } = props
  const { t } = useTranslation()
  // The grid draws at the width WidthProvider assumes before it has measured,
  // which is a wide one; a phone reports itself right after.
  const [screen, setScreen] = useState<Screen>('lg')
  // ⚠️ Rebuilt only when the arrangement or the cards change. Without the memo
  // this ran on every widget tick, once or twice a second on a board of
  // thirty, and handed react-grid-layout a new object identity each time.
  const wide = useMemo(() => layoutFor(layouts.lg, widgets, COLUMNS.lg), [layouts.lg, widgets])
  const gridLayouts: Layouts = useMemo(() => ({ lg: wide, sm: stackedFor(wide, COLUMNS.sm) }), [wide])
  /**
   * Move or resize the focused card with the arrow keys.
   *
   * Always in the wide arrangement, since it is the only one; on a phone the
   * stack follows it.
   */
  const nudge = (event: KeyboardEvent<HTMLDivElement>, widget: WidgetView) => {
    if (!onLayoutChange || event.altKey || event.ctrlKey || event.metaKey) return
    if (!event.key.startsWith('Arrow')) return
    // Only when the card itself has the focus, not something inside it.
    if (event.target !== event.currentTarget) return
    event.preventDefault()
    const item = wide.find((one) => one.i === String(widget.id))
    if (!item) return
    const next = moved(item as LayoutItem, event.key, event.shiftKey, COLUMNS.lg, floorOf(widget, COLUMNS.lg))
    if (!next) return
    onLayoutChange('lg', wide.map((one) => plain(one.i === next.i ? next : one)))
  }

  return (
    <>
      {/* On a phone a card cannot be dragged, so edit mode says where it can. */}
      {editing && screen === 'sm' && (
        <p role="note" className="text-xs text-muted px-1 pb-3">
          {t('board.stackedHint')}
        </p>
      )}
      <ResponsiveGrid
        className={`board ${editing ? 'board-editing' : ''}`}
        layouts={gridLayouts}
        breakpoints={BREAKPOINTS}
        cols={COLUMNS}
        rowHeight={compact ? 60 : ROW_HEIGHT}
        margin={[GAP, GAP]}
        containerPadding={[0, 0]}
        isDraggable={Boolean(editing)}
        isResizable={Boolean(editing)}
        // A press on a button or link must not start a drag: the drag machinery
        // swallows the click, and the settings button on a card did nothing.
        //
        // ⚠️ While editing, only the card's own two buttons are left out. A card
        // whose body is a link or a row of buttons had almost no surface to take
        // hold of: on a monitor card the strip of bars filled it, and what was
        // left to drag was the two millimetres of padding at the edge. Nothing
        // in the body does anything in edit mode anyway; the stylesheet takes
        // its pointer events away, which is what makes this safe.
        draggableCancel={editing ? '.card-controls' : "button, a, input, select, textarea, [role='button'], .no-drag"}
        compactType={autoCompact ? 'vertical' : null}
        // Without compaction, other cards must never move on their own: a card
        // dragged across the board used to push everything aside, and nothing
        // came back. Occupied cells are simply not a drop target.
        preventCollision={!autoCompact}
        useCSSTransforms
        onBreakpointChange={(next: string) => setScreen(next === 'sm' ? 'sm' : 'lg')}
        onLayoutChange={(_current: Layout[], all: Layouts) => {
          if (!onLayoutChange || !editing) return
          // Only the wide arrangement is kept. When it is still what the board
          // handed in, the change was in the stack, which is worked out from
          // it and never saved.
          const changed = all.lg
          if (!changed || sameArrangement(changed, wide)) return
          onLayoutChange('lg', changed.map(plain))
        }}
      >
        {widgets.map((widget) => (
          <div
            key={String(widget.id)}
            // ⚠️ The keyboard way round the grid. react-grid-layout 1.5.2 listens
            // to pointer and touch events and nothing else, so a board could be
            // arranged with a mouse and by no other means: not by keyboard, not
            // by a switch, not by voice control that drives the keyboard. The
            // grid itself never learns about this; the layout is ours to change,
            // and the same save path runs as after a drag.
            tabIndex={editing ? 0 : undefined}
            role={editing ? 'application' : undefined}
            aria-label={editing ? t('board.moveWith', { name: widget.title || widget.kind }) : undefined}
            onKeyDown={editing ? (event) => nudge(event, widget) : undefined}
          >
            <GridCard
              widget={widget}
              data={data[widget.id]}
              series={series?.[widget.id]}
              editing={editing}
              canAct={canAct}
              onAction={onAction}
              onRefresh={onRefresh}
              onSettings={onSettings}
              onRemove={onRemove}
            />
          </div>
        ))}
      </ResponsiveGrid>
    </>
  )
}

interface CardProps {
  widget: WidgetView
  data: WidgetData | undefined
  series: Record<string, number[]> | undefined
  editing?: boolean
  canAct?: boolean
  onAction?: (widgetId: number, action: Action) => void
  onRefresh?: (widgetId: number) => void
  onSettings?: (widgetId: number) => void
  onRemove?: (widgetId: number) => void
}

/**
 * One card in the grid, drawn again only when its own data changed.
 *
 * ⚠️ Measured before this: thirty cards on a board, the data of **one** of
 * them arriving, thirty renders. The cause was two things at once, and fixing
 * either alone changes nothing. The card was not memoised, and every card was
 * handed four freshly made closures on every render, which would have defeated
 * the memo anyway. So the closures are made here, from props that are stable
 * for as long as the card is, and the wrapper is what the grid renders.
 */
const GridCard = memo(function GridCard({ widget, data, series, editing, canAct, onAction, onRefresh, onSettings, onRemove }: CardProps) {
  const act = useCallback((action: Action) => onAction?.(widget.id, action), [onAction, widget.id])
  const refresh = useCallback(() => onRefresh?.(widget.id), [onRefresh, widget.id])
  const settings = useCallback(() => onSettings?.(widget.id), [onSettings, widget.id])
  const remove = useCallback(() => onRemove?.(widget.id), [onRemove, widget.id])
  return (
    <WidgetCard
      widget={widget}
      data={data}
      series={series}
      editing={editing}
      canAct={canAct}
      onAction={onAction ? act : undefined}
      onRefresh={onRefresh && !editing && !widget.client_only ? refresh : undefined}
      onSettings={onSettings ? settings : undefined}
      onRemove={onRemove ? remove : undefined}
    />
  )
})

/**
 * The layout the grid draws: saved positions, a spot at the bottom for widgets
 * without one, and a floor under every size.
 *
 * ⚠️ The floor was the size a card was created with, from 2026-09-05, so that
 * a shrunken card could not cut its content. The side effect was that
 * ``min_size`` did nothing at all: every one of the 195 widgets declares one
 * smaller than its default, so the declared minimum was never reachable and a
 * search bar could not be made into a bar. Reversed 2026-09-06: the floor is
 * what the adapter says is still usable, which is what the field is for.
 */
export function layoutFor(layout: LayoutItem[] | undefined, widgets: WidgetView[], cols: number): Layout[] {
  const known = new Map((layout ?? []).map((item) => [item.i, item]))
  const result: Layout[] = []
  let y = Math.max(0, ...(layout ?? []).map((item) => item.y + item.h))
  let x = 0
  for (const widget of widgets) {
    const id = String(widget.id)
    const [minW, minH] = floorOf(widget, cols)
    const item = known.get(id)
    if (item) {
      result.push({ ...item, w: Math.max(item.w, minW), h: Math.max(item.h, minH), minW, minH })
      continue
    }
    const w = Math.min(cols, Math.max(3, minW))
    if (x + w > cols) {
      x = 0
      y += 2
    }
    result.push({ i: id, x, y, w, h: Math.max(2, minH), minW, minH })
    x += w
  }
  return result
}

/**
 * The phone's board: the wide arrangement read like a page, row by row and
 * left to right, one card under the next at the full width.
 *
 * Two cards that are small on the wide board, two columns of twelve or less,
 * share a row when they follow each other and are equally tall. Two columns of
 * twelve on a monitor are about as wide as half a phone, so what fits there
 * fits here; a list of three columns does not, and gets the width. A small
 * card without a partner of its height takes the whole row too, rather than
 * half of one with nothing beside it.
 *
 * Nothing in the stack can be dragged or resized. Its order is the wide
 * board's, and a drag here would have had nowhere to be kept.
 */
export function stackedFor(wide: Layout[], cols: number): Layout[] {
  const half = Math.floor(cols / 2)
  const ordered = [...wide].sort((a, b) => a.y - b.y || a.x - b.x)
  const tall = (item: Layout) => Math.max(item.h, item.minH ?? 1)
  const small = (item: Layout) => item.w <= 2
  const stacked: Layout[] = []
  let y = 0
  for (let index = 0; index < ordered.length; index += 1) {
    const card = ordered[index]
    const next = ordered[index + 1]
    const h = tall(card)
    if (next && small(card) && small(next) && tall(next) === h) {
      stacked.push({ i: card.i, x: 0, y, w: half, h, isDraggable: false, isResizable: false })
      stacked.push({ i: next.i, x: half, y, w: cols - half, h, isDraggable: false, isResizable: false })
      index += 1
    } else {
      stacked.push({ i: card.i, x: 0, y, w: cols, h, isDraggable: false, isResizable: false })
    }
    y += h
  }
  return stacked
}

/** Whether two layouts put every card in the same place at the same size. */
function sameArrangement(one: Layout[], other: Layout[]): boolean {
  if (one.length !== other.length) return false
  const spots = new Map(other.map((item) => [item.i, item]))
  return one.every((item) => {
    const spot = spots.get(item.i)
    return spot !== undefined && spot.x === item.x && spot.y === item.y && spot.w === item.w && spot.h === item.h
  })
}

/** The smallest the adapter says this card is still usable at. */
function floorOf(widget: WidgetView, cols: number): [number, number] {
  const [w, h] = widget.min_size ?? widget.default_size ?? [1, 1]
  return [Math.max(1, Math.min(cols, w)), Math.max(1, h)]
}
