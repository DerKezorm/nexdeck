/**
 * The grid of a board, read from its settings.
 *
 * The server hands every card's sizes in the board's own columns already, so
 * nothing here converts twelfths; this only says how many columns there are,
 * how wide the board is drawn and how tall a row is.
 */

export const GRID_CHOICES = [12, 24, 36] as const
export type GridColumns = (typeof GRID_CHOICES)[number]
export const WIDTHS = ['normal', 'wide', 'full'] as const
export type BoardWidth = (typeof WIDTHS)[number]

export function gridColumns(settings: Record<string, unknown> | undefined): GridColumns {
  const value = settings?.columns
  return value === 24 || value === 36 ? value : 12
}

export function boardWidth(settings: Record<string, unknown> | undefined): BoardWidth {
  const value = settings?.width
  return value === 'wide' || value === 'full' ? value : 'normal'
}

/** The class that limits the board's width; `full` has none. */
export const WIDTH_CLASS: Record<BoardWidth, string> = {
  normal: 'max-w-[1480px]',
  wide: 'max-w-[2200px]',
  full: 'max-w-none',
}

/** How many of the board's columns one twelfth is. */
export function perTwelfth(columns: number): number {
  return Math.max(1, Math.round(columns / 12))
}

/** Below this a card has no room for its title and one line. */
export const FIT_ROW_MIN = 44
/** Above this a short board on a tall display turns into posters. */
export const FIT_ROW_MAX = 180

/**
 * The row height that fits `rows` rows into `space` pixels, or null when
 * it cannot be done without going below the floor. Then the board keeps its
 * usual rows and scrolls, rather than squeezing every card until none can be
 * read, which is what a board taller than the window would otherwise get.
 */
export function fittingRow(space: number, rows: number, gap: number): number | null {
  if (rows < 1 || space <= 0) return null
  const height = Math.floor((space - gap * (rows - 1)) / rows)
  if (height < FIT_ROW_MIN) return null
  return Math.min(FIT_ROW_MAX, height)
}
