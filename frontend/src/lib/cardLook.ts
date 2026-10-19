/**
 * A card's own colour and how it shows (the card's settings, Look), and the
 * colour a logo has.
 *
 * The first four colours are the theme's own (accent, ok, warn, bad), so a
 * theme recolours them; the other four are nexdeck's. A colour of one's own
 * stays as it is. The server checks the same list before it stores one.
 */
import { useEffect, useState } from 'react'

import { channels } from './appearance'
import { iconUrl } from './format'

export const PALETTE = ['accent', 'blue', 'violet', 'pink', 'red', 'orange', 'yellow', 'green'] as const
export type PaletteColour = (typeof PALETTE)[number]
export const EFFECTS = ['frame', 'tint', 'fill'] as const
export type Effect = (typeof EFFECTS)[number]

const VARIABLE: Record<PaletteColour, string> = {
  accent: 'var(--nd-accent)',
  blue: 'var(--nd-c-blue)',
  violet: 'var(--nd-c-violet)',
  pink: 'var(--nd-c-pink)',
  red: 'var(--nd-bad)',
  orange: 'var(--nd-c-orange)',
  yellow: 'var(--nd-warn)',
  green: 'var(--nd-ok)',
}
const HEX = /^#[0-9a-f]{6}$/i

/** What a stored colour is: none, one from the list, the logo's, or one of one's own. */
export function colourKind(value: unknown): 'none' | 'palette' | 'icon' | 'own' {
  if (typeof value !== 'string' || !value) return 'none'
  if (value === 'icon') return 'icon'
  if ((PALETTE as readonly string[]).includes(value)) return 'palette'
  return HEX.test(value) ? 'own' : 'none'
}

export function effectOf(value: unknown): Effect {
  return (EFFECTS as readonly string[]).includes(value as string) ? (value as Effect) : 'tint'
}

