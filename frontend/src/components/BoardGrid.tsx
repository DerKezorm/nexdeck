import { useMemo } from 'react'
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
export function BoardGrid(props: Props) {
  const { widgets, layouts, data, series, editing, canAct, onLayoutChange, onAction, onRefresh, onSettings, onRemove, compact, autoCompact } = props
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
      draggableCancel="button, a, input, select, textarea, [role='button'], .no-drag"
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
        <div key={String(widget.id)}>
          <WidgetCard
            widget={widget}
            data={data[widget.id]}
            series={series?.[widget.id]}
            editing={editing}
            canAct={canAct}
            onAction={onAction ? (action) => onAction(widget.id, action) : undefined}
            onRefresh={onRefresh && !editing && !widget.client_only ? () => onRefresh(widget.id) : undefined}
            onSettings={onSettings ? () => onSettings(widget.id) : undefined}
            onRemove={onRemove ? () => onRemove(widget.id) : undefined}
          />
        </div>
      ))}
    </ResponsiveGrid>
  )
}

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
