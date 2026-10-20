import { vi } from 'vitest'

import {
  alignTo, byHand, CLIMATE_FOOTPRINT, handStep, CLIMATE_FOOTPRINTS, climateSpots, controlWidth, heightOf, isWide, shareOf, targetAt, DEFAULT_WIDTH, FOOTPRINT, isResizable, MAX_WIDTH, MIN_WIDTH, resizeTo, widthOf, freshId, hsToRgb, LAMP_STYLES, lampSender, lampSpots, mergeWish, nextSpot, phoneGroups, readingOrder, rgbToHs, ROW_WIDTH, snap,
  stepTarget, surfaceHeight, temperature, withLamps, withNews, withWish,
  type HomeAnswer, type HomeClimate, type HomeElement, type HomeLight, type LampStyle, type LampWish,
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
  expect(groups.map((group) => [group.heading?.id ?? null, group.devices.map((lamp) => lamp.id)])).toEqual([
    [null, ['early']],
    ['living', ['sofa', 'reading']],
    ['kitchen', ['stove', 'counter']],
    ['garden', ['path']],
    ['bed', ['bedside']],
  ])
})

it('keeps a heading on the phone that has no lamps yet, and leaves out an empty top', () => {
  expect(phoneGroups([heading('a', 16, 16), lampAt('x', 16, 56)]).map((group) => group.heading?.id ?? null)).toEqual(['a'])
  expect(phoneGroups([heading('a', 16, 16), heading('b', 320, 16)]).map((group) => group.devices.length)).toEqual([0, 0])
})

// -- thermostats ---------------------------------------------------------------

it('moves a target on the thermostat\'s own step and keeps it inside its bounds', () => {
  const thermostat = { step: 0.5, min: 7, max: 30 }
  expect(stepTarget(thermostat, 21.5, 1)).toBe(22)
  expect(stepTarget(thermostat, 21.5, -3)).toBe(20)
  expect(stepTarget(thermostat, 21.3, 0)).toBe(21.5)
  expect(stepTarget(thermostat, 29.5, 4)).toBe(30)
  expect(stepTarget(thermostat, 7.5, -4)).toBe(7)
  expect(stepTarget({ step: 0.1, min: 5, max: 25 }, 20, 3)).toBe(20.3)
  expect(stepTarget({ step: 1, min: 45, max: 90 }, 68, 1)).toBe(69)
  expect(stepTarget({ step: 0, min: 7, max: 30 }, 20, 1)).toBe(20.5)
})

it('writes a temperature with a decimal only where it has one', () => {
  expect(temperature(21)).toBe('21°')
  expect(temperature(21.5)).toBe('21.5°')
  expect(temperature(21.25)).toBe('21.3°')
  expect(temperature(null)).toBe('–')
})

it('puts news of a thermostat into the answer, keeping its name and leaving strangers out', () => {
  const answer: HomeAnswer = {
    version: 1,
    problem: null,
    layout: { integration_id: 1, elements: [{ id: 'heat', type: 'climate', x: 0, y: 0, rid: 'r', entity_id: 'climate.a', name: 'A', style: 'pill', sensor: null }] },
    climates: { heat: { name: 'Living room', area: 'Living room', reading: 20, target: 21, missing: false } as never },
  }
  const next = withNews(answer, { page_id: 1, climates: { heat: { reading: 22, missing: false }, stranger: { reading: 1, missing: false } } })
  expect(next.climates?.heat).toMatchObject({ name: 'Living room', reading: 22, target: 21 })
  expect(next.climates).not.toHaveProperty('stranger')
  expect(withNews(next, { page_id: 1, climates: { heat: { missing: true } } }).climates?.heat).toEqual({ missing: true })
  expect(withNews(answer, { page_id: 1 })).toBe(answer)
})

it('reads a thermostat on a phone under its heading, as a lamp', () => {
  const climate = (id: string, x: number, y: number): HomeElement => ({ id, type: 'climate', x, y, rid: `r-${id}`, entity_id: `climate.${id}`, name: id, style: 'pill', sensor: null })
  const groups = phoneGroups([heading('down', 16, 16), heading('up', 400, 16), climate('living', 16, 56), climate('bed', 400, 56), lampAt('lamp', 16, 104)])
  expect(groups.map((group) => [group.heading?.id, group.devices.map((device) => device.id)])).toEqual([['down', ['living', 'lamp']], ['up', ['bed']]])
  const spots = climateSpots([], 6)
  for (const [index, a] of spots.entries()) for (const b of spots.slice(index + 1)) expect(b.x >= a.x + CLIMATE_FOOTPRINT.width || b.y >= a.y + CLIMATE_FOOTPRINT.height).toBe(true)
})

// -- guides and widths -----------------------------------------------------------

const box = (x: number, y: number, width = 100, height = 40) => ({ x, y, width, height })

it('snaps a dragged box onto the edges and middles of the others, the nearest one winning', () => {
  const others = [box(100, 20), box(400, 300, 200)]
  // Its left edge 4 px from the other's: onto it, with a line from the top of one to the bottom of the other.
  const left = alignTo(box(104, 180), { x: 104, y: 184 }, others)
  expect(left.x).toBe(100)
  expect(left.y).toBe(184)
  expect(left.guides).toEqual([{ axis: 'x', at: 100, from: 20, to: 224 }])
  // Its middle onto the other's middle (450 + 50 = 500).
  expect(alignTo(box(447, 120), { x: 448, y: 120 }, others).x).toBe(450)
  // Its top onto the other's bottom: 60, from 63.
  const below = alignTo(box(240, 63), { x: 240, y: 64 }, others)
  expect(below.y).toBe(60)
  expect(below.guides).toEqual([{ axis: 'y', at: 60, from: 100, to: 340 }])
  // Nothing near: where the step put it, and no lines.
  expect(alignTo(box(250, 150), { x: 248, y: 152 }, others)).toEqual({ x: 248, y: 152, guides: [] })
  // Two near at once: the nearer of them.
  expect(alignTo(box(98, 0), { x: 96, y: 0 }, [box(103, 200), box(99, 400)]).x).toBe(99)
  expect(alignTo(box(2, 0), { x: 0, y: 0 }, [box(-3, 200)]).x).toBe(0)
})

