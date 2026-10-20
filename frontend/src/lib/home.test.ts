import { freshId, nextSpot, readingOrder, snap, surfaceHeight, withLamps, type HomeAnswer, type HomeElement } from './home'

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
  expect(nextSpot([heading('a', 300, 16), heading('b', 16, 120)])).toEqual({ x: 16, y: 176 })
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
  expect(surfaceHeight([heading('a', 0, 400)])).toBe(560)
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
