import { Responsive, WidthProvider, type Layout, type Layouts } from 'react-grid-layout'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'

import type { Breakpoint, LayoutItem, WidgetData, WidgetView } from '../lib/types'
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
  onAction?: (widgetId: number, action: string, params?: Record<string, unknown>) => void
  onRefresh?: (widgetId: number) => void
  onSettings?: (widgetId: number) => void
  onRemove?: (widgetId: number) => void
  compact?: boolean
}

/** The board: a responsive grid with one layout per form factor. */
export function BoardGrid(props: Props) {
  const { widgets, layouts, data, series, editing, canAct, onLayoutChange, onAction, onRefresh, onSettings, onRemove, compact } = props
  const byId = new Map(widgets.map((w) => [String(w.id), w]))
  const gridLayouts: Layouts = {
    lg: fill(layouts.lg, widgets, 12),
    md: fill(layouts.md, widgets, 8),
    sm: fill(layouts.sm, widgets, 4),
  }
  return (
    <ResponsiveGrid
      className="board"
      layouts={gridLayouts}
      breakpoints={BREAKPOINTS}
      cols={COLUMNS}
      rowHeight={compact ? 60 : ROW_HEIGHT}
      margin={[GAP, GAP]}
      containerPadding={[0, 0]}
      isDraggable={Boolean(editing)}
      isResizable={Boolean(editing)}
      compactType="vertical"
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
            onAction={onAction ? (action, params) => onAction(widget.id, action, params) : undefined}
            onRefresh={onRefresh && !editing ? () => onRefresh(widget.id) : undefined}
            onSettings={onSettings ? () => onSettings(widget.id) : undefined}
            onRemove={onRemove ? () => onRemove(widget.id) : undefined}
          />
        </div>
      ))}
      {byId.size === 0 ? null : null}
    </ResponsiveGrid>
  )
}

/** Widgets without a saved position get one at the bottom, so nothing is lost. */
function fill(layout: LayoutItem[] | undefined, widgets: WidgetView[], cols: number): Layout[] {
  const known = new Map((layout ?? []).map((item) => [item.i, item]))
  const result: Layout[] = []
  let y = Math.max(0, ...(layout ?? []).map((item) => item.y + item.h))
  let x = 0
  for (const widget of widgets) {
    const id = String(widget.id)
    const item = known.get(id)
    if (item) {
      result.push({ ...item, minW: item.minW ?? 1, minH: item.minH ?? 1 })
      continue
    }
    const w = Math.min(cols, 3)
    if (x + w > cols) {
      x = 0
      y += 2
    }
    result.push({ i: id, x, y, w, h: 2, minW: 1, minH: 1 })
    x += w
  }
  return result
}
