/**
 * A card inside a group or the side bar, and the side bar itself.
 *
 * While the board is arranged a held card can be taken hold of and dragged
 * out, into another group, into the side bar or onto the board, and its size
 * inside steps through two buttons at its foot. Outside of that it is drawn
 * like any card.
 */
import type { CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'

import { HELD_WIDTHS, MOST_HELD_ROWS, SIDE_WIDTH, type HeldSize, type Side } from '../lib/holding'
import { usePageCards } from '../lib/groups'
import type { WidgetView } from '../lib/types'
import { useLive } from '../stores/live'
import { WidgetCard } from './WidgetCard'

/** A width in twelfths, as a reader says it: ¼, ⅓, ½, ⅔ or whole. */
function share(w: number, whole: string): string {
  return ({ 2: '⅙', 3: '¼', 4: '⅓', 6: '½', 8: '⅔', 9: '¾', 12: whole } as Record<number, string>)[w] ?? `${w}/12`
}

/** The next step of a width or a height; the last one goes round to the first. */
export function nextWidth(w: number): number {
  return HELD_WIDTHS.find((one) => one > w) ?? HELD_WIDTHS[0]
}
export function nextHeight(h: number): number {
  return h >= MOST_HELD_ROWS ? 1 : h + 1
}

interface HeldProps {
  widget: WidgetView
  size: HeldSize
  /** In the side bar a card is as wide as the bar; only its height can change. */
  heightOnly?: boolean
  style?: CSSProperties
}

export function HeldCard({ widget, size, heightOnly, style }: HeldProps) {
  const { t } = useTranslation()
  const page = usePageCards()
  const live = useLive((state) => state.data[widget.id])
  const series = useLive((state) => state.series[widget.id])
  const holding = page.editing ? page.holding : undefined
  const settings = holding?.onSettings
  const remove = holding?.onRemove
  return (
    <div
      className={`relative min-h-0 nd-in-group ${holding ? 'nd-held-editing' : ''} ${holding?.dragging === widget.id ? 'opacity-30' : ''}`}
      style={style}
      data-held={widget.id}
      onPointerDown={holding?.startDrag ? (event) => holding.startDrag?.(event, widget) : undefined}
    >
      <WidgetCard
        widget={widget}
        data={live}
        series={series}
        editing={page.editing}
        canAct={page.canAct}
        onAction={page.onAction ? (action) => page.onAction?.(widget.id, action) : undefined}
        onSettings={settings ? () => settings(widget.id) : undefined}
        onRemove={remove ? () => remove(widget.id) : undefined}
      />
      {holding?.onHeldSize && (
        <span className="absolute right-1.5 bottom-1.5 z-10 flex gap-1 nd-held-sizes">
          {!heightOnly && (
            <button
              type="button"
              className="chip !py-0 text-[10.5px] bg-[var(--nd-bg-elev)]"
              onClick={() => holding.onHeldSize?.(widget, { ...size, w: nextWidth(size.w) })}
              aria-label={t('holding.widthOf', { name: widget.title || widget.kind })}
            >
              {t('holding.width', { part: share(size.w, t('holding.whole')) })}
            </button>
          )}
          <button
            type="button"
            className="chip !py-0 text-[10.5px] bg-[var(--nd-bg-elev)]"
            onClick={() => holding.onHeldSize?.(widget, { ...size, h: nextHeight(size.h) })}
            aria-label={t('holding.heightOf', { name: widget.title || widget.kind })}
          >
            {t('holding.height', { rows: size.h })}
          </button>
        </span>
      )}
    </div>
  )
}

interface SideProps {
  side: Side
  cards: WidgetView[]
  /** On a phone the bar stands over the board, as wide as the screen. */
  stacked?: boolean
}

/** The column beside the board that stays where it is while the page scrolls. */
export function SideBar({ side, cards, stacked }: SideProps) {
  const { t } = useTranslation()
  const page = usePageCards()
  const rowHeight = page.rowHeight ?? 68
  const gap = page.gap ?? 12
  const arranging = Boolean(page.editing && page.holding && !stacked)
  const over = page.holding?.over === 'side'
  return (
    <aside
      className={`flex flex-col self-start ${stacked ? 'w-full mb-3' : 'sticky top-16 shrink-0'} ${arranging ? `rounded-2xl border-2 border-dashed p-2 ${over ? 'border-[var(--nd-accent)] bg-accent-soft' : 'border-line-strong'}` : ''}`}
      style={{ width: stacked ? undefined : SIDE_WIDTH[side.width], gap }}
      data-drop={arranging ? 'side' : undefined}
      aria-label={t('holding.side')}
    >
      {arranging && <span className="text-[11px] uppercase tracking-wide text-muted px-1">{t('holding.side')}</span>}
      {cards.map((card) => {
        const h = Math.max(1, Math.min(12, Number((card.options?.held_size as HeldSize | undefined)?.h) || 2))
        return <HeldCard key={card.id} widget={card} size={{ w: 12, h }} heightOnly style={{ height: h * rowHeight + (h - 1) * gap }} />
      })}
      {arranging && !cards.length && <p className="text-xs text-faint px-2 py-6 text-center">{t('holding.sideEmpty')}</p>}
    </aside>
  )
}
