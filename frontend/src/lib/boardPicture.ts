/**
 * The board as a picture, ready to post: the board as it is on screen, at
 * twice its size, on a frame of colour with a small note of where it comes
 * from in the corner.
 *
 * The picture is drawn in this browser from what is on the page; nothing is
 * sent anywhere. The library that turns the page into a picture is loaded
 * only when somebody asks for one: it is not small, and most never do.
 */
import { create } from 'zustand'

/** Whether a board page is open that can be saved as a picture, and whether the dialog for it is. */
export const usePicture = create<{ available: boolean; open: boolean; setAvailable: (available: boolean) => void; setOpen: (open: boolean) => void }>((set) => ({
  available: false,
  open: false,
  setAvailable: (available) => set({ available }),
  setOpen: (open) => set({ open }),
}))

export type Frame = 'gradient' | 'accent' | 'none'

export interface PictureOptions {
  frame: Frame
  /** "made with nexdeck" in the corner. */
  note: boolean
  /** Twice the size on screen, for a sharp picture on a phone. */
  scale?: number
}

/** What is left out of the picture: the bars, buttons that float over cards, notices. */
export function leftOut(node: Node): boolean {
  if (!(node instanceof Element)) return false
  // Dialogs and passing notices are not part of the board either.
  const role = node.getAttribute('role')
  return node.hasAttribute('data-no-picture') || node.classList.contains('card-controls') || role === 'dialog' || role === 'status'
}

function colour(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

/** Rounded corners for a canvas path, without relying on roundRect being there. */
function rounded(context: CanvasRenderingContext2D, x: number, y: number, width: number, height: number, radius: number): void {
  context.beginPath()
  context.moveTo(x + radius, y)
  context.arcTo(x + width, y, x + width, y + height, radius)
  context.arcTo(x + width, y + height, x, y + height, radius)
  context.arcTo(x, y + height, x, y, radius)
  context.arcTo(x, y, x + width, y, radius)
  context.closePath()
}

/**
 * The board drawn into a picture with its frame and note. `board` is the
 * board as a canvas already; this only puts it on its frame, which keeps the
 * part that can be tested apart from the part that needs a real browser.
 */
export function framed(board: HTMLCanvasElement, options: PictureOptions): HTMLCanvasElement {
  const scale = options.scale ?? 2
  const margin = options.frame === 'none' ? 0 : 40 * scale
  const canvas = document.createElement('canvas')
  canvas.width = board.width + margin * 2
  canvas.height = board.height + margin * 2
  const context = canvas.getContext('2d')
  if (!context) return board
  const accent = colour('--nd-accent', '#22d3ee')
  if (options.frame === 'gradient') {
    const ground = context.createLinearGradient(0, 0, canvas.width, canvas.height)
    ground.addColorStop(0, accent)
    ground.addColorStop(0.55, '#818cf8')
    ground.addColorStop(1, '#f472b6')
    context.fillStyle = ground
    context.fillRect(0, 0, canvas.width, canvas.height)
  } else if (options.frame === 'accent') {
    context.fillStyle = accent
    context.fillRect(0, 0, canvas.width, canvas.height)
    context.fillStyle = 'rgba(0, 0, 0, 0.55)'
    context.fillRect(0, 0, canvas.width, canvas.height)
  }
  const radius = options.frame === 'none' ? 0 : 16 * scale
  context.save()
  if (margin) {
    context.shadowColor = 'rgba(0, 0, 0, 0.45)'
    context.shadowBlur = 40 * scale
    context.shadowOffsetY = 16 * scale
    rounded(context, margin, margin, board.width, board.height, radius)
    context.fillStyle = colour('--nd-bg', '#0a0d12')
    context.fill()
  }
  context.restore()
  context.save()
  rounded(context, margin, margin, board.width, board.height, radius)
  context.clip()
  context.drawImage(board, margin, margin)
  context.restore()
  if (options.note) note(context, canvas, margin, scale)
  return canvas
}

/** The small note in the corner: a mark in the accent and "made with nexdeck". */
function note(context: CanvasRenderingContext2D, canvas: HTMLCanvasElement, margin: number, scale: number): void {
  const text = 'made with nexdeck'
  context.font = `500 ${12 * scale}px Inter, system-ui, sans-serif`
  const width = context.measureText(text).width + 34 * scale
  const height = 26 * scale
  const inset = (margin ? margin : 0) + 14 * scale
  const x = canvas.width - inset - width
  const y = canvas.height - inset - height
  context.fillStyle = 'rgba(0, 0, 0, 0.55)'
  rounded(context, x, y, width, height, height / 2)
  context.fill()
  const mark = context.createLinearGradient(x, y, x + 12 * scale, y + 12 * scale)
  mark.addColorStop(0, colour('--nd-accent', '#22d3ee'))
  mark.addColorStop(1, '#818cf8')
  context.fillStyle = mark
  rounded(context, x + 10 * scale, y + 7 * scale, 12 * scale, 12 * scale, 3 * scale)
  context.fill()
  context.fillStyle = '#ffffff'
  context.textBaseline = 'middle'
  context.fillText(text, x + 28 * scale, y + height / 2 + scale)
}

/** The board page as a canvas, by the library that is loaded for it now. */
export async function boardCanvas(page: HTMLElement, scale = 2): Promise<HTMLCanvasElement> {
  const { domToCanvas } = await import('modern-screenshot')
  // ⚠️ The picture is drawn from a copy of the page, and a copy cannot see
  // through glass: backdrop-filter drew each card as a dark box cut across
  // its neighbours. While the picture is taken the page draws glass as a
  // nearly solid surface instead, which reads the same on the background.
  const root = document.documentElement
  root.dataset.picture = ''
  try {
    await painted()
    // No colour of its own under the page: the board's background is part of
    // the page and lies below it, and a colour here covered it.
    return await domToCanvas(page, { scale, filter: (node) => !leftOut(node) })
  } finally {
    delete root.dataset.picture
  }
}

/** A file name that says what it is and when: nexdeck-home-2026-10-01.png. */
export function fileName(board: string, now = new Date()): string {
  const slug = board.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'board'
  return `nexdeck-${slug}-${now.toISOString().slice(0, 10)}.png`
}

/** Two frames, so that what was just switched (showcase mode) is drawn before the picture is taken. */
export function painted(): Promise<void> {
  return new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(() => done())))
}
