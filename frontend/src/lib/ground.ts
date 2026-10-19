/**
 * Whether the page is dark or light right now, for what has to pick a variant
 * by it: a logo asks the server for the one that reads on this ground.
 *
 * Read from the page itself (``data-theme`` on the root), watched for changes,
 * because more than one place sets it: the profile, the system's setting, a
 * kiosk link with ``?theme=``.
 */
import { create } from 'zustand'

export type Ground = 'dark' | 'light'

function read(): Ground {
  return typeof document !== 'undefined' && document.documentElement.dataset.theme === 'light' ? 'light' : 'dark'
}

export const useGround = create<{ mode: Ground }>(() => ({ mode: read() }))

if (typeof MutationObserver !== 'undefined' && typeof document !== 'undefined') {
  new MutationObserver(() => {
    const mode = read()
    if (useGround.getState().mode !== mode) useGround.setState({ mode })
  }).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
}

/**
 * Whether a logo all but vanishes on this ground: most of its drawn pixels
 * near black on a dark page, or near white on a light one. Only then is the
 * variant asked for. Most logos read on both grounds in their own colours,
 * and their light variants are often plain white: asked for every logo, the
 * colours of Radarr, Sonarr and Jellyfin went (seen on 19.10.2026).
 */
export function vanishes(pixels: Uint8ClampedArray, ground: Ground): boolean {
  let drawn = 0
  let lost = 0
  for (let at = 0; at < pixels.length; at += 4) {
    if (pixels[at + 3] < 200) continue
    drawn += 1
    const high = Math.max(pixels[at], pixels[at + 1], pixels[at + 2])
    const low = Math.min(pixels[at], pixels[at + 1], pixels[at + 2])
    if (ground === 'dark' ? high < 70 : low > 205) lost += 1
  }
  return drawn >= 20 && lost / drawn > 0.6
}

const verdicts = new Map<string, boolean>()

/** What was found for a logo on a ground, or undefined while nobody has looked. */
export function verdictFor(url: string, ground: Ground): boolean | undefined {
  return verdicts.get(`${url}|${ground}`)
}

/** Look at a loaded logo once and remember whether it vanishes on this ground. */
export function judge(picture: HTMLImageElement, url: string, ground: Ground): boolean {
  const key = `${url}|${ground}`
  const known = verdicts.get(key)
  if (known !== undefined) return known
  let verdict = false
  try {
    const canvas = document.createElement('canvas')
    canvas.width = 32
    canvas.height = 32
    const context = canvas.getContext('2d', { willReadFrequently: true })
    if (context) {
      context.drawImage(picture, 0, 0, 32, 32)
      verdict = vanishes(context.getImageData(0, 0, 32, 32).data, ground)
    }
  } catch {
    // A logo from another address taints the canvas: it stays as it is.
  }
  verdicts.set(key, verdict)
  return verdict
}
