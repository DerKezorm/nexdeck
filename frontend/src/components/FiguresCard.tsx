/**
 * Key figures: the number cards a page put in here, drawn as tiles of one
 * grid with their value, unit and colour. Each tile is still its card: its
 * data, its settings, its yellow and red lines and its link are its own.
 *
 * While the board is arranged, a number card dragged onto the grid becomes a
 * tile, a tile dragged out becomes a card again, and the last tile adds a
 * new number card straight into the grid.
 */
import { Plus, Settings2 } from 'lucide-react'
import { useRef, type CSSProperties, type PointerEvent as ReactPointerEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { tLabel } from '../i18n/texts'
import { figuresLayout, tileMetric, toneOf } from '../lib/figures'
import { cardsOf, usePageCards } from '../lib/groups'
import { labelOf, localizeCustom } from '../lib/customCard'
import { formatValue } from '../lib/format'
import { safeUrl } from '../lib/safeUrl'
import { useDisguise } from '../lib/showcase'
import type { WidgetData, WidgetView } from '../lib/types'
import { useBoxSize } from '../lib/useBoxSize'
import { useLive } from '../stores/live'
import type { RenderProps } from './renderers'
import { ServiceIcon } from './ServiceIcon'
import { Sparkline } from './Sparkline'

/** As a group: more than this is a page of its own. */
const MOST_TILES = 12

function Tile({ card, data, points, history }: { card: WidgetView; data: WidgetData | undefined; points: number[] | undefined; history: boolean }) {
  const { t } = useTranslation()
  const page = usePageCards()
  const disguise = useDisguise()
  const holding = page.editing ? page.holding : undefined
  const tone = toneOf(card, data)
  // A custom card's texts are the author's own and come in the language of whoever looks.
  const L = labelOf(data)
  const primary = localizeCustom(data)?.primary
  const label = primary?.label ? L(primary.label) : ''
  const title = disguise.free(card.title) || label || tLabel(card.kind)
  const value = primary?.display ?? formatValue(primary?.value)
  const unit = primary?.unit ? L(primary.unit) : ''
  const reason = data?.error ? String(data.error) : tone === 'warn' || tone === 'bad' ? String(data?.meta?.status_reason ?? '') : ''
  const why = reason ? tLabel(reason) : label && label !== title ? label : (card.integration_name ?? '')
  // ⚠️ A link from the service is checked like every other; one that is not http(s) is none.
  const link = holding ? undefined : safeUrl(card.link || data?.link || card.service_link) || undefined
  const body = (
    <>
      {history && points && points.length >= 5 && new Set(points).size > 1 && (
        <span className="nd-tile-history" aria-hidden="true">
          <Sparkline values={points} height={40} fill={false} className="!h-full" />
        </span>
      )}
      <span className="nd-tile-head">
        {card.icon ? <ServiceIcon icon={card.icon} size={14} /> : null}
        <span className="truncate">{title}</span>
        <span className="dot nd-tile-dot" data-status={tone} aria-hidden="true" />
      </span>
      <span className="nd-tile-value num">
        {value}
        {unit && <small>{unit}</small>}
      </span>
      {why && <span className="nd-tile-why">{disguise.free(why)}</span>}
      {holding?.onSettings && (
        <button type="button" className="btn btn-icon btn-flat h-6 w-6 nd-tile-settings" onClick={() => holding.onSettings?.(card.id)} aria-label={t('widget.settings')} title={t('widget.settings')}>
          <Settings2 size={13} />
        </button>
      )}
    </>
  )
  const shared = {
    className: `nd-tile ${holding?.dragging === card.id ? 'opacity-30' : ''} ${holding ? 'nd-held-editing' : ''}`,
    'data-tone': tone,
    'data-held': card.id,
    onPointerDown: holding?.startDrag ? (event: ReactPointerEvent<HTMLElement>) => holding.startDrag?.(event, card) : undefined,
  }
  return link ? (
    <a {...shared} href={link} target="_blank" rel="noopener noreferrer" title={title}>
      {body}
    </a>
  ) : (
    <div {...shared} title={title}>
      {body}
    </div>
  )
}

export function FiguresCard({ widget, data }: RenderProps) {
  const { t } = useTranslation()
  const page = usePageCards()
  const live = useLive((state) => state.data)
  const series = useLive((state) => state.series)
  const box = useRef<HTMLDivElement>(null)
  const size = useBoxSize(box)
  const cards = cardsOf(widget, page.widgets)
  const arranging = Boolean(page.editing && page.holding)
  const adding = arranging && page.holding?.onAddInto && cards.length < MOST_TILES
  const columns = String(data?.meta?.columns ?? widget.options?.columns ?? 'auto')
  const look = String(data?.meta?.tone ?? widget.options?.tone ?? 'fill')
  const history = Boolean(data?.meta?.history ?? widget.options?.history)
  const { across, down } = figuresLayout(cards.length + (adding ? 1 : 0), size.width, size.height, columns)
  const over = page.holding?.over === `group:${widget.id}`
  return (
    <div
      ref={box}
      className={`nd-figures ${over ? 'bg-accent-soft' : ''}`}
      data-look={look}
      data-drop={arranging ? `group:${widget.id}` : undefined}
      style={{ '--across': across, '--down': down } as CSSProperties}
      data-testid="figures"
    >
      {cards.map((card) => {
        const cardData = live[card.id]
        const metric = tileMetric(cardData)
        return <Tile key={card.id} card={card} data={cardData} points={metric ? series[card.id]?.[metric] : undefined} history={history} />
      })}
      {adding && (
        <button type="button" className="nd-tile nd-tile-add" onClick={() => page.holding?.onAddInto?.(widget.id)}>
          <Plus size={16} aria-hidden="true" />
          {t('figures.add')}
        </button>
      )}
      {!cards.length && !adding && <p className="nd-figures-empty">{page.editing ? t('figures.emptyEditing') : t('figures.empty')}</p>}
    </div>
  )
}
