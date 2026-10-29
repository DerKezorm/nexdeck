/**
 * What the stage tells the AI about itself: text that reads below 4.5:1 against
 * its ground, and parts that are there but cannot be seen. And the style sheets
 * of a picture, in which :root has to mean the stand-in for <html>.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Parts } from './partAt'
import { audit, rootless } from './look'

const PARTS: Parts = {
  'card-title': { group: 'card', label: 'Title', selectors: ['.card > header > h3'], pseudo: [] },
  button: { group: 'control', label: 'Button', selectors: ['.btn'], pseudo: [] },
  chip: { group: 'data', label: 'Chip', selectors: ['.chip'], pseudo: [] },
}

beforeEach(() => {
  // jsdom lays nothing out; every element is given a size here, unless a test takes it away.
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({ width: 40, height: 20, x: 0, y: 0, top: 0, left: 0, right: 40, bottom: 20, toJSON: () => ({}) } as DOMRect)
})

afterEach(() => {
  vi.restoreAllMocks()
  document.body.innerHTML = ''
})

describe('the stage tells', () => {
  it('a text that reads below 4.5:1 against the first ground behind it, and not one that reads well', () => {
    document.body.innerHTML = `
      <section class="card" style="background-color: rgb(255, 255, 255)"><header><h3 style="color: rgb(200, 200, 200)">Title</h3></header></section>
      <button class="btn" style="background-color: rgb(0, 0, 0); color: rgb(255, 255, 255)">Save</button>`
    const found = audit(document, PARTS)
    expect(found).toHaveLength(1)
    expect(found[0]).toMatch(/^card-title: its text reads at 1\.\d:1/)
  })

  it('a part that is there but cannot be seen', () => {
    document.body.innerHTML = '<span class="chip" style="opacity: 0.1">Beta</span>'
    expect(audit(document, PARTS)).toEqual(['chip: is there but cannot be seen'])
  })

  it('nothing about a text on a picture, which no colour can be held against', () => {
    // A pale ground further out would make the pale text look unreadable; the picture in between is what it stands on.
    document.body.innerHTML = '<div style="background-color: rgb(250, 250, 250)"><div style="background-image: linear-gradient(red, blue)"><button class="btn" style="color: rgb(250, 250, 250)">Go</button></div></div>'
    expect(audit(document, PARTS)).toEqual([])
  })
})

describe('a picture of the stage', () => {
  it('reads its style sheets with :root as the element that stands in for <html>', () => {
    expect(rootless(":root[data-skin='k'] .btn { color: red } :root { --nd-bg: #000 }")).toBe("[data-capture-root][data-skin='k'] .btn { color: red } [data-capture-root] { --nd-bg: #000 }")
  })
})
