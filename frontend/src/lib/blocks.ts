/**
 * The finished blocks of a card put together from blocks (KARTEN-7), as the server sends them in `meta.blocks`.
 *
 * The server works everything out (values, colours, rows, which button is offered); the browser only draws. A text
 * on a block is the author's own, one text or one per language, and is picked for the viewer on the way to the screen.
 */
import type { Action } from './types'

export type Size = 'xs' | 's' | 'm' | 'l' | 'xl'
export type Gap = 'none' | 's' | 'm' | 'l'
export type HeightStep = 's' | 'm' | 'l'

/** The colours a block may have: the theme's and nexdeck's own, nothing free. */
export const BLOCK_COLORS = ['text', 'accent', 'green', 'yellow', 'red', 'muted', 'blue', 'violet', 'pink', 'orange'] as const
export type BlockColor = (typeof BLOCK_COLORS)[number]

/** One value, written out by the server. `null` is a value that is not there: the block keeps its place and stays empty. */
export type ShownBlockValue = { text: string; number?: number | null; status?: 'ok' | 'warn' | 'error' | 'unknown' | null } | null

export interface BlockRow {
  blocks: Block[]
  actions?: Action[]
}

export type Block =
  | { type: 'row'; id?: string; gap: Gap; align: 'start' | 'center' | 'end' | 'between'; wrap: boolean; children: Block[] }
  | { type: 'column'; id?: string; gap: Gap; children: Block[] }
  | { type: 'divider'; id?: string }
  | { type: 'text'; id?: string; value: ShownBlockValue; size: Size; weight: 'normal' | 'bold'; color: string }
  | { type: 'value'; id?: string; label?: string | Record<string, string>; value: ShownBlockValue; size: Size; color: string }
  | { type: 'badge'; id?: string; value: ShownBlockValue; color: string }
  | { type: 'symbol'; id?: string; icon: string; color: string; size: Size }
  | { type: 'image'; id?: string; src: string | null; height: HeightStep }
  | { type: 'progress'; id?: string; value: ShownBlockValue; max: number; color: string }
  | { type: 'sparkline'; id: string; value: ShownBlockValue; metric: string }
  | { type: 'list'; id?: string; rows: BlockRow[]; empty?: string | Record<string, string> }
  | { type: 'button'; id?: string; action: Action | null }

/** The colour as a CSS value. A name nobody knows is the text colour (KARTEN-7 AC-3). */
export function colorOf(name: string | undefined): string {
  switch (name) {
    case 'accent':
      return 'var(--nd-accent)'
    case 'green':
      return 'var(--nd-ok)'
    case 'yellow':
      return 'var(--nd-warn)'
    case 'red':
      return 'var(--nd-bad)'
    case 'muted':
      return 'var(--nd-text-muted)'
    case 'blue':
      return 'var(--nd-c-blue)'
    case 'violet':
    case 'purple':
      return 'var(--nd-c-violet)'
    case 'pink':
      return 'var(--nd-c-pink)'
    case 'orange':
      return 'var(--nd-c-orange)'
    default:
      return 'var(--nd-text)'
  }
}

/** The colour a status gives a value: it wins over the block's own colour when the server set one. */
export function statusColor(status: string | null | undefined): string | null {
  if (status === 'ok') return 'var(--nd-ok)'
  if (status === 'warn') return 'var(--nd-warn)'
  if (status === 'error') return 'var(--nd-bad)'
  if (status === 'unknown') return 'var(--nd-unknown)'
  return null
}

/** Whether a block has a list inside it, which is the one thing on a card that scrolls. */
export function holdsList(block: Block): boolean {
  if (block.type === 'list') return true
  return block.type === 'row' || block.type === 'column' ? block.children.some(holdsList) : false
}
