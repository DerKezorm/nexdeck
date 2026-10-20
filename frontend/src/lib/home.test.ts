import { freshId, nextSpot, readingOrder, snap, surfaceHeight, type HomeElement } from './home'

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
