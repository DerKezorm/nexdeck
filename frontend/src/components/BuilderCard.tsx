/**
 * The card put together from blocks (KARTEN-7): rows, columns and the blocks in them, drawn from the finished tree the
 * server sends in `meta.blocks`. The browser works nothing out here. Spaces and sizes come in fixed steps, colours from
 * the theme's tokens only (AC-3); a value that is not there leaves its block empty and in its place (EC-1); a long text
 * is cut with an ellipsis (EC-2); a row breaks into lines on a narrow card (EC-3); a list scrolls inside the card and
 * everything else is cut off at its edge, and the editor is told (AC-7).
 */
import { createContext, useContext, useLayoutEffect, useRef, useState } from 'react'
import { ImageOff } from 'lucide-react'

import { BLOCK_COLORS, colorOf, holdsList, statusColor, type Block, type BlockRow, type Gap, type HeightStep, type ShownBlockValue, type Size } from '../lib/blocks'
import { safeUrl } from '../lib/safeUrl'
import { useDisguise } from '../lib/showcase'
import { ActionButtons, type RenderProps } from './renderers'
import { LucideByName } from './ServiceIcon'
import { Sparkline } from './Sparkline'

/** Who wants to know whether the blocks fit the card: the editor's preview. Cards on a board have nobody asking. */
export const OverflowContext = createContext<((overflowing: boolean) => void) | null>(null)

const TEXT_SIZE: Record<Size, string> = { xs: 'text-[11px]', s: 'text-xs', m: 'text-sm', l: 'text-lg', xl: 'text-2xl' }
const VALUE_SIZE: Record<Size, string> = { xs: 'text-sm', s: 'text-base', m: 'text-xl', l: 'text-3xl', xl: 'text-4xl' }
const SYMBOL_PX: Record<Size, number> = { xs: 12, s: 14, m: 18, l: 24, xl: 32 }
const GAP: Record<Gap, string> = { none: 'gap-0', s: 'gap-1', m: 'gap-2', l: 'gap-4' }
const IMAGE_HEIGHT: Record<HeightStep, string> = { s: 'h-10', m: 'h-16', l: 'h-28' }
const ALIGN = { start: 'justify-start', center: 'justify-center', end: 'justify-end', between: 'justify-between' } as const

/** Whether a block's colour is one of the allowed names: any other name is drawn as the text colour. */
export const knownColor = (name: string | undefined): boolean => (BLOCK_COLORS as readonly string[]).includes(name ?? '')

/** What a value says, `''` when there is none. */
function said(value: ShownBlockValue | undefined): string {
  return value?.text ?? ''
}

/** An empty value keeps its place: one line of the block's own size, with nothing in it. */
const EMPTY = ' '

type Draw = Pick<RenderProps, 'series' | 'canAct' | 'onAction'>

function Free({ text, className, style, title }: { text: string; className: string; style?: React.CSSProperties; title?: boolean }) {
  const disguise = useDisguise()
  const shown = disguise.free(text)
  return (
    <span className={className} style={style} title={title && shown ? shown : undefined}>
      {shown || EMPTY}
    </span>
  )
}

function Pictured({ src, height }: { src: string | null; height: HeightStep }) {
  const [broken, setBroken] = useState(false)
  // Only an address nexdeck may link to; anything else, and a picture that does not load, is the placeholder (EC-7).
  const safe = src ? safeUrl(src) : ''
  // A path is one slash and no more: two lead to another host.
  const usable = /^(https?:\/\/|\/(?!\/))/i.test(safe) && !broken
  return (
    <div className={`${IMAGE_HEIGHT[height]} w-full rounded-lg overflow-hidden bg-surface-hover grid place-items-center shrink-0`} data-testid="block-image">
      {usable ? (
        <img src={safe} alt="" loading="lazy" onError={() => setBroken(true)} className="w-full h-full object-cover" />
      ) : (
        <ImageOff size={18} className="text-faint" aria-hidden="true" data-testid="block-image-placeholder" />
      )}
    </div>
  )
}

