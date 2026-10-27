/** The catalog's search and its order, without drawing it. */
import { describe, expect, it } from 'vitest'

import type { AdapterSpec, Integration } from '../../../api/types'
import { entries, firstSentence, markIn, search, sections, within } from './catalog'

function adapter(kind: string, label: string, category: string, extra: Partial<AdapterSpec> = {}): AdapterSpec {
  return { kind, label, category, description: '', icon: kind, beta: false, docs_url: '', needs_integration: true, fields: [], widgets: [], ...extra }
}

const ADAPTERS = [
  adapter('tautulli', 'Tautulli', 'media', { description: 'Who is watching on Plex right now.' }),
  adapter('plex', 'Plex', 'media'),
  adapter('wol', 'Wake-on-LAN', 'network'),
  adapter('jellystat', 'Jellystat', 'media', { beta: true }),
  adapter('snmp', 'SNMP device', 'network', { keywords: ['Cisco', 'Netgear'] }),
  adapter('core', 'Basics', 'basics', { needs_integration: false }),
  adapter('github', 'GitHub', 'feeds', { needs_integration: false, optional_integration: true }),
]
const ORDER = ['feeds', 'network', 'media']
const OWN = [{ kind: 'plex' }, { kind: 'plex' }, { kind: 'wol' }] as Integration[]
const all = entries(ADAPTERS, OWN, ORDER, (category) => (category === 'media' ? 'Medien' : category))
const kinds = (list: { adapter: AdapterSpec }[]) => list.map((entry) => entry.adapter.kind)

describe('the catalog', () => {
  it('holds what takes a connection, in the categories order and by name', () => {
    expect(kinds(all)).toEqual(['github', 'snmp', 'wol', 'jellystat', 'plex', 'tautulli'])
  })

  it('counts the connections each service has already', () => {
    expect(all.find((entry) => entry.adapter.kind === 'plex')?.connected).toBe(2)
    expect(all.find((entry) => entry.adapter.kind === 'tautulli')?.connected).toBe(0)
  })
})

describe('the search', () => {
  it('finds by the technical name, a vendor, and the category in the language on screen', () => {
    expect(kinds(search(all, 'wol', false))).toEqual(['wol'])
    expect(kinds(search(all, 'netgear', false))).toEqual(['snmp'])
    expect(kinds(search(all, 'medien', false))).toEqual(['jellystat', 'plex', 'tautulli'])
  })

  it('puts the service named so first, so Enter opens the one meant', () => {
    // Bazarr comes first in the catalog and mentions Sonarr; Sonarr itself is what was typed.
    const list = entries([adapter('bazarr', 'Bazarr', 'media', { description: 'Subtitles for what Sonarr holds.' }), adapter('sonarr', 'Sonarr', 'media')], [], ORDER, (c) => c)
    expect(kinds(list)).toEqual(['bazarr', 'sonarr'])
    expect(kinds(search(list, 'sonarr', false))).toEqual(['sonarr', 'bazarr'])
    // A name that begins with the word before one that only holds it.
    const names = entries([adapter('jason', 'Jason', 'media'), adapter('sonarr', 'Sonarr', 'media')], [], ORDER, (c) => c)
    expect(kinds(search(names, 'son', false))).toEqual(['sonarr', 'jason'])
  })

  it('needs every word, in any order', () => {
    expect(kinds(search(all, 'watching plex', false))).toEqual(['tautulli'])
    expect(kinds(search(all, 'plex cisco', false))).toEqual([])
  })

  it('leaves out beta when asked to', () => {
    expect(kinds(search(all, 'jelly', false))).toEqual(['jellystat'])
    expect(kinds(search(all, 'jelly', true))).toEqual([])
  })
})

describe('the choices on the left', () => {
  it('count the hits under all, already connected and each category, keeping empty ones', () => {
    const hits = search(all, 'plex', false)
    expect(sections(all, hits)).toEqual([
      { id: 'all', count: 2 },
      { id: 'connected', count: 1 },
      { id: 'feeds', count: 0 },
      { id: 'network', count: 0 },
      { id: 'media', count: 2 },
    ])
  })

  it('narrow the hits', () => {
    expect(kinds(within(all, 'connected'))).toEqual(['wol', 'plex'])
    expect(kinds(within(all, 'network'))).toEqual(['snmp', 'wol'])
  })
})

describe('a tile', () => {
  it('marks where the first word sits in the name', () => {
    expect(markIn('Jellystat', 'stat')).toEqual([5, 9])
    expect(markIn('Plex', 'sonarr')).toBeNull()
    expect(markIn('Plex', '')).toBeNull()
  })

  it('says one sentence of the description', () => {
    expect(firstSentence('Fotos and videos. And much more.')).toBe('Fotos and videos.')
    expect(firstSentence('Version 1.5 and nothing else')).toBe('Version 1.5 and nothing else')
  })
})
