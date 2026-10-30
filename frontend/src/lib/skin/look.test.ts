/**
 * What the stage tells the AI about itself: text that reads below 4.5:1 against
 * its ground, and parts that are there but cannot be seen. And the style sheets
 * of a picture, in which :root has to mean the stand-in for <html>.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Parts } from './partAt'
import { audit, rootless, seeBothModes } from './look'

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

describe('the stage looked at in both modes', () => {
  it('tells what reads badly in the mode it reads badly in, draws each mode, and is left as it was', async () => {
    document.head.insertAdjacentHTML('beforeend', '<style id="modes">.btn { color: rgb(20, 20, 20) } [data-theme="light"] .btn { color: rgb(240, 240, 240) }</style>')
    document.body.innerHTML = '<button class="btn" style="background-color: rgb(255, 255, 255)">Go</button>'
    const html = document.documentElement
    html.setAttribute('data-theme', 'dark')
    const drawn: string[] = []
    const draw = async (root: Document) => {
      drawn.push(`${root.documentElement.getAttribute('data-theme')} ${root.documentElement.hasAttribute('data-stage-still')}`)
      return root.documentElement.getAttribute('data-theme') === 'light' ? 'LIGHT' : 'DARK'
    }
    const seen = await seeBothModes(document, PARTS, true, draw)
    expect(seen.findings).toHaveLength(1)
    expect(seen.findings[0]).toMatch(/^light: button: its text reads at 1\.\d:1/)
    expect(seen.pictures).toEqual([{ mode: 'dark', image: 'DARK' }, { mode: 'light', image: 'LIGHT' }])
    expect(drawn).toEqual(['dark true', 'light true'])
    expect(html.getAttribute('data-theme')).toBe('dark')
    expect(html.hasAttribute('data-stage-still')).toBe(false)
    document.getElementById('modes')?.remove()
    html.removeAttribute('data-theme')
  })

  it('draws nothing where the provider sees no pictures, and keeps a stage that stood still and had no mode', async () => {
    const html = document.documentElement
    html.removeAttribute('data-theme')
    html.setAttribute('data-stage-still', '')
    const draw = vi.fn(async () => 'X')
    expect(await seeBothModes(document, PARTS, false, draw)).toEqual({ findings: [], pictures: [] })
    expect(draw).not.toHaveBeenCalled()
    expect(html.hasAttribute('data-theme')).toBe(false)
    expect(html.hasAttribute('data-stage-still')).toBe(true)
    html.removeAttribute('data-stage-still')
  })
})
