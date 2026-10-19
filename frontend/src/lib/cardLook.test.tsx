/**
 * The look of a card: its colour, liquid glass and its bent edge, the logo in
 * a container row, the big app tile, the tilt. The colour goes into a style,
 * so what is not a known name or #rrggbb must never get there.
 */
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { CardLookFields } from '../components/CardLookFields'
import { AppTile, renderWidget } from '../components/renderers'
import { WidgetCard } from '../components/WidgetCard'
import { applyAppearance, setBoardStyle, useLook } from './appearance'
import { colourKind, followPointer, inkOn, lookOf, mainColour, tipOf } from './cardLook'
import { iconUrl } from './format'
import { vanishes } from './ground'
import { shiftAt } from './refraction'
import type { WidgetData, WidgetView } from './types'

const card: WidgetView = { id: 7, kind: 'core.clock', title: 'Clock', icon: 'lucide:clock', link: '', renderer: 'value', options: {}, integration_id: null, refresh_seconds: null }

describe('a colour of the card', () => {
  it('is a name from the list, the logo, one of its own, or nothing', () => {
    expect(colourKind('violet')).toBe('palette')
    expect(colourKind('icon')).toBe('icon')
    expect(colourKind('#E57000')).toBe('own')
    for (const stranger of ['', undefined, 'tomato', '#12345', 'red; background: url(x)', 3]) expect(colourKind(stranger)).toBe('none')
  })

  it('reaches the style only as a theme variable or a checked hex', () => {
    expect(lookOf({ card_colour: 'red', card_effect: 'frame' }, '')).toEqual({ className: 'look-frame', style: { '--nd-tone': 'var(--nd-bad)' } })
    expect(lookOf({ card_colour: '#ffffff', card_effect: 'fill' }, '')).toEqual({ className: 'look-fill', style: { '--nd-tone': '#ffffff', '--nd-tone-ink': '#0b1220' } })
    expect(lookOf({ card_colour: 'red; background: url(x)' }, '')).toEqual({ className: '', style: {} })
    // A logo without a colour leaves the card as it is.
    expect(lookOf({ card_colour: 'icon' }, '')).toEqual({ className: '', style: {} })
    expect(lookOf({ card_colour: 'icon', card_effect: 'nonsense' }, '#e5a00d').className).toBe('look-tint')
  })

  it('puts dark text on a bright fill and white on a deep one', () => {
    expect(inkOn('#facc15')).toBe('#0b1220')
    expect(inkOn('#1e3a8a')).toBe('#ffffff')
  })

  it('reads the main colour of a logo from its coloured pixels, not its greys', () => {
    const pixels = new Uint8ClampedArray(4 * 10)
    for (let at = 0; at < 6; at += 1) pixels.set([229, 160, 13, 255], at * 4)
    for (let at = 6; at < 10; at += 1) pixels.set([40, 40, 40, 255], at * 4)
    expect(mainColour(pixels)).toBe('#e5a00d')
    expect(mainColour(new Uint8ClampedArray([255, 255, 255, 255, 0, 0, 0, 255]))).toBe('')
  })

  it('wears its colour on the board', () => {
    const { container } = render(<WidgetCard widget={{ ...card, options: { card_colour: 'green', card_effect: 'fill' } }} data={{ status: 'ok' }} />)
    const frame = container.querySelector('section.card') as HTMLElement
    expect(frame.className).toContain('look-fill')
    expect(frame.style.getPropertyValue('--nd-tone')).toBe('var(--nd-ok)')
  })

  it('is chosen in the settings: a colour, then how it shows', () => {
    const changed = vi.fn()
    const { rerender } = render(<CardLookFields options={{}} icon="plex" onChange={changed} />)
    expect(screen.queryByRole('group')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Violet' }))
    expect(changed).toHaveBeenLastCalledWith({ card_colour: 'violet' })
    fireEvent.click(screen.getByRole('button', { name: 'From the icon' }))
    expect(changed).toHaveBeenLastCalledWith({ card_colour: 'icon' })
    fireEvent.change(screen.getByLabelText('A colour of your own as #rrggbb'), { target: { value: 'E57000' } })
    expect(changed).toHaveBeenLastCalledWith({ card_colour: '#e57000' })
    rerender(<CardLookFields options={{ card_colour: 'violet' }} icon="plex" onChange={changed} />)
    fireEvent.click(screen.getByRole('button', { name: 'Fill' }))
    expect(changed).toHaveBeenLastCalledWith({ card_effect: 'fill' })
  })
})

describe('liquid glass', () => {
  beforeEach(() => {
    delete document.documentElement.dataset.cards
    useLook.setState({ cards: 'glass', board: null, refraction: true })
  })
  afterEach(() => setBoardStyle(null))

  it('is a card style, and a board may wear its own over the installation', () => {
    applyAppearance({ preset: 'cyan', accent: '', css: '', colour: '#22d3ee', card_style: 'liquid', refraction: false })
    expect(document.documentElement.dataset.cards).toBe('liquid')
    expect(document.documentElement.dataset.refract).toBe('off')
    setBoardStyle('neon')
    expect(document.documentElement.dataset.cards).toBe('neon')
    setBoardStyle('wood')
    // An unknown style hands back to the installation.
    expect(document.documentElement.dataset.cards).toBe('liquid')
    setBoardStyle(null)
    expect(document.documentElement.dataset.cards).toBe('liquid')
  })

  it('bends only the rim, inwards, and most at the very edge', () => {
    expect(shiftAt(100, 50, 200, 100, 16, 26)).toEqual([0, 0])
    const [left] = shiftAt(1, 50, 200, 100, 16, 26)
    const [nearer] = shiftAt(10, 50, 200, 100, 16, 26)
    expect(left).toBeGreaterThan(0.8)
    expect(nearer).toBeGreaterThan(0)
    expect(nearer).toBeLessThan(left)
    expect(shiftAt(199, 50, 200, 100, 16, 26)[0]).toBeLessThan(0)
    expect(shiftAt(100, 1, 200, 100, 16, 26)[1]).toBeGreaterThan(0.8)
    // Past the rim the glass is flat.
    expect(shiftAt(40, 50, 200, 100, 16, 26)).toEqual([0, 0])
  })
})

describe('the pointer', () => {
  it('tips a small card further than a big one, and never past its edge', () => {
    expect(tipOf({ width: 200, height: 200 }, 0, 0)).toBe('perspective(700px) rotateX(10.00deg) rotateY(-10.00deg) scale(1.04)')
    expect(tipOf({ width: 600, height: 400 }, 0, 0)).toBe('perspective(700px) rotateX(3.00deg) rotateY(-3.00deg) scale(1.01)')
    expect(tipOf({ width: 200, height: 200 }, 900, -50)).toBe('perspective(700px) rotateX(10.00deg) rotateY(10.00deg) scale(1.04)')
  })
})

describe('following the pointer', () => {
  function cardIn(): { card: HTMLElement; holder: HTMLElement } {
    const holder = document.createElement('div')
    const card = document.createElement('section')
    holder.append(card)
    document.body.append(holder)
    for (const [name, value] of Object.entries({ offsetWidth: 200, offsetHeight: 100, offsetLeft: 0, offsetTop: 0 })) Object.defineProperty(card, name, { value })
    // A tipped card has another outline every time it is asked: that is what made it shake.
    let wobble = 0
    card.getBoundingClientRect = () => ({ left: (wobble += 7), top: wobble, width: 200 + wobble, height: 100 + wobble, right: 0, bottom: 0, x: 0, y: 0, toJSON: () => ({}) })
    return { card, holder }
  }
  const frames: FrameRequestCallback[] = []
  beforeEach(() => {
    frames.length = 0
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => frames.push(callback))
    vi.stubGlobal('cancelAnimationFrame', () => undefined)
  })
  afterEach(() => vi.unstubAllGlobals())
  const flush = () => frames.splice(0).forEach((callback) => callback(0))
  const at = (holder: HTMLElement, x: number, y: number, pointerType = 'mouse') => holder.dispatchEvent(Object.assign(new Event('pointermove'), { clientX: x, clientY: y, pointerType }))

  it('tips by the place of the card, so the same spot gives the same tilt every frame', () => {
    const { card, holder } = cardIn()
    const stop = followPointer(card, () => true)
    const seen: string[] = []
    for (let round = 0; round < 5; round += 1) {
      at(holder, 180, 90)
      flush()
      seen.push(card.style.transform)
    }
    expect(new Set(seen).size).toBe(1)
    expect(seen[0]).toBe(tipOf({ width: 200, height: 100 }, 180, 90))
    holder.dispatchEvent(new Event('pointerleave'))
    expect(card.style.transform).toBe('')
    stop()
  })

  it('moves the glare but does not tip under a finger or with the switch off', () => {
    const { card, holder } = cardIn()
    let tilts = true
    const stop = followPointer(card, () => tilts)
    at(holder, 100, 50, 'touch')
    flush()
    expect(card.style.transform).toBe('')
    expect(card.style.getPropertyValue('--nd-mx')).toBe('50.0%')
    tilts = false
    at(holder, 100, 50)
    flush()
    expect(card.style.transform).toBe('')
    stop()
  })
})