/** The text that reads on a fill of this colour: dark on a bright one, white on a deep one. */
export function inkOn(colour: string): string {
  const parts = channels(colour)
  if (!parts) return ''
  const [r, g, b] = parts.map((value) => {
    const c = value / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.42 ? '#0b1220' : '#ffffff'
}

const logoColours = new Map<string, string>()

/**
 * The main colour of a logo: the biggest group of clearly coloured pixels, by
 * hue. Greys, near black and near white do not count, so a white logo on a
 * red ground is red. Empty when the logo has no colour to speak of.
 */
export function mainColour(pixels: Uint8ClampedArray): string {
  const groups = new Map<number, { n: number; r: number; g: number; b: number }>()
  for (let at = 0; at < pixels.length; at += 4) {
    if (pixels[at + 3] < 200) continue
    const r = pixels[at]
    const g = pixels[at + 1]
    const b = pixels[at + 2]
    const max = Math.max(r, g, b)
    const min = Math.min(r, g, b)
    if (max < 40 || max - min < 40) continue
    let hue: number
    if (max === r) hue = ((g - b) / (max - min)) % 6
    else if (max === g) hue = (b - r) / (max - min) + 2
    else hue = (r - g) / (max - min) + 4
    const key = Math.round((((hue * 60) % 360) + 360) % 360 / 20)
    const group = groups.get(key) ?? { n: 0, r: 0, g: 0, b: 0 }
    group.n += 1
    group.r += r
    group.g += g
    group.b += b
    groups.set(key, group)
  }
  let best: { n: number; r: number; g: number; b: number } | null = null
  for (const group of groups.values()) if (!best || group.n > best.n) best = group
  if (!best) return ''
  const hex = (value: number) => Math.round(value).toString(16).padStart(2, '0')
  return `#${hex(best.r / best.n)}${hex(best.g / best.n)}${hex(best.b / best.n)}`
}

/**
 * The main colour of a card's logo, worked out once per logo in the browser.
 * The logo comes from nexdeck's own address, so the canvas may read it.
 */
export function useLogoColour(icon: string | undefined, wanted: boolean): string {
  const url = wanted ? iconUrl(icon) : null
  const [colour, setColour] = useState(() => (url ? logoColours.get(url) ?? '' : ''))
  useEffect(() => {
    if (!url) return
    const known = logoColours.get(url)
    if (known !== undefined) {
      setColour(known)
      return
    }
    let gone = false
    const picture = new Image()
    picture.onload = () => {
      try {
        const canvas = document.createElement('canvas')
        canvas.width = 48
        canvas.height = 48
        const context = canvas.getContext('2d', { willReadFrequently: true })
        if (!context) return
        context.drawImage(picture, 0, 0, 48, 48)
        const found = mainColour(context.getImageData(0, 0, 48, 48).data)
        logoColours.set(url, found)
        if (!gone) setColour(found)
      } catch {
        // A logo from another address taints the canvas; the card stays without the colour.
        logoColours.set(url, '')
      }
    }
    picture.src = url
    return () => {
      gone = true
    }
  }, [url])
  return url ? colour : ''
}

/** The style and classes a card wears for its colour, or nothing. */
export function lookOf(options: Record<string, unknown> | undefined, logo: string): { className: string; style: Record<string, string> } {
  const value = options?.card_colour
  const kind = colourKind(value)
  if (kind === 'none') return { className: '', style: {} }
  const effect = effectOf(options?.card_effect)
  let tone = ''
  let ink = ''
  if (kind === 'palette') tone = VARIABLE[value as PaletteColour]
  else if (kind === 'own') {
    tone = String(value)
    ink = inkOn(tone)
  } else if (logo) {
    tone = logo
    ink = inkOn(logo)
  }
  if (!tone) return { className: '', style: {} }
  return { className: `look-${effect}`, style: ink ? { '--nd-tone': tone, '--nd-tone-ink': ink } : { '--nd-tone': tone } }
}

/** What the pointer does to a card: it tips towards it, more for a small one. */
export function tipOf(box: { width: number; height: number }, x: number, y: number): string {
  const big = box.width > 360 || box.height > 360
  const most = big ? 3 : 10
  const lift = big ? 1.01 : 1.04
  const across = Math.min(1, Math.max(0, x / box.width))
  const down = Math.min(1, Math.max(0, y / box.height))
  return `perspective(700px) rotateX(${((0.5 - down) * 2 * most).toFixed(2)}deg) rotateY(${((across - 0.5) * 2 * most).toFixed(2)}deg) scale(${lift})`
}

/**
 * Let a card follow the pointer: the glare always, the tilt when ``tilts``
 * says so. Hands back what undoes it.
 *
 * ⚠️ Measured against the card's place, never against the card. A tipped and
 * lifted card has another outline, and the tilt read from that outline gave
 * another tilt, frame after frame: it shook, worst while crossing the lines
 * of a card with history. At its edge the pointer even fell off the tipped
 * card, it sprang back and caught the pointer again. The place (offsetLeft,
 * offsetTop and the size before transforms) does not move, and the listener
 * sits on the parent, which does not tip.
 */
export function followPointer(card: HTMLElement, tilts: () => boolean): () => void {
  const holder = card.parentElement
  if (!holder) return () => undefined
  let frame = 0
  let last: { x: number; y: number; mouse: boolean } | null = null
  const place = () => {
    const parent = card.offsetParent as HTMLElement | null
    const base = parent ? parent.getBoundingClientRect() : { left: 0, top: 0 }
    return { left: base.left + card.offsetLeft - (parent?.scrollLeft ?? 0), top: base.top + card.offsetTop - (parent?.scrollTop ?? 0), width: card.offsetWidth, height: card.offsetHeight }
  }
  const paint = () => {
    frame = 0
    if (!last) return
    const box = place()
    if (!box.width || !box.height) return
    const x = last.x - box.left
    const y = last.y - box.top
    card.style.setProperty('--nd-mx', `${((x / box.width) * 100).toFixed(1)}%`)
    card.style.setProperty('--nd-my', `${((y / box.height) * 100).toFixed(1)}%`)
    if (!last.mouse || !tilts() || window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches) return
    card.classList.add('is-tipping')
    card.style.transform = tipOf(box, x, y)
  }
  const move = (event: PointerEvent) => {
    last = { x: event.clientX, y: event.clientY, mouse: event.pointerType === 'mouse' }
    if (!frame) frame = requestAnimationFrame(paint)
  }
  const leave = () => {
    last = null
    if (frame) cancelAnimationFrame(frame)
    frame = 0
    card.classList.remove('is-tipping')
    card.style.transform = ''
    card.style.removeProperty('--nd-mx')
    card.style.removeProperty('--nd-my')
  }
  holder.addEventListener('pointermove', move)
  holder.addEventListener('pointerleave', leave)
  return () => {
    holder.removeEventListener('pointermove', move)
    holder.removeEventListener('pointerleave', leave)
    leave()
  }
}
