import { describe, expect, it } from 'vitest'

import { pickTarget, searchUrl, type SearchTarget } from './search'

const web: SearchTarget = { name: 'DuckDuckGo', url: 'https://duckduckgo.com/?q={query}', prefix: 'd', icon: '' }
const tube: SearchTarget = { name: 'YouTube', url: 'https://www.youtube.com/results?search_query={query}', prefix: 'y', icon: '' }
const radarr: SearchTarget = { name: 'Radarr', url: 'https://radarr.example.com/add/new?term={query}', prefix: 'r', icon: '' }

describe('searchUrl', () => {
  it('puts the words in', () => {
    expect(searchUrl(web, 'nexdeck')).toBe('https://duckduckgo.com/?q=nexdeck')
  })

  it('encodes what would otherwise change the address', () => {
    // Without encoding the & would add a parameter of the caller's choosing.
    expect(searchUrl(radarr, 'dune part two&x=1')).toBe('https://radarr.example.com/add/new?term=dune%20part%20two%26x%3D1')
  })

  it('fills every placeholder, not only the first', () => {
    const twice: SearchTarget = { name: 'Twice', url: 'https://example.com/{query}?q={query}', prefix: '', icon: '' }
    expect(searchUrl(twice, 'a b')).toBe('https://example.com/a%20b?q=a%20b')
  })

  it('trims what was typed', () => {
    expect(searchUrl(web, '  spaced  ')).toBe('https://duckduckgo.com/?q=spaced')
  })
})

describe('pickTarget', () => {
  const targets = [web, tube, radarr]

  it('picks the target a shortcut names and keeps the rest', () => {
    expect(pickTarget(targets, '!y cats')).toEqual({ chosen: tube, rest: 'cats' })
  })

  it('does not care about the case of the shortcut', () => {
    expect(pickTarget(targets, '!Y cats')).toEqual({ chosen: tube, rest: 'cats' })
  })

  it('leaves a shortcut nobody has in the query', () => {
    expect(pickTarget(targets, '!zz cats')).toEqual({ chosen: null, rest: '!zz cats' })
  })

  it('leaves ordinary text alone', () => {
    expect(pickTarget(targets, 'plex server')).toEqual({ chosen: null, rest: 'plex server' })
  })

  it('takes a shortcut without anything behind it', () => {
    expect(pickTarget(targets, '!d')).toEqual({ chosen: web, rest: '' })
  })
})
