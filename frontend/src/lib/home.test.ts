import { vi } from 'vitest'

import {
  FOOTPRINT, freshId, hsToRgb, LAMP_STYLES, lampSender, lampSpots, mergeWish, nextSpot, phoneGroups, readingOrder, rgbToHs, ROW_WIDTH, snap, surfaceHeight, withLamps, withWish,
  type HomeAnswer, type HomeElement, type LampStyle, type LampWish,
} from './home'

const heading = (id: string, x: number, y: number): HomeElement => ({ id, type: 'heading', x, y, text: id })

it('snaps to the step of the surface and stays on it', () => {
  expect(snap(59)).toBe(56)
  expect(snap(60)).toBe(64)
  expect(snap(-30)).toBe(0)
  expect(snap(1e9)).toBe(20000)
})

it('reads elements placed side by side as one row, left to right', () => {
  const order = readingOrder([heading('kitchen', 320, 0), heading('outside', 656, 0), heading('living', 16, 16), heading('upstairs', 16, 200)])
  expect(order.map((element) => element.id)).toEqual(['living', 'kitchen', 'outside', 'upstairs'])
})

it('starts a new row once an element stands clearly lower', () => {
  const order = readingOrder([heading('b', 400, 48), heading('a', 16, 0)])
  expect(order.map((element) => element.id)).toEqual(['a', 'b'])
})

it('puts a new element below the lowest one, or in the corner of an empty page', () => {
  expect(nextSpot([])).toEqual({ x: 16, y: 16 })
  // Below where the lowest one ends (a heading is 24 high), with a gap of 16.
  expect(nextSpot([heading('a', 300, 16), heading('b', 16, 120)])).toEqual({ x: 16, y: 160 })
})

it('gives an id no element has, of the characters the server keeps', () => {
  const taken = [heading('h0', 0, 0)]
  let calls = 0
  const id = freshId(taken, () => (calls++ === 0 ? 0 : 0.5))
  expect(id).not.toBe('h0')
  expect(id).toMatch(/^[A-Za-z0-9_-]{1,32}$/)
})

it('leaves room below the lowest element', () => {
  expect(surfaceHeight([])).toBe(160)
  expect(surfaceHeight([heading('a', 0, 400)])).toBe(584)
})

it('puts news of a lamp into the answer, keeping what the news does not say', () => {
  const answer: HomeAnswer = {
    version: 1,
    problem: null,
    layout: { integration_id: 1, elements: [
      { id: 'floor', type: 'light', x: 0, y: 0, rid: 'r-floor', entity_id: 'light.floor_lamp', name: 'Floor lamp', style: 'pill' },
      { id: 'desk', type: 'light', x: 0, y: 0, rid: 'r-desk', entity_id: 'light.desk', name: 'Desk', style: 'pill' },
    ] },
    lights: {
      floor: { rid: 'r-floor', entity_id: 'light.floor_lamp', name: 'Floor lamp', area: 'Living room', device: '', group: false, on: true, unavailable: false, pct: 62, rgb: null, kelvin: 2400, dims: true, temperature: true, colour: true, missing: false },
      desk: { missing: true },
    },
  }
  const next = withLamps(answer, { floor: { on: false, pct: null, kelvin: null, missing: false }, desk: { on: true, missing: false }, stranger: { on: true, missing: false } })
  expect(next.lights?.floor).toMatchObject({ name: 'Floor lamp', area: 'Living room', on: false, pct: null, missing: false })
  expect(next.lights?.desk).toEqual({ on: true, missing: false })
  expect(next.lights).not.toHaveProperty('stranger')
  expect(withLamps(next, { floor: { missing: true } }).lights?.floor).toEqual({ missing: true })
  // The answer it started from stays as it was: react-query compares by reference.
  expect(answer.lights?.floor).toMatchObject({ on: true })
})

// -- what is asked of a lamp ---------------------------------------------------

