import { memo, useCallback, useMemo, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Responsive, WidthProvider, type Layout, type Layouts } from 'react-grid-layout'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'

import type { Action, Breakpoint, LayoutItem, WidgetData, WidgetView } from '../lib/types'
import { WidgetCard } from './WidgetCard'

const ResponsiveGrid = WidthProvider(Responsive)

export const BREAKPOINTS: Record<Breakpoint, number> = { lg: 1100, md: 700, sm: 0 }
export const COLUMNS: Record<Breakpoint, number> = { lg: 12, md: 8, sm: 4 }
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

/** The board: a responsive grid with one layout per form factor. */
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

export function BoardGrid(props: Props) {
  const { widgets, layouts, data, series, editing, canAct, onLayoutChange, onAction, onRefresh, onSettings, onRemove, compact, autoCompact } = props
  const { t } = useTranslation()
  // ⚠️ Three full layouts, rebuilt from scratch. Without the memo this ran on
  // every widget tick, once or twice a second on a board of thirty, and handed
  // react-grid-layout a new object identity each time.
  const gridLayouts: Layouts = useMemo(
    () => ({
      lg: layoutFor(layouts.lg, widgets, 12),
      md: layoutFor(layouts.md, widgets, 8),
      sm: layoutFor(layouts.sm, widgets, 4),
    }),
    [layouts, widgets],
  )
  /**
   * Move or resize the focused card with the arrow keys.
   *
   * Every breakpoint is changed at once, the way a drag does, so a card does
   * not walk out of step between the phone and the desktop layouts.
   */
  const nudge = (event: KeyboardEvent<HTMLDivElement>, widget: WidgetView) => {
    if (!onLayoutChange || event.altKey || event.ctrlKey || event.metaKey) return
    if (!event.key.startsWith('Arrow')) return
    // Only when the card itself has the focus, not something inside it.
    if (event.target !== event.currentTarget) return
    event.preventDefault()
    for (const [key, cols] of Object.entries(COLUMNS) as [Breakpoint, number][]) {
      const current = gridLayouts[key] ?? []
      const item = current.find((one) => one.i === String(widget.id))
      if (!item) continue
      const next = moved(item as LayoutItem, event.key, event.shiftKey, cols, floorOf(widget, cols))
      if (!next) continue
      onLayoutChange(
        key,
        current.map((one) => (one.i === next.i ? next : ({ i: one.i, x: one.x, y: one.y, w: one.w, h: one.h } as LayoutItem))),
      )
    }
  }

  return (
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
      onLayoutChange={(_current: Layout[], all: Layouts) => {
        if (!onLayoutChange || !editing) return
        for (const key of ['lg', 'md', 'sm'] as Breakpoint[]) {
          const layout = all[key]
          if (layout) onLayoutChange(key, layout.map(({ i, x, y, w, h }) => ({ i, x, y, w, h })))
        }
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

/** The smallest the adapter says this card is still usable at. */
function floorOf(widget: WidgetView, cols: number): [number, number] {
  const [w, h] = widget.min_size ?? widget.default_size ?? [1, 1]
  return [Math.max(1, Math.min(cols, w)), Math.max(1, h)]
}
