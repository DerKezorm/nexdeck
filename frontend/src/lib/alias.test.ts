/** The short name shown while typing is the one the server will take (``tests/test_go.py`` has the same cases). */
import { describe, expect, it } from 'vitest'

import { ALIAS, deriveAlias } from './alias'

describe('deriveAlias', () => {
  it.each([
    ['Plex', 'plex'],
    ['Home Assistant', 'home-assistant'],
    ['Kühlschrank & Gefrierfach', 'kuehlschrank-gefrierfach'],
    ['Café ☕', 'cafe'],
    ['  --Pi-hole--  ', 'pi-hole'],
    ['★★', ''],
    ['x'.repeat(60), 'x'.repeat(40)],
  ])('%s becomes %s', (name, short) => {
    expect(deriveAlias(name)).toBe(short)
    if (short) expect(ALIAS.test(short)).toBe(true)
  })
})
