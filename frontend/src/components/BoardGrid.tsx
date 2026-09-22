import { memo, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type MouseEvent, type RefObject } from 'react'
import { useTranslation } from 'react-i18next'
import { Responsive, WidthProvider, type Layout, type Layouts } from 'react-grid-layout'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'

import { namedSizes, resized, shiftGroup } from '../lib/arranging'
import { fittingRow, perTwelfth } from '../lib/grid'
import type { Action, Breakpoint, LayoutItem, WidgetData, WidgetView } from '../lib/types'
import { CardMenu, type MoveTarget } from './CardMenu'
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
 *
 * The wide board has the columns its settings say, 12, 24 or 36, and every
 * size the server hands over is already in those columns.
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
  /** May change the board: a note card is written from the card itself. */
  canWrite?: boolean
  onLayoutChange?: (breakpoint: Breakpoint, layout: LayoutItem[]) => void
  onAction?: (widgetId: number, action: Action) => void
  onRefresh?: (widgetId: number) => void
  onSettings?: (widgetId: number) => void
  onRemove?: (widgetId: number) => void
  compact?: boolean
  /** On, every card moves up to fill space. Off, cards stay where they are dropped and gaps are allowed. */
  autoCompact?: boolean
  /** The columns of the wide board; twelve for a board that does not say. */
  columns?: number
  /** Stretch or shrink the rows so the page fits the window, as far as cards stay readable. */
  fitHeight?: boolean
  /** What the page leaves free under the board, in pixels, for fitting its height. */
  bottomSpace?: number
  /** Pages a card may be moved to from its menu; without them the menu offers sizes only. */
  moveTargets?: MoveTarget[]
  onMove?: (widgetIds: number[], pageId: number) => void
  /** Counted up by the page when it puts an arrangement back itself, so the grid draws it fresh. */
  epoch?: number
}

const STEP: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }

