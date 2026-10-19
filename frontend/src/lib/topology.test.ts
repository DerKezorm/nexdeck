/**
 * The arithmetic of the topology page: how values read, where devices stand
 * when nothing was placed by hand, where a late arrival goes, and which value
 * labels may stand without covering another one or a device.
 */
import { declutter, formatBits, freeSpot, levelOf, pathUp, portName, treeLayout, utilisation } from './topology'

describe('formatBits', () => {
  it('reads like UniFi, in bits, with the reader decimal mark', () => {
    expect(formatBits(640)).toBe('640 bit/s')
    expect(formatBits(1_500)).toBe('1.5 kbit/s')
    expect(formatBits(12_000_000)).toBe('12 Mbit/s')
    expect(formatBits(2_500_000, 'de')).toBe('2,5 Mbit/s')
    expect(formatBits(1_250_000_000, 'de')).toBe('1,25 Gbit/s')
  })

  it('says it does not know rather than zero', () => {
    expect(formatBits(null)).toBe('–')
    expect(formatBits(undefined)).toBe('–')
  })
})

describe('load', () => {
  it('is the fuller direction against the speed, and unknown without a speed', () => {
    expect(utilisation({ down: 600e6, up: 10e6, speed: 1e9 })).toBeCloseTo(0.6)
    expect(utilisation({ down: 600e6, up: 10e6, speed: null })).toBeNull()
    expect(utilisation({ down: null, up: null, speed: 1e9 })).toBeNull()
    expect([levelOf(0.49), levelOf(0.5), levelOf(0.8), levelOf(null)]).toEqual(['calm', 'busy', 'full', 'calm'])
  })
})

describe('treeLayout', () => {
  const links = [
    { a: 'internet', b: 'gw' },
    { a: 'gw', b: 'core' },
    { a: 'core', b: 'left' },
    { a: 'core', b: 'right' },
    { a: 'right', b: 'leaf' },
  ]
  const ids = ['internet', 'gw', 'core', 'left', 'right', 'leaf']

  it('hangs every device a row under the one it uplinks to', () => {
    const at = treeLayout(ids, links, () => 150)
    expect(at.gw[1] - at.internet[1]).toBe(150)
    expect(at.leaf[1] - at.right[1]).toBe(150)
    expect(at.left[1]).toBe(at.right[1])
  })

  it('puts a parent over the middle of its children and keeps cards of one row apart by their widths', () => {
    const widths: Record<string, number> = { left: 300, right: 160, leaf: 160 }
    const at = treeLayout(ids, links, (id) => widths[id] ?? 150)
    // Within the ten-pixel grid every position snaps to.
    expect(Math.abs(at.core[0] - (at.left[0] + at.right[0]) / 2)).toBeLessThanOrEqual(10)
    expect(at.right[0] - at.left[0]).toBeGreaterThanOrEqual(300 / 2 + 160 / 2)
  })

  it('never puts a wide parent over the subtree to its left', () => {
    const at = treeLayout(['a', 'b', 'c', 'd'], [{ a: 'a', b: 'b' }, { a: 'a', b: 'c' }, { a: 'c', b: 'd' }], (id) => (id === 'c' ? 600 : 150))
    expect(at.c[0] - 600 / 2).toBeGreaterThanOrEqual(at.b[0] + 150 / 2)
  })

  it('places a device whose uplink is missing as a tree of its own', () => {
    const at = treeLayout(['gw', 'stray'], [{ a: 'elsewhere', b: 'stray' }], () => 150)
    expect(at.stray[1]).toBe(at.gw[1])
    expect(at.stray[0]).not.toBe(at.gw[0])
  })

  it('survives a cycle', () => {
    const at = treeLayout(['a', 'b'], [{ a: 'a', b: 'b' }, { a: 'b', b: 'a' }], () => 150)
    expect(Object.keys(at).sort()).toEqual(['a', 'b'])
  })
})

describe('freeSpot', () => {
  it('goes straight under the parent when that is free, beside it when not', () => {
    expect(freeSpot([500, 100], [], 150)).toEqual([500, 250])
    const spot = freeSpot([500, 100], [{ x: 500, y: 250, w: 200 }], 150)
    expect(spot[1]).toBe(250)
    expect(Math.abs(spot[0] - 500)).toBeGreaterThanOrEqual((200 + 150) / 2)
  })
})

describe('declutter', () => {
  it('keeps the busier of two labels that would cover each other', () => {
    const kept = declutter(
      [
        { id: 'quiet', x: 100, y: 100, w: 120, h: 20, weight: 1e6 },
        { id: 'busy', x: 130, y: 105, w: 120, h: 20, weight: 9e8 },
        { id: 'apart', x: 400, y: 100, w: 120, h: 20, weight: 1 },
      ],
      [],
    )
    expect([...kept].sort()).toEqual(['apart', 'busy'])
  })

  it('leaves out a label that would sit on a device card', () => {
    expect(declutter([{ id: 'on-card', x: 100, y: 100, w: 120, h: 20, weight: 1 }], [{ x: 110, y: 100, w: 180, h: 58 }]).size).toBe(0)
  })
})

describe('naming', () => {
  it('names a port with its own name when it has one', () => {
    expect(portName({ index: 12, name: '' }, 'Port')).toBe('Port 12')
    expect(portName({ index: 48, name: 'Printer' }, 'Port')).toBe('Port 48 · Printer')
    expect(portName({ index: null, name: '' }, 'Port')).toBe('')
  })

  it('walks up to the internet and stops at a loop', () => {
    const links = [
      { id: 'l1', a: 'internet', b: 'gw' },
      { id: 'l2', a: 'gw', b: 'core' },
      { id: 'l3', a: 'core', b: 'ap' },
    ]
    expect(pathUp('ap', links)).toEqual({ nodes: ['ap', 'core', 'gw', 'internet'], links: ['l3', 'l2', 'l1'] })
    expect(pathUp('x', [{ id: 'a', a: 'y', b: 'x' }, { id: 'b', a: 'x', b: 'y' }]).nodes).toEqual(['x', 'y'])
  })
})
