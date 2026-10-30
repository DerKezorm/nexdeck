/**
 * The skin editor's own logic: undo that folds a dragged colour into one step,
 * values set at a path, the drawing of a sprite, a picture cut down to the
 * colours a sprite may hold, the part a click lands on, and the looks it can
 * start from, which must be the looks the look's page offers.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

import { change, redo, setAt, start, undo, type SkinDoc } from '../../lib/skin/draft'
import { partAt, partOf, type Parts } from '../../lib/skin/partAt'
import { fromPixels, mirror, paint, resize, shift } from './SpriteEditor'

const DOC: SkinDoc = { nexdeck_skin: 1, key: 'k', name: 'K' }
const registry = JSON.parse(readFileSync(join(process.cwd(), '..', 'backend', 'app', 'skins', 'parts.json'), 'utf8')) as { parts: Parts }

describe('undo', () => {
  it('folds changes of one field within half a second into one step, and not those of another', () => {
    let history = start(DOC)
    history = change(history, { ...DOC, name: 'A' }, 'name', 1000)
    history = change(history, { ...DOC, name: 'AB' }, 'name', 1200)
    history = change(history, { ...DOC, name: 'AB', key: 'x' }, 'key', 1300)
    expect(history.past).toHaveLength(2)
    history = undo(history)
    expect(history.present.name).toBe('AB')
    expect(undo(history).present).toEqual(DOC)
  })

  it('makes a change after a pause, and a whole new file, a step of its own', () => {
    let history = start(DOC)
    history = change(history, { ...DOC, name: 'A' }, 'name', 1000)
    history = change(history, { ...DOC, name: 'AB' }, 'name', 1600)
    history = change(history, { ...DOC, name: 'C' }, undefined, 1700)
    history = change(history, { ...DOC, name: 'D' }, undefined, 1701)
    expect(history.past).toHaveLength(4)
  })

  it('redoes what was undone until something new is done', () => {
    let history = change(start(DOC), { ...DOC, name: 'A' })
    history = undo(history)
    expect(redo(history).present.name).toBe('A')
    expect(change(history, { ...DOC, name: 'B' }).future).toEqual([])
  })
})

describe('a value at a path', () => {
  it('sets it in a copy and makes what is missing on the way', () => {
    const next = setAt(DOC, ['parts', 'card', 'motion'], { name: 'hop' })
    expect(next).toEqual({ ...DOC, parts: { card: { motion: { name: 'hop' } } } })
    expect(DOC).toEqual({ nexdeck_skin: 1, key: 'k', name: 'K' })
  })

  it('takes a field or an entry of a list out with undefined', () => {
    const doc = { ...DOC, options: [{ key: 'a' }, { key: 'b' }], tokens: { radius: 4 } } as SkinDoc
    expect(setAt(doc, ['options', 0], undefined).options).toEqual([{ key: 'b' }])
    expect(setAt(doc, ['tokens', 'radius'], undefined).tokens).toEqual({})
  })
})

describe('drawing a sprite', () => {
  const rows = ['AB.', '...']
  it('paints, mirrors, shifts round and changes its size', () => {
    expect(paint(rows, 2, 1, 'A')).toEqual(['AB.', '..A'])
    expect(mirror(rows)).toEqual(['.BA', '...'])
    expect(shift(rows, 1, 0)).toEqual(['.AB', '...'])
    expect(shift(rows, 0, 1)).toEqual(['...', 'AB.'])
    expect(resize(rows, 4, 3)).toEqual(['AB..', '....', '....'])
    expect(resize(rows, 1, 1)).toEqual(['A'])
  })

  it('cuts a picture down to the colours a sprite may hold, see-through where it is', () => {
    const pixels: number[] = []
    for (let index = 0; index < 20; index++) pixels.push(index * 12, 0, 0, 255)
    pixels.push(0, 0, 0, 0)
    const sprite = fromPixels(new Uint8ClampedArray(pixels), 21, 1, 4)
    expect(Object.keys(sprite.palette).length).toBeLessThanOrEqual(4)
    expect(sprite.rows[0]).toHaveLength(21)
    expect(sprite.rows[0].endsWith('.')).toBe(true)
  })
})

describe('the part a click lands on', () => {
  it('is the nearest part, and of two the one whose selector says more', () => {
    document.body.innerHTML = `
      <section class="card glass"><header><span class="dot" data-status="ok"></span><h3>Title</h3></header></section>
      <button class="btn btn-accent"><span id="inside">Save</span></button>`
    expect(partOf(document.querySelector('.dot')!, registry.parts)).toBe('card-status')
    expect(partAt(document.getElementById('inside'), registry.parts)?.part).toBe('button-primary')
    expect(partAt(document.querySelector('h3'), registry.parts)?.part).toBe('card-title')
    expect(partAt(document.body, registry.parts)).toBeNull()
  })
})

describe('the looks a new skin starts from', () => {
  it('each have a name in every language, which the list of starting points shows', () => {
    const shipped = JSON.parse(readFileSync(join(process.cwd(), '..', 'backend', 'app', 'skins', 'examples', 'looks.json'), 'utf8')) as { looks: { key: string }[] }
    expect(shipped.looks.length).toBeGreaterThan(0)
    for (const language of ['en', 'de', 'es', 'fr', 'it']) {
      const names = (JSON.parse(readFileSync(join(process.cwd(), 'src', 'i18n', `${language}.json`), 'utf8')) as { settings: { appearance: { looks: Record<string, string> } } }).settings.appearance.looks
      for (const look of shipped.looks) expect(names[look.key], `${language}: ${look.key}`).toBeTruthy()
    }
  })
})
