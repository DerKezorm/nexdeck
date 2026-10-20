/**
 * The tools of an element stand outside its drawing, on the first side that
 * covers nothing, else on the side that covers least (seen 20.10.2026: on a
 * small tile they hid its "off").
 */
import { describe, expect, it } from 'vitest'

import { pickToolSide, TOOL_SIDES, type ToolSide } from './HomePage'

const rect = (left: number, top: number, width: number, height: number) => ({ left, top, right: left + width, bottom: top + height })
const PAGE = rect(0, 0, 1000, 800)
/** An element at 100,100, 120 by 40, with its tools 80 by 24 on each side. */
const SIDES: Record<ToolSide, ReturnType<typeof rect>> = {
  above: rect(140, 72, 80, 24),
  corner: rect(210, 74, 80, 24),
  right: rect(224, 100, 24, 80),
  below: rect(100, 144, 80, 24),
  left: rect(72, 100, 24, 80),
}

describe('pickToolSide', () => {
  it('takes the corner above when nothing stands there', () => {
    expect(pickToolSide(SIDES, [], PAGE)).toBe('above')
  })

  it('goes on to the next free side when a pill stands right above', () => {
    expect(pickToolSide(SIDES, [rect(100, 52, 120, 40)], PAGE)).toBe('right')
  })

  it('keeps off another element\'s tools as well', () => {
    expect(pickToolSide(SIDES, [rect(130, 60, 200, 40), rect(222, 96, 30, 30)], PAGE)).toBe('below')
  })

  it('never leaves the page: at its top edge the tools go beside the element', () => {
    expect(pickToolSide(SIDES, [], rect(0, 90, 1000, 800))).toBe('right')
  })

  it('where every side covers something, takes the one that covers least', () => {
    const everywhere = [rect(0, 0, 1000, 99), rect(221, 0, 400, 400), rect(0, 141, 1000, 400), rect(60, 100, 30, 10)]
    expect(pickToolSide(SIDES, everywhere, PAGE)).toBe('left')
    expect(TOOL_SIDES[0]).toBe('above')
  })
})