it('merges wishes with the later one winning, off taking everything with it', () => {
  expect(mergeWish({ brightness_pct: 30 }, { brightness_pct: 70 })).toEqual({ brightness_pct: 70 })
  expect(mergeWish({ brightness_pct: 30, kelvin: 2700 }, { on: false })).toEqual({ on: false })
  expect(mergeWish({ on: false }, { brightness_pct: 40 })).toEqual({ on: true, brightness_pct: 40 })
  expect(mergeWish({ brightness_pct: 30, hs: [10, 10] }, { kelvin: 3000 })).toEqual({ brightness_pct: 30, kelvin: 3000 })
  expect(mergeWish({ kelvin: 3000 }, { hs: [200, 50] })).toEqual({ hs: [200, 50] })
})

it('reckons a hue and saturation into a colour as Home Assistant does', () => {
  expect(hsToRgb(0, 100)).toEqual([255, 0, 0])
  expect(hsToRgb(120, 100)).toEqual([0, 255, 0])
  expect(hsToRgb(240, 100)).toEqual([0, 0, 255])
  expect(hsToRgb(360, 100)).toEqual([255, 0, 0])
  expect(hsToRgb(30, 50)).toEqual([255, 191, 128])
  expect(hsToRgb(200, 0)).toEqual([255, 255, 255])
})

it('reckons a colour back into hue and saturation', () => {
  expect(rgbToHs([255, 0, 0])).toEqual([0, 100])
  expect(rgbToHs([0, 0, 255])).toEqual([240, 100])
  expect(rgbToHs([160, 90, 255])).toEqual([265.5, 64.7])
  expect(rgbToHs([255, 0, 128])).toEqual([329.9, 100])
  expect(rgbToHs([255, 255, 255])).toEqual([0, 0])
  expect(rgbToHs([0, 0, 0])).toEqual([0, 0])
  for (const [h, s] of [[30, 50], [200, 80], [300, 25]] as [number, number][]) {
    const [back, sat] = rgbToHs(hsToRgb(h, s))
    expect(Math.abs(back - h)).toBeLessThan(1.5)
    expect(Math.abs(sat - s)).toBeLessThan(1.5)
  }
})

it('shows a lamp as it will stand once the wish is done', () => {
  const lamp = { rid: 'r', entity_id: 'light.a', name: 'A', area: '', device: '', group: false, on: false, unavailable: false, pct: null, rgb: null, kelvin: null, dims: true, temperature: true, colour: true }
  expect(withWish(lamp, { on: true })).toMatchObject({ on: true, pct: 100 })
  expect(withWish(lamp, { brightness_pct: 25 })).toMatchObject({ on: true, pct: 25 })
  expect(withWish({ ...lamp, on: true, pct: 60, rgb: [1, 2, 3] }, { kelvin: 2700 })).toMatchObject({ on: true, pct: 60, kelvin: 2700, rgb: null })
  expect(withWish({ ...lamp, on: true, pct: 60, kelvin: 2700 }, { hs: [240, 100] })).toMatchObject({ rgb: [0, 0, 255], kelvin: null, hs: [240, 100] })
  expect(withWish({ ...lamp, on: true, pct: 60 }, { on: false })).toMatchObject({ on: false, pct: null })
  expect(withWish(lamp, undefined)).toBe(lamp)
})