function BlockView({ block, draw, inList }: { block: Block; draw: Draw; inList?: boolean }) {
  switch (block.type) {
    case 'row':
      return (
        <div className={`flex flex-row items-center min-w-0 max-w-full ${block.wrap === false ? 'flex-nowrap' : 'flex-wrap'} ${GAP[block.gap] ?? GAP.m} ${ALIGN[block.align] ?? ALIGN.start} ${holdsList(block) ? 'min-h-0 shrink' : 'shrink-0'}`} data-block="row">
          {(block.children ?? []).map((child, index) => (
            <BlockView key={child.id ?? index} block={child} draw={draw} inList={inList} />
          ))}
        </div>
      )
    case 'column':
      return (
        <div className={`flex flex-col min-w-0 max-w-full ${GAP[block.gap] ?? GAP.m} ${holdsList(block) ? 'min-h-0 shrink overflow-hidden' : 'shrink-0'}`} data-block="column">
          {(block.children ?? []).map((child, index) => (
            <BlockView key={child.id ?? index} block={child} draw={draw} inList={inList} />
          ))}
        </div>
      )
    case 'divider':
      return <hr className="border-0 border-t border-line w-full shrink-0 my-0.5" data-block="divider" />
    case 'text':
      return (
        <Free
          text={said(block.value)}
          title
          className={`block min-w-0 max-w-full truncate shrink-0 ${TEXT_SIZE[block.size] ?? TEXT_SIZE.s} ${block.weight === 'bold' ? 'font-semibold' : ''}`}
          style={{ color: colorOf(block.color) }}
        />
      )
    case 'value': {
      // A status the server set wins over the block's own colour.
      const color = statusColor(block.value?.status) ?? colorOf(block.color)
      return (
        <div className="min-w-0 max-w-full shrink-0" data-block="value">
          {block.label ? <div className="text-[11px] text-muted uppercase tracking-wide truncate">{String(block.label)}</div> : null}
          <Free text={said(block.value)} title className={`block num truncate font-semibold leading-tight ${VALUE_SIZE[block.size] ?? VALUE_SIZE.m}`} style={{ color }} />
        </div>
      )
    }
    case 'badge': {
      const color = statusColor(block.value?.status) ?? colorOf(block.color)
      return (
        <Free
          text={said(block.value)}
          title
          className="chip max-w-full min-w-0 truncate shrink-0 font-medium"
          style={{ color, background: `color-mix(in srgb, ${color} 14%, transparent)` }}
        />
      )
    }
    case 'symbol':
      return (
        <span className="shrink-0 inline-flex" style={{ color: colorOf(block.color) }} data-block="symbol">
          <LucideByName name={block.icon} size={SYMBOL_PX[block.size] ?? SYMBOL_PX.m} />
        </span>
      )
    case 'image':
      return <Pictured src={block.src} height={block.height ?? 'm'} />
    case 'progress': {
      const number = block.value?.number
      const share = typeof number === 'number' && block.max > 0 ? Math.max(0, Math.min(1, number / block.max)) : 0
      const color = statusColor(block.value?.status) ?? colorOf(block.color)
      return (
        <div
          className="bar w-full shrink-0"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={block.max}
          aria-valuenow={typeof number === 'number' ? number : undefined}
          data-testid="block-progress"
        >
          <span className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${share * 100}%`, background: color }} />
        </div>
      )
    }
    case 'sparkline': {
      const points = draw.series?.[block.metric]
      // Drawn only once there is a line to draw; until then the block keeps its height.
      return (
        <div className="w-full shrink-0 h-7" data-testid="block-sparkline" aria-hidden="true">
          {points && points.length >= 2 && new Set(points).size > 1 ? <Sparkline values={points} height={28} /> : null}
        </div>
      )
    }
    case 'list':
      return <ListBlock rows={block.rows ?? []} empty={typeof block.empty === 'string' ? block.empty : undefined} draw={draw} />
    case 'button':
      return block.action ? (
        <div className="shrink-0 min-w-0 max-w-full" data-block="button">
          <ActionButtons actions={[block.action]} canAct={draw.canAct} onAction={draw.onAction} compact labelled />
        </div>
      ) : null
    default:
      return null
  }
}

/** The rows of a list: the template once for each row. It is the one block that scrolls when the card is too small. */
function ListBlock({ rows, empty, draw }: { rows: BlockRow[]; empty?: string; draw: Draw }) {
  if (!rows.length) {
    return empty ? (
      <div className="text-xs text-faint text-center py-2 shrink-0" data-testid="block-list-empty">
        {empty}
      </div>
    ) : null
  }
  return (
    <ul className="scroll min-h-10 min-w-0 w-full flex-initial grid content-start gap-1" data-scroll="" data-block="list">
      {rows.map((row, index) => (
        <li key={index} className="min-w-0 grid gap-1">
          {(row.blocks ?? []).map((block, at) => (
            <BlockView key={block.id ?? at} block={block} draw={draw} inList />
          ))}
        </li>
      ))}
    </ul>
  )
}

/** The blocks of the card and whether they fit it: what runs over the edge is cut, and the editor is told. */
export function BuilderCard({ data, series, canAct, onAction }: RenderProps) {
  const root = useRef<HTMLDivElement>(null)
  const report = useContext(OverflowContext)
  const blocks = Array.isArray(data?.meta?.blocks) ? (data.meta.blocks as Block[]) : []

  useLayoutEffect(() => {
    const element = root.current
    if (!report || !element) return
    const measure = () => {
      const clipped = (one: Element) => one.scrollHeight > one.clientHeight + 1 || one.scrollWidth > one.clientWidth + 1
      report(clipped(element) || [...element.querySelectorAll('[data-scroll]')].some(clipped))
    }
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const watcher = new ResizeObserver(measure)
    watcher.observe(element)
    return () => watcher.disconnect()
  })

  const draw: Draw = { series, canAct, onAction }
  return (
    <div ref={root} className="flex-1 min-h-0 min-w-0 overflow-hidden px-3 pb-2 flex flex-col gap-2" data-testid="builder-card">
      {blocks.map((block, index) => (
        <BlockView key={block.id ?? index} block={block} draw={draw} />
      ))}
    </div>
  )
}
