/**
 * The heading card: a title across the page, a line, or both, to split the
 * cards under it into a section. With the line alone it is a divider.
 *
 * It has no ground of its own (see `.card-plain`): a heading drawn as one more
 * glass box reads as one more card, and the point is that it is not one.
 *
 * Drawn from the card's own options, not from the server's answer, for the
 * same reason as the button card: the look is nothing a service knows, and a
 * change shows while the settings sheet is still open.
 */
import type { WidgetData, WidgetView } from '../lib/types'
import { ServiceIcon } from './ServiceIcon'

interface Props {
  widget: WidgetView
  data?: WidgetData
}

const SIZES: Record<string, string> = { small: 'text-[13px]', normal: 'text-[16px]', large: 'text-[21px]' }
const ICONS: Record<string, number> = { small: 15, normal: 18, large: 22 }

export function HeadingCard({ widget }: Props) {
  const option = (name: string, fallback: string) => {
    const own = widget.options?.[name]
    return typeof own === 'string' && own ? own : fallback
  }
  const style = option('style', 'both')
  const centred = option('align', 'left') === 'center'
  const size = SIZES[option('size', 'normal')] ? option('size', 'normal') : 'normal'
  const colour = option('colour', '') || undefined
  const title = (widget.title || '').trim()
  const showTitle = style !== 'line' && Boolean(title)
  const showLine = style !== 'title'

  const line = <span className="flex-1 min-w-4 border-t border-line" style={colour ? { borderColor: colour } : undefined} data-testid="heading-line" aria-hidden="true" />

  return (
    <div className={`flex-1 min-h-0 flex items-center gap-3 px-2 ${centred ? 'justify-center' : ''}`}>
      {showLine && centred && showTitle && line}
      {showTitle && (
        <h2 className={`flex items-center gap-2 min-w-0 font-semibold text-ink ${SIZES[size]}`} style={colour ? { color: colour } : undefined} title={title}>
          {widget.icon && <ServiceIcon icon={widget.icon} size={ICONS[size]} className="flex-none" />}
          <span className="truncate">{title}</span>
        </h2>
      )}
      {showLine && line}
    </div>
  )
}
