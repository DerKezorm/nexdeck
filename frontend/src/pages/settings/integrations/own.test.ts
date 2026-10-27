/** The order and the filters of the own list, without drawing it. */
import { describe, expect, it } from 'vitest'

import type { AdapterSpec, Integration } from '../../../api/types'
import { FILTERS, grouped, matches, rowsOf, visible, type VersionReading } from './own'

function connection(id: number, name: string, extra: Partial<Integration> = {}): Integration {
  return {
    id, kind: 'sonarr', label: 'Sonarr', icon: 'sonarr', beta: false, name, config: {}, enabled: true, demo: false, admin_only: false,
    muted: false, last_ok_at: '2026-10-27T10:00:00Z', last_error: '', widget_count: 1, created_at: '2026-10-01T10:00:00Z', ...extra,
  }
}

const ADAPTERS = [
  { kind: 'sonarr', category: 'downloads' },
  { kind: 'plex', category: 'media' },
  { kind: 'pihole', category: 'network' },
] as AdapterSpec[]

const behind = { state: 'behind', running: '1.0', newest: '1.1' } as VersionReading

describe('the rows of the own list', () => {
  it('call a connection failing only while it is switched on and real', () => {
    const rows = rowsOf(
      [connection(1, 'On', { last_error: 'Timed out' }), connection(2, 'Off', { last_error: 'Timed out', enabled: false }), connection(3, 'Demo', { last_error: 'Timed out', demo: true })],
      ADAPTERS,
      undefined,
    )
    expect(rows.map((row) => row.failing)).toEqual([true, false, false])
  })

  it('count a failing connection as failing only, not also as an update', () => {
    const rows = rowsOf([connection(1, 'Broken', { last_error: 'Refused' }), connection(2, 'Old')], ADAPTERS, { 1: behind, 2: behind })
    expect(rows.map((row) => [row.failing, row.behind])).toEqual([
      [true, false],
      [false, true],
    ])
  })

  it('take the category from the adapter, and "other" for one it does not know', () => {
    const rows = rowsOf([connection(1, 'Plex', { kind: 'plex' }), connection(2, 'Gone', { kind: 'vanished' })], ADAPTERS, undefined)
    expect(rows.map((row) => row.category)).toEqual(['media', 'other'])
  })
})

describe('the order', () => {
  it('puts failing first, then updates, then the rest by name', () => {
    const rows = rowsOf(
      [connection(1, 'alpha'), connection(2, 'Zulu', { last_error: 'Refused' }), connection(3, 'Mike'), connection(4, 'Bravo')],
      ADAPTERS,
      { 3: behind },
    )
    expect(visible(rows, 'all', '', (c) => c).map((row) => row.integration.name)).toEqual(['Zulu', 'Mike', 'alpha', 'Bravo'])
  })
})

describe('the filters', () => {
  const rows = rowsOf(
    [connection(1, 'A', { last_error: 'Refused' }), connection(2, 'B', { widget_count: 0 }), connection(3, 'C', { muted: true }), connection(4, 'D')],
    ADAPTERS,
    { 4: behind },
  )
  const names = (filter: Parameters<typeof visible>[1]) => visible(rows, filter, '', (c) => c).map((row) => row.integration.name)

  it('each keep their own', () => {
    expect(names('failing')).toEqual(['A'])
    expect(names('updates')).toEqual(['D'])
    expect(names('cardless')).toEqual(['B'])
    expect(names('muted')).toEqual(['C'])
    expect(names('all')).toHaveLength(4)
  })

  it('are counted by the same test that filters', () => {
    expect(FILTERS.map((one) => rows.filter(one.test).length)).toEqual([4, 1, 1, 1, 1])
  })
})

describe('the search', () => {
  it('finds every word in any order, without accents or case', () => {
    expect(matches('Pi-hole primär Network', 'PRIMAR pi')).toBe(true)
    expect(matches('Pi-hole primär Network', 'primar plex')).toBe(false)
  })

  it('looks at the name, the service, the category and the error', () => {
    const rows = rowsOf([connection(1, 'Downstairs', { last_error: 'Signing in was refused (401)' }), connection(2, 'Upstairs', { kind: 'plex', label: 'Plex' })], ADAPTERS, undefined)
    const found = (query: string) => visible(rows, 'all', query, (c) => (c === 'media' ? 'Media' : c)).map((row) => row.integration.name)
    expect(found('401')).toEqual(['Downstairs'])
    expect(found('media')).toEqual(['Upstairs'])
    expect(found('sonarr')).toEqual(['Downstairs'])
  })
})

describe('by category', () => {
  it('follows the given order, counts failing and updates, and leaves out empty ones', () => {
    const rows = rowsOf(
      [connection(1, 'Plex', { kind: 'plex' }), connection(2, 'Sonarr', { last_error: 'x' }), connection(3, 'Sonarr 2'), connection(4, 'Odd', { kind: 'vanished' })],
      ADAPTERS,
      { 3: behind },
    )
    const groups = grouped(rows, ['media', 'downloads', 'network', 'other'])
    expect(groups.map((group) => [group.category, group.rows.length, group.failing, group.updates])).toEqual([
      ['media', 1, 0, 0],
      ['downloads', 2, 1, 1],
      ['other', 1, 0, 0],
    ])
  })
})