describe('logos', () => {
  it('ask for the variant of the ground they stand on', () => {
    expect(iconUrl('github', 'dark')).toBe('/api/v1/icons/github.svg?on=dark')
    expect(iconUrl('github')).toBe('/api/v1/icons/github.svg')
    expect(iconUrl('https://example.com/x.png', 'dark')).toBe('https://example.com/x.png')
  })

  it('want their variant only when they all but vanish on the ground', () => {
    const black = new Uint8ClampedArray(4 * 40)
    for (let at = 0; at < 40; at += 1) black.set([20, 20, 20, 255], at * 4)
    const orange = new Uint8ClampedArray(4 * 40)
    for (let at = 0; at < 40; at += 1) orange.set([229, 160, 13, 255], at * 4)
    expect(vanishes(black, 'dark')).toBe(true)
    expect(vanishes(black, 'light')).toBe(false)
    expect(vanishes(orange, 'dark')).toBe(false)
    expect(vanishes(orange, 'light')).toBe(false)
  })

  it('stand beside a container, with the dot on their corner', () => {
    const view = { ...card, kind: 'docker.containers', renderer: 'list' } as WidgetView
    const data: WidgetData = { status: 'ok', items: [{ id: 'a', title: 'qbittorrent', icon: 'qbittorrent', icon_dot: true, status: 'ok' }, { id: 'b', title: 'nightly', status: 'bad' }] }
    const { container } = render(<>{renderWidget({ widget: view, data })}</>)
    const rows = container.querySelectorAll('li')
    expect(rows[0].querySelector('img')?.getAttribute('src')).toContain('/api/v1/icons/qbittorrent.svg')
    expect(rows[0].querySelector('.dot')?.getAttribute('data-status')).toBe('ok')
    expect(rows[1].querySelector('img')).toBeNull()
    expect(rows[1].querySelector('.dot')?.getAttribute('data-status')).toBe('bad')
  })
})

