/**
 * The bent edge of liquid glass: inside a rim the background is pulled in
 * from further inside, the way a thick glass edge bends what lies behind it.
 *
 * Each card gets an SVG filter of its own size with a displacement map, and
 * puts it into its backdrop-filter. Only Chromium takes an SVG filter there;
 * Safari and Firefox draw the glass without the bend, which is why this is
 * asked before anything is made.
 *
 * ⚠️ Chrome runs a backdrop filter in device pixels. Sized in CSS pixels, the
 * map covered two thirds of a card at 150 % and the rest slid sideways,
 * measured in the mock-up on 19.10.2026. Map and scale are multiplied by the
 * device pixel ratio.
 */

/** How far in from the edge the glass bends, and how far it shifts there, in CSS pixels. */
export const RIM = 26
export const SHIFT = 18

/** Whether this browser bends a backdrop through an SVG filter. */
export function canRefract(): boolean {
  if (typeof navigator === 'undefined' || typeof CSS === 'undefined') return false
  const ua = navigator.userAgent
  // Chromium and its kin; Safari says "Safari" without "Chrome", Firefox neither.
  return /Chrome\/|Chromium\//.test(ua) && !/Firefox\//.test(ua) && CSS.supports('backdrop-filter', 'url(#x)')
}

/**
 * The shift at one point of a rounded box of ``width`` by ``height`` with
 * corners of ``radius``, as two numbers from -1 to 1. Nothing in the middle;
 * towards the edge it grows with the square of how near the edge it is, and
 * points inwards, so the glass shows what lies further in.
 */
export function shiftAt(x: number, y: number, width: number, height: number, radius: number, rim: number): [number, number] {
  const halfW = width / 2
  const halfH = height / 2
  const ox = x - halfW
  const oy = y - halfH
  const r = Math.min(radius, halfW, halfH)
  const qx = Math.abs(ox) - (halfW - r)
  const qy = Math.abs(oy) - (halfH - r)
  const outside = Math.hypot(Math.max(qx, 0), Math.max(qy, 0))
  const depth = -(outside + Math.min(Math.max(qx, qy), 0) - r)
  if (depth <= 0 || depth >= rim) return [0, 0]
  let nx: number
  let ny: number
  if (qx > 0 && qy > 0) {
    const length = Math.hypot(qx, qy) || 1
    nx = (qx / length) * Math.sign(ox)
    ny = (qy / length) * Math.sign(oy)
  } else if (qx > qy) {
    nx = Math.sign(ox)
    ny = 0
  } else {
    nx = 0
    ny = Math.sign(oy)
  }
  const near = 1 - depth / rim
  const strength = near * near
  return [-nx * strength, -ny * strength]
}

const maps = new Map<string, string>()

/** The displacement map of one size as a picture: red and green carry the shift, 128 is none. */
function mapFor(width: number, height: number, radius: number): string {
  const key = `${width}x${height}x${radius}`
  const known = maps.get(key)
  if (known) return known
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const context = canvas.getContext('2d')
  if (!context) return ''
  const picture = context.createImageData(width, height)
  const data = picture.data
  const rim = Math.min(RIM, Math.min(width, height) / 4)
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const [dx, dy] = shiftAt(x + 0.5, y + 0.5, width, height, radius, rim)
      const at = (y * width + x) * 4
      data[at] = 128 + dx * 127
      data[at + 1] = 128 + dy * 127
      data[at + 2] = 128
      data[at + 3] = 255
    }
  }
  context.putImageData(picture, 0, 0)
  const url = canvas.toDataURL()
  // A board has a handful of sizes; a resized window adds some. Not without end.
  if (maps.size > 60) maps.delete(maps.keys().next().value as string)
  maps.set(key, url)
  return url
}

const SVG = 'http://www.w3.org/2000/svg'

/** The one hidden <svg> the filters live in. */
function holder(): SVGDefsElement {
  let defs = document.getElementById('nd-refraction') as SVGDefsElement | null
  if (defs) return defs
  const svg = document.createElementNS(SVG, 'svg')
  svg.setAttribute('width', '0')
  svg.setAttribute('height', '0')
  svg.setAttribute('aria-hidden', 'true')
  svg.style.position = 'absolute'
  defs = document.createElementNS(SVG, 'defs') as SVGDefsElement
  defs.id = 'nd-refraction'
  svg.append(defs)
  document.body.append(svg)
  return defs
}

/**
 * Bend the edge of one element. Hands back what undoes it. The filter follows
 * the element's size; ``radius`` is its corner in CSS pixels.
 */
export function refract(element: HTMLElement, id: string, radius: number): () => void {
  const filter = document.createElementNS(SVG, 'filter')
  filter.id = id
  filter.setAttribute('color-interpolation-filters', 'sRGB')
  filter.setAttribute('filterUnits', 'userSpaceOnUse')
  filter.setAttribute('primitiveUnits', 'userSpaceOnUse')
  const image = document.createElementNS(SVG, 'feImage')
  image.setAttribute('result', 'map')
  image.setAttribute('preserveAspectRatio', 'none')
  const shift = document.createElementNS(SVG, 'feDisplacementMap')
  shift.setAttribute('in', 'SourceGraphic')
  shift.setAttribute('in2', 'map')
  shift.setAttribute('xChannelSelector', 'R')
  shift.setAttribute('yChannelSelector', 'G')
  filter.append(image, shift)
  holder().append(filter)

  const size = () => {
    const box = element.getBoundingClientRect()
    const width = Math.round(box.width)
    const height = Math.round(box.height)
    if (!width || !height) return
    const ratio = window.devicePixelRatio || 1
    const deviceWidth = Math.round(width * ratio)
    const deviceHeight = Math.round(height * ratio)
    for (const node of [filter, image]) {
      node.setAttribute('x', '0')
      node.setAttribute('y', '0')
      node.setAttribute('width', String(deviceWidth))
      node.setAttribute('height', String(deviceHeight))
    }
    shift.setAttribute('scale', String(Math.round(SHIFT * 2 * ratio)))
    image.setAttribute('href', mapFor(width, height, radius))
    const value = `blur(4px) url(#${id}) saturate(185%) brightness(1.06)`
    element.style.backdropFilter = value
  }
  size()
  const watcher = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(size)
  watcher?.observe(element)
  // The ratio changes with the browser's zoom and when a window moves to another screen.
  window.addEventListener('resize', size)
  return () => {
    watcher?.disconnect()
    window.removeEventListener('resize', size)
    element.style.backdropFilter = ''
    filter.remove()
  }
}
