import { ChevronDown } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { tLabel } from '../i18n/texts'
import { cardStatus } from '../lib/cardStatus'
import { cardsOf, useFolded, usePageCards } from '../lib/groups'
import { useDisguise } from '../lib/showcase'
import type { WidgetView } from '../lib/types'
import { useLive } from '../stores/live'
import type { RenderProps } from './renderers'
import { renderWidget } from './renderers'
import { ServiceIcon } from './ServiceIcon'
import { WidgetCard } from './WidgetCard'

/** Two rows of the board (ROW_HEIGHT 68): no card on it is smaller. */
export const CARD_FLOOR = 136

/** What a holder says while it holds nothing yet: where its cards come from. */
function Waiting({ editing }: { editing?: boolean }) {
  const { t } = useTranslation()
  return <div className="flex-1 flex items-center justify-center text-xs text-faint px-4 text-center">{editing ? t('groups.emptyEditing') : t('groups.empty')}</div>
}

/**
 * Several cards in one, a tab each. The tab says how its card stands, so a
 * red card is seen from the other tab. On a wall it can turn the tabs
 * itself, and holds still under the pointer.
 */
export function TabsCard({ widget }: RenderProps) {
  const page = usePageCards()
  const disguise = useDisguise()
  const live = useLive((state) => state.data)
  const series = useLive((state) => state.series)
  const cards = cardsOf(widget, page.widgets)
  const [active, setActive] = useState(0)
  const [held, setHeld] = useState(false)
  const turn = Number(widget.options?.turn ?? 0)
  useEffect(() => {
    if (!turn || held || cards.length < 2) return
    const timer = window.setInterval(() => setActive((index) => (index + 1) % cards.length), turn * 1000)
    return () => window.clearInterval(timer)
  }, [turn, held, cards.length])
  if (!cards.length) return <Waiting editing={page.editing} />
  const shown: WidgetView = cards[Math.min(active, cards.length - 1)]
  const data = live[shown.id]
  return (
    <div className="flex-1 min-h-0 flex flex-col" onMouseEnter={() => setHeld(true)} onMouseLeave={() => setHeld(false)} data-testid="tabs">
      <div role="tablist" className="flex gap-0.5 px-2 pt-1.5 border-b border-line overflow-x-auto scrollbar-none" aria-label={disguise.free(widget.title)}>
        {cards.map((card, index) => {
          const chosen = card.id === shown.id
          return (
            <button
              key={card.id}
              type="button"
              role="tab"
              aria-selected={chosen}
              className={`flex items-center gap-1.5 whitespace-nowrap px-2.5 py-1.5 -mb-px text-[12px] border-b-2 transition-colors ${chosen ? 'border-accent text-ink' : 'border-transparent text-muted hover:text-ink'}`}
              onClick={() => setActive(index)}
            >
              {card.icon ? <ServiceIcon icon={card.icon} size={13} /> : null}
              {disguise.free(card.title || tLabel(card.kind))}
              <span className="dot" data-status={cardStatus(card, live[card.id])} />
            </button>
          )
        })}
      </div>
      <div role="tabpanel" className="flex-1 min-h-0 flex flex-col pt-2" key={shown.id}>
        {data?.error ? (
          <p className="px-3 text-[12px] text-bad">{disguise.free(String(data.error))}</p>
        ) : (
          renderWidget({ widget: shown, data, series: series[shown.id], canAct: page.canAct, onAction: page.onAction ? (action) => page.onAction?.(shown.id, action) : undefined })
        )}
      </div>
    </div>
  )
}

/**
 * A titled box of cards side by side that folds away. Folded, it is one row
 * high and says how many cards it holds and how many of them are down; the
 * fold is this browser's, never the board's.
 */
export function GroupCard({ widget }: RenderProps) {
  const { t } = useTranslation()
  const page = usePageCards()
  const disguise = useDisguise()
  const live = useLive((state) => state.data)
  const series = useLive((state) => state.series)
  const folded = useFolded((state) => state.folded.includes(widget.id))
  const toggle = useFolded((state) => state.toggle)
  const cards = cardsOf(widget, page.widgets)
  const down = cards.filter((card) => cardStatus(card, live[card.id]) === 'bad').length
  const columns = String(widget.options?.columns ?? 'auto')
  return (
    <div className="flex-1 min-h-0 flex flex-col" data-testid="group">
      <button
        type="button"
        className="flex items-center gap-2 px-3 py-2 text-left w-full"
        onClick={() => toggle(widget.id)}
        aria-expanded={!folded}
        disabled={page.editing}
      >
        <ChevronDown size={15} className={`text-muted transition-transform ${folded ? '-rotate-90' : ''}`} aria-hidden="true" />
        <span className="text-[14px] font-semibold truncate">{disguise.free(widget.title)}</span>
        <span className="flex-1" />
        <span className="chip">
          {t('groups.cards', { count: cards.length })}
          {down ? <b className="text-bad">· {t('groups.down', { count: down })}</b> : null}
        </span>
      </button>
      {!folded &&
        (cards.length ? (
          // ⚠️ Every row keeps the height of the smallest card on the board,
          // and the box scrolls past it. On a phone the cards wrap to one a
          // row inside a box no taller than the wide board made it, and three
          // of them shared the height of one, drawn over each other.
          <div
            className="flex-1 min-h-0 grid gap-2.5 px-3 pb-3 overflow-y-auto"
            style={{
              gridTemplateColumns: columns === 'auto' ? 'repeat(auto-fit, minmax(180px, 1fr))' : `repeat(${Number(columns) || 3}, minmax(0, 1fr))`,
              gridAutoRows: `minmax(${CARD_FLOOR}px, 1fr)`,
            }}
          >
            {cards.map((card) => (
              <div key={card.id} className="min-h-0 nd-in-group">
                <WidgetCard widget={card} data={live[card.id]} series={series[card.id]} canAct={page.canAct} onAction={page.onAction ? (action) => page.onAction?.(card.id, action) : undefined} />
              </div>
            ))}
          </div>
        ) : (
          <Waiting editing={page.editing} />
        ))}
    </div>
  )
}