describe('the app tile as a big icon', () => {
  const tile: WidgetView = { id: 4, kind: 'core.app', title: 'Plex', icon: 'plex', link: 'https://plex.example.com', renderer: 'app', options: { look: 'icon' }, integration_id: null, refresh_seconds: null }
  const health = { enabled: true, last_ok: true, last_error: '', last_latency_ms: 12, bars: [1, 1, 0.2] } as unknown as WidgetView['health']

  it('shows the name, the logo and a dot in the corner', () => {
    render(<AppTile widget={{ ...tile, health }} data={{ status: 'ok' }} />)
    const big = screen.getByTestId('app-big')
    expect(big).toHaveTextContent('Plex')
    expect(big.querySelector('.dot')).not.toBeNull()
    expect(screen.queryByTestId('availability-bars')).toBeNull()
  })

  it('shows the bars along the bottom when asked to', () => {
    render(<AppTile widget={{ ...tile, health, options: { look: 'icon', corner: 'bars' } }} data={{ status: 'ok' }} />)
    expect(screen.getByTestId('availability-bars')).toBeTruthy()
    expect(screen.getByTestId('app-big').querySelector('.dot')).toBeNull()
  })

  it('stays the row it always was without the option', () => {
    render(<AppTile widget={{ ...tile, health, options: {} }} data={{ status: 'ok' }} />)
    expect(screen.queryByTestId('app-big')).toBeNull()
    expect(screen.getByTestId('availability-bars')).toBeTruthy()
  })
})