/** One press of an arrow key: one cell, or one cell of size with Shift. */
function moved(item: LayoutItem, key: string, resize: boolean, cols: number, floor: [number, number]): LayoutItem | null {
  const move = STEP[key]
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
  const { widgets, layouts, data, series, editing, canAct, canWrite, onLayoutChange, onAction, onRefresh, onSettings, onRemove, compact, autoCompact, fitHeight, bottomSpace = 40, moveTargets, onMove } = props
  const columns = props.columns ?? COLUMNS.lg
  const { t } = useTranslation()
  // The grid draws at the width WidthProvider assumes before it has measured,
  // which is a wide one; a phone reports itself right after.
  const [screen, setScreen] = useState<Screen>('lg')
  // ⚠️ Rebuilt only when the arrangement or the cards change. Without the memo
  // this ran on every widget tick, once or twice a second on a board of
  // thirty, and handed react-grid-layout a new object identity each time.
  const wide = useMemo(() => layoutFor(layouts.lg, widgets, columns), [layouts.lg, widgets, columns])
  const gridLayouts: Layouts = useMemo(() => ({ lg: wide, sm: stackedFor(wide, COLUMNS.sm, columns) }), [wide, columns])
  const cols = useMemo(() => ({ lg: columns, sm: COLUMNS.sm }), [columns])
  const host = useRef<HTMLDivElement>(null)
  const rows = useMemo(() => Math.max(1, ...wide.map((item) => item.y + item.h)), [wide])
  const rowHeight = useFittingRow(host, Boolean(fitHeight) && screen === 'lg', rows, bottomSpace) ?? (compact ? 60 : ROW_HEIGHT)

  /**
   * Several cards at once: Shift, Ctrl or Cmd and a press adds a card to the
   * selection or takes it out. A drag or an arrow key on any of them moves
   * them all; Escape and leaving edit mode let go.
   */
  const [selected, setSelected] = useState<Set<string>>(() => new Set())
  useEffect(() => {
    if (!editing) setSelected(new Set())
  }, [editing])
  // ⚠️ On the press, not the click: the grid starts its drag on the press and
  // the release lands on its placeholder, so a click never arrives.
  const pick = (event: MouseEvent<HTMLDivElement>, id: string) => {
    if (!(event.shiftKey || event.ctrlKey || event.metaKey)) return
    if ((event.target as HTMLElement).closest('.card-controls')) return
    event.preventDefault()
    event.stopPropagation()
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }
  const group = (id: string) => selected.size > 1 && selected.has(id)
  // A new grid when an arrangement is put back that the grid itself did not
  // make: a group move it refused, or a size from the menu.
  const [redraw, setRedraw] = useState(0)
  // The grid reports a drag twice, first as a drag and then as a change of
  // layout that knows of the one card only. A group move answers the first
  // and swallows the second.
  const handled = useRef(false)
  /**
   * While one card of a selection is dragged, the others go with it on
   * screen. The grid moves only the card under the pointer; the rest are
   * shifted by the same step here, and faded where the group cannot land.
   *
   * ⚠️ Reported on 22.09.2026: the others stood still until the pointer let
   * go and then jumped, which looked as if the selection had not taken.
   */
  const [follow, setFollow] = useState<{ dragged: string; dx: number; dy: number; fits: boolean; column: number } | null>(null)
  const drag = (_layout: Layout[], before: Layout, after: Layout) => {
    if (!group(after.i)) return
    const dx = after.x - before.x
    const dy = after.y - before.y
    if (follow && follow.dx === dx && follow.dy === dy) return
    // Measured here, in the handler: the grid is not read while it is drawn.
    const width = host.current?.clientWidth ?? 0
    const column = (width - GAP * (columns - 1)) / columns
    setFollow({ dragged: after.i, dx, dy, column, fits: shiftGroup(wide.map(plain), selected, dx, dy, columns) !== null })
  }
  const followStyle = (id: string): CSSProperties | undefined => {
    if (!follow || id === follow.dragged || !selected.has(id)) return undefined
    return {
      transform: `translate(${follow.dx * (follow.column + GAP)}px, ${follow.dy * (rowHeight + GAP)}px)`,
      opacity: follow.fits ? 1 : 0.4,
      position: 'relative',
      zIndex: 3,
    }
  }
  const dragStop = (_layout: Layout[], before: Layout, after: Layout) => {
    setFollow(null)
    if (!onLayoutChange || !group(after.i)) return
    // A card put back where it was makes no second report to swallow.
    if (after.x === before.x && after.y === before.y) return
    handled.current = true
    const moved = shiftGroup(wide.map(plain), selected, after.x - before.x, after.y - before.y, columns)
    if (moved) onLayoutChange('lg', moved)
    else setRedraw((n) => n + 1)
  }

  /**
   * Move or resize the focused card with the arrow keys.
   *
   * Always in the wide arrangement, since it is the only one; on a phone the
   * stack follows it.
   */
  const nudge = (event: KeyboardEvent<HTMLDivElement>, widget: WidgetView) => {
    if (!onLayoutChange || event.altKey || event.ctrlKey || event.metaKey) return
    // Only when the card itself has the focus, not something inside it.
    if (event.target !== event.currentTarget) return
    if (event.key === 'Escape' && selected.size) {
      event.preventDefault()
      setSelected(new Set())
      return
    }
    if (!event.key.startsWith('Arrow')) return
    event.preventDefault()
    const item = wide.find((one) => one.i === String(widget.id))
    if (!item) return
    if (group(item.i) && !event.shiftKey) {
      const [dx, dy] = STEP[event.key] ?? [0, 0]
      const moved = shiftGroup(wide.map(plain), selected, dx, dy, columns)
      if (moved) onLayoutChange('lg', moved)
      return
    }
    const next = moved(item as LayoutItem, event.key, event.shiftKey, columns, floorOf(widget, columns))
    if (!next) return
    onLayoutChange('lg', wide.map((one) => plain(one.i === next.i ? next : one)))
  }

  const [menu, setMenu] = useState<{ id: number; anchor: DOMRect } | null>(null)
  const openMenu = useCallback((id: number, anchor: DOMRect) => setMenu({ id, anchor }), [])
  const menuCard = menu ? widgets.find((one) => one.id === menu.id) : undefined
  const menuSpot = menu ? wide.find((one) => one.i === String(menu.id)) : undefined

  return (
    <>
      {/* On a phone a card cannot be dragged, so edit mode says where it can. */}
      {editing && screen === 'sm' && (
        <p role="note" className="text-xs text-muted px-1 pb-3">
          {t('board.stackedHint')}
        </p>
      )}
      <div ref={host}>
      <ResponsiveGrid
        // ⚠️ A new grid when the columns change. The responsive wrapper takes
        // the layouts from its props at once but its columns a render later,
        // so for one render a 24-column arrangement would lie on 12 columns:
        // the grid pulls every card past the edge back in, and edit mode
        // saves that.
        key={`${columns}-${redraw}-${props.epoch ?? 0}`}
        className={`board ${editing ? 'board-editing' : ''}`}
        layouts={gridLayouts}
        breakpoints={BREAKPOINTS}
        cols={cols}
        rowHeight={rowHeight}
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
        onDragStart={() => {
          handled.current = false
        }}
        onDrag={drag}
        onDragStop={dragStop}
        onLayoutChange={(_current: Layout[], all: Layouts) => {
          if (handled.current) {
            handled.current = false
            return
          }
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
            aria-selected={editing && selected.has(String(widget.id)) ? true : undefined}
            className={editing && selected.has(String(widget.id)) ? 'card-selected' : undefined}
            onKeyDown={editing ? (event) => nudge(event, widget) : undefined}
            onMouseDownCapture={editing ? (event) => pick(event, String(widget.id)) : undefined}
          >
            <div className="h-full" style={followStyle(String(widget.id))}>
            <GridCard
              widget={widget}
              data={data[widget.id]}
              series={series?.[widget.id]}
              editing={editing}
              canAct={canAct}
              canWrite={canWrite}
              onAction={onAction}
              onRefresh={onRefresh}
              onSettings={onSettings}
              onRemove={onRemove}
              onArrange={editing && onLayoutChange ? openMenu : undefined}
            />
            </div>
          </div>
        ))}
      </ResponsiveGrid>
      </div>
      {editing && selected.size > 1 && (
        <p role="status" className="text-xs text-muted px-1 pt-3">
          {t('arrange.selected', { count: selected.size })}
        </p>
      )}
      {menu && menuCard && menuSpot && onLayoutChange && (
        <CardMenu
          anchor={menu.anchor}
          carrying={group(menuSpot.i) ? selected.size : 1}
          sizes={namedSizes(floorOf(menuCard, columns), sizeOf(menuCard, columns), columns)}
          current={{ w: menuSpot.w, h: menuSpot.h }}
          targets={onMove ? moveTargets ?? [] : []}
          onSize={(w, h) => {
            onLayoutChange('lg', resized(wide.map(plain), menuSpot.i, w, h, columns))
            setRedraw((n) => n + 1)
          }}
          onMove={(pageId) => {
            const ids = group(menuSpot.i) ? [...selected].map(Number) : [menuCard.id]
            setSelected(new Set())
            onMove?.(ids, pageId)
          }}
          onClose={() => setMenu(null)}
        />
      )}
    </>
  )
}

