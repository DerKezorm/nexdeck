/**
 * The stage looks at itself, for the AI's second round (skins, phase C): what
 * reads badly or has vanished, said in words, and where the provider sees
 * pictures, a picture of the stage.
 *
 * Words work with every provider. For each part that carries text the colour
 * of its text is held against the first ground behind it that is not see-
 * through; below 4.5:1 is told. A part that is there but drawn with no size or
 * hidden is told as well.
 *
 * The picture is the stage drawn into an SVG `foreignObject` and from there into
 * a canvas, with every style sheet of the page inlined. Inside the SVG the root
 * is the SVG, so `:root` in those sheets is rewritten to the element that stands
 * in for <html> and carries its marks. Pictures and fonts from addresses do not
 * load inside an SVG drawn as an image; the stage reads without them. Anything
 * that fails gives no picture, and the words go alone.
 */
import { contrast } from '../appearance'
import type { Parts } from './partAt'

/** Parts whose words a person reads. */
export const READ: string[] = ['card-title', 'number', 'button', 'button-primary', 'chip', 'page-nav', 'input', 'tab', 'menu-item', 'dialog-title']
const LEAST = 4.5
const WIDTH = 1024

function rgb(value: string): [number, number, number, number] | null {
  const found = value.match(/rgba?\(([^)]+)\)/)
  if (!found) return null
  const [r, g, b, a = '1'] = found[1].split(/[\s,/]+/).filter(Boolean)
  return [Number(r), Number(g), Number(b), Number(a)]
}

function hex([r, g, b]: [number, number, number, number]): string {
  return '#' + [r, g, b].map((channel) => Math.round(channel).toString(16).padStart(2, '0')).join('')
}

/** The first ground behind an element that is not see-through; a picture as ground says nothing and ends the search. */
function ground(element: Element): string | null {
  for (let at: Element | null = element; at; at = at.parentElement) {
    const style = getComputedStyle(at)
    if (style.backgroundImage && style.backgroundImage !== 'none') return null
    const colour = rgb(style.backgroundColor)
    if (colour && colour[3] >= 0.95) return hex(colour)
  }
  return null
}

export function audit(root: Document, parts: Parts): string[] {
  const found: string[] = []
  for (const name of READ) {
    const part = parts[name]
    if (!part) continue
    let element: Element | null
    try {
      element = root.querySelector(part.selectors.join(', '))
    } catch {
      continue
    }
    if (!element) continue
    const style = getComputedStyle(element)
    const box = element.getBoundingClientRect()
    if (box.width === 0 || box.height === 0 || style.visibility === 'hidden' || Number(style.opacity) < 0.3) {
      found.push(`${name}: is there but cannot be seen`)
      continue
    }
    const ink = rgb(style.color)
    const behind = ground(element)
    if (!ink || !behind) continue
    const ratio = contrast(hex(ink), behind)
    if (ratio < LEAST) found.push(`${name}: its text reads at ${ratio.toFixed(1)}:1 against its ground (at least ${LEAST}:1)`)
  }
  return found
}

export const MODES = ['dark', 'light'] as const
export type Mode = (typeof MODES)[number]
export interface Seen {
  findings: string[]
  pictures: { mode: Mode; image: string }[]
}

/**
 * The stage in dark and then in light mode, each told and drawn, and then as it
 * was. A skin is worn in both: the first real run set its cards dark in css,
 * read well on the dark stage and not at all on the light one, and a look at
 * the mode on show never told. Transitions are stilled meanwhile, or a colour
 * would be read halfway between the two modes.
 */
export async function seeBothModes(root: Document, parts: Parts, picture: boolean, draw: (root: Document) => Promise<string> = capture): Promise<Seen> {
  const html = root.documentElement
  const was = html.getAttribute('data-theme')
  const still = html.hasAttribute('data-stage-still')
  html.setAttribute('data-stage-still', '')
  const seen: Seen = { findings: [], pictures: [] }
  try {
    for (const mode of MODES) {
      html.setAttribute('data-theme', mode)
      seen.findings.push(...audit(root, parts).map((finding) => `${mode}: ${finding}`))
      const image = picture ? await draw(root) : ''
      if (image) seen.pictures.push({ mode, image })
    }
  } finally {
    if (was === null) html.removeAttribute('data-theme')
    else html.setAttribute('data-theme', was)
    if (!still) html.removeAttribute('data-stage-still')
  }
  return seen
}

/** A style sheet in which `:root` means the element standing in for <html> (inside an SVG the root is the SVG). */
export function rootless(sheet: string): string {
  return sheet.replace(/:root\b/g, '[data-capture-root]')
}

/** The stage as a JPEG, base64 without the data: prefix; empty when this browser cannot draw it. */
export async function capture(root: Document): Promise<string> {
  try {
    const html = root.documentElement
    const width = Math.min(html.clientWidth, 1440)
    const height = Math.min(html.scrollHeight, 1200)
    const sheets = [...root.styleSheets]
      .map((sheet) => {
        try {
          return [...sheet.cssRules].map((rule) => rule.cssText).join('\n')
        } catch {
          return ''
        }
      })
      .join('\n')
    const body = root.body.cloneNode(true) as HTMLElement
    body.querySelectorAll('script, iframe').forEach((element) => element.remove())
    // <html> carries the accent and the corners in a style of its own: one style attribute with the size, never two.
    const quoted = (value: string) => value.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;')
    const marks = [...html.attributes].filter((attribute) => attribute.name !== 'style').map((attribute) => `${attribute.name}="${quoted(attribute.value)}"`).join(' ')
    const own = quoted(html.getAttribute('style') ?? '')
    const inner = new XMLSerializer().serializeToString(body)
    // In CDATA: a style sheet holds & and < that XML would read as markup, and one such character draws nothing at all.
    const style = rootless(sheets).replace(/\]\]>/g, ']] >')
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"><foreignObject width="100%" height="100%"><div xmlns="http://www.w3.org/1999/xhtml" data-capture-root="" ${marks} style="${own};width:${width}px;height:${height}px;overflow:hidden"><style><![CDATA[${style}]]></style>${inner}</div></foreignObject></svg>`
    const image = new Image()
    image.decoding = 'sync'
    const loaded = new Promise<void>((resolve, reject) => {
      image.onload = () => resolve()
      image.onerror = () => reject(new Error('the stage could not be drawn'))
    })
    image.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg)
    await loaded
    const scale = Math.min(1, WIDTH / width)
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(width * scale)
    canvas.height = Math.round(height * scale)
    const context = canvas.getContext('2d')
    if (!context) return ''
    context.drawImage(image, 0, 0, canvas.width, canvas.height)
    return canvas.toDataURL('image/jpeg', 0.8).split(',')[1] ?? ''
  } catch {
    // A tainted canvas (Safari) or anything else: the words go without a picture.
    return ''
  }
}