it('settles a dragged width on the step, as wide as another, or ending where another ends', () => {
  const others = [box(0, 100, 224), box(400, 0, 176)]
  expect(resizeTo(box(0, 0, 200), 230, others)).toEqual({ width: 224, guides: [{ axis: 'y', at: 44, from: 0, to: 224 }, { axis: 'y', at: 144, from: 0, to: 224 }] })
  const edge = resizeTo(box(200, 0, 100), 197, others)
  expect(edge.width).toBe(200)
  expect(edge.guides).toEqual([{ axis: 'x', at: 400, from: 0, to: 40 }])
  expect(resizeTo(box(0, 0, 200), 263, others)).toEqual({ width: 264, guides: [] })
  expect(resizeTo(box(0, 0, 200), 20, others).width).toBe(MIN_WIDTH)
  expect(resizeTo(box(0, 0, 200), 2000, []).width).toBe(MAX_WIDTH)
})

it('gives every pill, chip, slider and thermostat a width of its style unless it has its own', () => {
  const pill = lampAt('a', 0, 0, 'pill') as HomeLight
  expect(controlWidth(pill)).toBe(DEFAULT_WIDTH.pill)
  expect(controlWidth({ ...pill, width: 300 })).toBe(300)
  expect(controlWidth({ ...pill, width: 10 })).toBe(MIN_WIDTH)
  expect(controlWidth(lampAt('b', 0, 0, 'chip') as HomeLight)).toBe(DEFAULT_WIDTH.chip)
  expect(controlWidth(lampAt('c', 0, 0, 'round') as HomeLight)).toBeNull()
  expect(controlWidth({ id: 't', type: 'climate', x: 0, y: 0, rid: 'r', entity_id: 'climate.a', name: 'A', style: 'pill', sensor: null })).toBe(DEFAULT_WIDTH.climate)
  expect(isResizable(lampAt('d', 0, 0, 'knob'))).toBe(false)
  expect(widthOf({ ...pill, width: 400 })).toBe(400)
})

// -- thermostat styles -----------------------------------------------------------

it('finds the target at a share of a thermostat\'s range, on its step', () => {
  const thermostat = { step: 0.5, min: 7, max: 30 }
  expect(targetAt(thermostat, 0)).toBe(7)
  expect(targetAt(thermostat, 1)).toBe(30)
  expect(targetAt(thermostat, 0.5)).toBe(18.5)
  expect(targetAt(thermostat, 5 / 6)).toBe(26)
  expect(targetAt(thermostat, -1)).toBe(7)
  expect(targetAt(thermostat, 2)).toBe(30)
  expect(shareOf(thermostat, 18.5)).toBe(0.5)
  expect(shareOf(thermostat, 40)).toBe(1)
  expect(shareOf(thermostat, null)).toBe(0)
  expect(shareOf({ min: 20, max: 20 }, 20)).toBe(0)
})

it('gives each thermostat style its room, and a width only to those with a name in a row', () => {
  const heater = (style: string): HomeElement => ({ id: style, type: 'climate', x: 0, y: 0, rid: 'r', entity_id: 'climate.a', name: 'A', style: style as never, sensor: null })
  for (const style of ['pill', 'round', 'chip', 'tile', 'slider', 'dial', 'valve', 'thermometer', 'radiator', 'digits'] as const) {
    expect(heightOf(heater(style)), style).toBe(CLIMATE_FOOTPRINTS[style].height)
    expect(widthOf(heater(style)), style).toBe(CLIMATE_FOOTPRINTS[style].width)
    const spots = climateSpots([], 8, style)
    const { width, height } = CLIMATE_FOOTPRINTS[style]
    for (const [index, a] of spots.entries()) for (const b of spots.slice(index + 1)) expect(b.x >= a.x + width || b.y >= a.y + height, style).toBe(true)
  }
  expect(controlWidth(heater('chip') as HomeClimate)).toBe(DEFAULT_WIDTH.climateChip)
  expect(controlWidth(heater('slider') as HomeClimate)).toBe(DEFAULT_WIDTH.climateSlider)
  expect(controlWidth(heater('dial') as HomeClimate)).toBeNull()
  expect(isWide(heater('pill') as HomeClimate)).toBe(true)
  expect(isWide(heater('dial') as HomeClimate)).toBe(false)
})

it('moves a target by hand at least half a degree, a degree in Fahrenheit, but keeps a coarser step', () => {
  expect(handStep({ step: 0.1, unit: '°C' })).toBe(0.5)
  expect(handStep({ step: 0.5, unit: '°C' })).toBe(0.5)
  expect(handStep({ step: 1, unit: '°C' })).toBe(1)
  expect(handStep({ step: 0.5, unit: '°F' })).toBe(1)
  expect(handStep({ step: 0, unit: '°C' })).toBe(0.5)
  const tenths = { step: 0.1, unit: '°C', min: 5, max: 30 }
  expect(stepTarget(byHand(tenths), 21.3, 1)).toBe(21.5)
  expect(stepTarget(byHand(tenths), 21.3, 2)).toBe(22)
  expect(stepTarget(byHand(tenths), 21.3, -1)).toBe(21)
  expect(stepTarget(byHand(tenths), 21.3, -2)).toBe(20.5)
})