interface CardProps {
  widget: WidgetView
  data: WidgetData | undefined
  series: Record<string, number[]> | undefined
  editing?: boolean
  canAct?: boolean
  canWrite?: boolean
  onAction?: (widgetId: number, action: Action) => void
  onRefresh?: (widgetId: number) => void
  onSettings?: (widgetId: number) => void
  onRemove?: (widgetId: number) => void
  onArrange?: (widgetId: number, anchor: DOMRect) => void
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
const GridCard = memo(function GridCard({ widget, data, series, editing, canAct, canWrite, onAction, onRefresh, onSettings, onRemove, onArrange }: CardProps) {
  const arrange = useCallback((anchor: DOMRect) => onArrange?.(widget.id, anchor), [onArrange, widget.id])
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
      canWrite={canWrite}
      onAction={onAction ? act : undefined}
      onRefresh={onRefresh && !editing && !widget.client_only ? refresh : undefined}
      onSettings={onSettings ? settings : undefined}
      onRemove={onRemove ? remove : undefined}
      onArrange={onArrange ? arrange : undefined}
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
    const w = Math.min(cols, Math.max(3 * perTwelfth(cols), minW))
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
export function stackedFor(wide: Layout[], cols: number, wideColumns: number = COLUMNS.lg): Layout[] {
  const half = Math.floor(cols / 2)
  const ordered = [...wide].sort((a, b) => a.y - b.y || a.x - b.x)
  const tall = (item: Layout) => Math.max(item.h, item.minH ?? 1)
  // Two twelfths of the wide board, in whatever columns it has.
  const small = (item: Layout) => item.w <= 2 * perTwelfth(wideColumns)
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

/** The size a card is made at, inside the columns. */
function sizeOf(widget: WidgetView, cols: number): [number, number] {
  const [w, h] = widget.default_size ?? widget.min_size ?? [3, 2]
  return [Math.max(1, Math.min(cols, w)), Math.max(1, h)]
}

/** The smallest the adapter says this card is still usable at. */
function floorOf(widget: WidgetView, cols: number): [number, number] {
  const [w, h] = widget.min_size ?? widget.default_size ?? [1, 1]
  return [Math.max(1, Math.min(cols, w)), Math.max(1, h)]
}

/**
 * The row height that makes the page fit the window, or null for the usual
 * one: when fitting is off, on a phone, or when the page has more rows than
 * the window can take at a readable height.
 *
 * Measured from where the grid starts on the page, not on the screen, so a
 * page scrolled a little keeps its rows; measured again whenever the window
 * or the space above the grid changes.
 */
function useFittingRow(host: RefObject<HTMLDivElement | null>, enabled: boolean, rows: number, bottomSpace: number): number | null {
  const [height, setHeight] = useState<number | null>(null)
  useEffect(() => {
    if (!enabled) {
      setHeight(null)
      return
    }
    let frame = 0
    const measure = () => {
      frame = 0
      const element = host.current
      if (!element) return
      const top = element.getBoundingClientRect().top + window.scrollY
      setHeight(fittingRow(window.innerHeight - top - bottomSpace, rows, GAP))
    }
    const later = () => {
      if (!frame) frame = window.requestAnimationFrame(measure)
    }
    measure()
    window.addEventListener('resize', later)
    const watcher = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(later)
    if (host.current?.parentElement) watcher?.observe(host.current.parentElement)
    return () => {
      window.removeEventListener('resize', later)
      watcher?.disconnect()
      if (frame) window.cancelAnimationFrame(frame)
    }
  }, [host, enabled, rows, bottomSpace])
  return height
}
