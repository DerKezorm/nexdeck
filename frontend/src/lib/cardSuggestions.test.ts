/**
 * The catalogue of what a card can show of a service (umbau U4): the common services, two to four suggestions each,
 * every one a relative GET path without a secret, its words in all five languages, and a kind a card can read.
 */
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import de from '../i18n/editor.de.json'
import en from '../i18n/editor.en.json'
import es from '../i18n/editor.es.json'
import fr from '../i18n/editor.fr.json'
import it_ from '../i18n/editor.it.json'
import { suggestionOf, suggestionsFor, SUGGESTIONS, wordsKey } from './cardSuggestions'

const here = path.dirname(fileURLToPath(import.meta.url))
const adapters = path.resolve(here, '../../../backend/app/adapters')
/** The kinds a custom card cannot read through: the keys of NOT_READ_BY_CARDS in base.py. */
const unreadableBlock = readFileSync(path.join(adapters, 'base.py'), 'utf8').split('NOT_READ_BY_CARDS: dict[str, str] = {')[1].split('\n}')[0]
const unreadable = [...unreadableBlock.matchAll(/^ {4}"(\w+)":/gm)].map((one) => one[1])

const at = (data: unknown, key: string) => key.split('.').reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], data)

describe('umbau U4: suggestions per kind of service', () => {
  it('cover the common services, two to four each, with ids of their own', () => {
    const kinds = Object.keys(SUGGESTIONS)
    expect(kinds.length).toBeGreaterThanOrEqual(14)
    for (const kind of ['homeassistant', 'proxmox', 'plex', 'jellyfin', 'emby', 'immich', 'portainer', 'sonarr', 'radarr']) expect(kinds).toContain(kind)
    for (const [kind, list] of Object.entries(SUGGESTIONS)) {
      expect([kind, list.length >= 2 && list.length <= 4]).toEqual([kind, true])
      expect(new Set(list.map((one) => one.id)).size).toBe(list.length)
    }
  })

  it('are relative paths to read, without a secret, and for kinds a card may read through', () => {
    for (const [kind, list] of Object.entries(SUGGESTIONS)) {
      // Every kind that speaks HTTP lets a custom card read; the exceptions stand in one list in base.py.
      expect([kind, existsSync(path.join(adapters, `${kind}.py`)), unreadable.includes(kind)]).toEqual([kind, true, false])
      for (const one of list) {
        expect(one.path).toMatch(/^\/[^/]/)
        expect(one.path).not.toMatch(/:\/\/|\.\.|token|api_?key|password|secret/i)
        expect(one.every).toMatch(/^\d+[smh]$/)
      }
    }
  })

  it('have a title and a sentence in every language, and the words of their start', () => {
    for (const [name, words] of Object.entries({ en, de, es, fr, it: it_ })) {
      for (const [kind, list] of Object.entries(SUGGESTIONS)) {
        for (const one of list) {
          for (const part of ['title', 'text'] as const) expect([name, wordsKey(kind, one, part), typeof at(words, wordsKey(kind, one, part))]).toEqual([name, wordsKey(kind, one, part), 'string'])
          if (one.preset?.form === 'value' && one.preset.label) expect(typeof at(words, wordsKey(kind, one, 'label'))).toBe('string')
        }
      }
    }
  })

  it('are found by kind and path; a kind without any has none', () => {
    expect(suggestionOf('homeassistant', '/api/states')?.id).toBe('states')
    expect(suggestionOf('homeassistant', ' /api/states ')?.id).toBe('states')
    expect(suggestionOf('homeassistant', '/api/states/sun.sun')).toBeNull()
    expect(suggestionsFor('emby')).toBe(SUGGESTIONS.jellyfin)
    expect(suggestionsFor('jsonapi')).toEqual([])
    expect(suggestionsFor(undefined)).toEqual([])
  })
})

describe('review 9: the queues of the *arr services', () => {
  it('ask for a hundred entries, as the adapter does, and name the total they are counted by', () => {
    const adapter = readFileSync(path.join(adapters, 'arr_base.py'), 'utf8')
    expect(adapter).toMatch(/"pageSize": 100/)
    expect(adapter).toMatch(/totalRecords/)
    for (const kind of ['sonarr', 'radarr', 'lidarr']) {
      const queue = SUGGESTIONS[kind].find((one) => one.id === 'queue')!
      expect([kind, Number(/[?&]pageSize=(\d+)/.exec(queue.path)?.[1])]).toEqual([kind, 100])
      expect([kind, queue.total, queue.rows]).toEqual([kind, 'totalRecords', 'records'])
    }
  })
})

describe('review 10: TrueNAS has no suggestions, because a card can only reach its deprecated REST API', () => {
  it('is not in the catalogue, and the adapter still says why', () => {
    expect(SUGGESTIONS.truenas).toBeUndefined()
    expect(suggestionsFor('truenas')).toEqual([])
    const adapter = readFileSync(path.join(adapters, 'truenas.py'), 'utf8')
    // a card's request is the REST API of this adapter, the one the adapter keeps for versions before 25.04
    expect(unreadable).not.toContain('truenas')
    expect(adapter).toMatch(/The REST API is for those older versions only/)
    expect(adapter).toMatch(/answers a key of a \*\*read-only administrator\*\* with 403/)
    for (const words of [en, de, es, fr, it_]) expect((words as { editor: { guided: { want: Record<string, unknown> } } }).editor.guided.want.truenas).toBeUndefined()
  })
})