it('sends a lamp the newest wish, never two at once, and at most every gap', async () => {
  vi.useFakeTimers()
  try {
    const sent: LampWish[] = []
    const answers: (() => void)[] = []
    const sender = lampSender((wish) => {
      sent.push(wish)
      return new Promise<void>((resolve) => answers.push(resolve))
    }, 300)
    sender.ask({ brightness_pct: 10 })
    expect(sender.queued()).toBe(false)
    sender.ask({ brightness_pct: 20 })
    sender.ask({ brightness_pct: 30 })
    expect(sent).toEqual([{ brightness_pct: 10 }])
    expect(sender.busy()).toBe(true)
    expect(sender.queued()).toBe(true)
    await vi.advanceTimersByTimeAsync(400)
    // The gap has passed, but the first is still on its way.
    expect(sent).toHaveLength(1)
    answers[0]()
    await vi.advanceTimersByTimeAsync(0)
    expect(sent).toEqual([{ brightness_pct: 10 }, { brightness_pct: 30 }])
    sender.ask({ kelvin: 3000 })
    answers[1]()
    await vi.advanceTimersByTimeAsync(400)
    expect(sent.at(-1)).toEqual({ kelvin: 3000 })
    answers[2]()
    await vi.advanceTimersByTimeAsync(0)
    expect(sender.busy()).toBe(false)
  } finally {
    vi.useRealTimers()
  }
})

// -- styles and the phone ------------------------------------------------------

const lampAt = (id: string, x: number, y: number, style: LampStyle = 'pill'): HomeElement => ({ id, type: 'light', x, y, rid: `r-${id}`, entity_id: `light.${id}`, name: id, style })

it('places lamps of each style side by side without one covering the next', () => {
  for (const style of LAMP_STYLES) {
    const spots = lampSpots([], 30, style)
    const { width, height } = FOOTPRINT[style]
    for (const [index, a] of spots.entries()) {
      for (const b of spots.slice(index + 1)) {
        const apart = b.x >= a.x + width || a.x >= b.x + width || b.y >= a.y + height || a.y >= b.y + height
        expect(apart, `${style} ${JSON.stringify(a)} ${JSON.stringify(b)}`).toBe(true)
      }
    }
    expect(Math.max(...spots.map((spot) => spot.x + width))).toBeLessThanOrEqual(16 + ROW_WIDTH)
  }
  expect(lampSpots([], 13, 'round').filter((spot) => spot.y === 16)).toHaveLength(12)
})

it('places new lamps below where a tall one ends, not where it begins', () => {
  const [spot] = lampSpots([lampAt('dots', 16, 16, 'dots')], 1, 'pill')
  expect(spot.y).toBeGreaterThanOrEqual(16 + FOOTPRINT.dots.height)
  expect(nextSpot([lampAt('bulb', 16, 16, 'bulb')]).y).toBeGreaterThanOrEqual(16 + FOOTPRINT.bulb.height)
  expect(surfaceHeight([lampAt('dots', 0, 400, 'dots')])).toBe(400 + FOOTPRINT.dots.height + 160)
})

it('reads a phone page as each heading with the lamps standing under it', () => {
  const groups = phoneGroups([
    heading('living', 16, 16), heading('kitchen', 320, 16), heading('garden', 660, 20),
    lampAt('early', 400, 0, 'round'),
    lampAt('sofa', 16, 56), lampAt('stove', 330, 56, 'round'), lampAt('path', 660, 56, 'rocker'),
    lampAt('reading', 16, 104),
    heading('bed', 16, 200), lampAt('bedside', 40, 240, 'bulb'),
    // Its middle (288 + 128) stands under the kitchen.
    lampAt('counter', 288, 104),
  ])
  expect(groups.map((group) => [group.heading?.id ?? null, group.lamps.map((lamp) => lamp.id)])).toEqual([
    [null, ['early']],
    ['living', ['sofa', 'reading']],
    ['kitchen', ['stove', 'counter']],
    ['garden', ['path']],
    ['bed', ['bedside']],
  ])
})

it('keeps a heading on the phone that has no lamps yet, and leaves out an empty top', () => {
  expect(phoneGroups([heading('a', 16, 16), lampAt('x', 16, 56)]).map((group) => group.heading?.id ?? null)).toEqual(['a'])
  expect(phoneGroups([heading('a', 16, 16), heading('b', 320, 16)]).map((group) => group.lamps.length)).toEqual([0, 0])
})
