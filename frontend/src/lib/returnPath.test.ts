/**
 * The way back after signing in goes to nexdeck's own paths and nowhere else.
 * Each refused case is an address that a careless check would let through.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import { keepReturn, returnPath, takeReturn, waitingReturn } from './returnPath'

describe('returnPath', () => {
  it('keeps a path of its own, with its query', () => {
    expect(returnPath('/go/plex')).toBe('/go/plex')
    expect(returnPath('/go?q=two+words')).toBe('/go?q=two+words')
    expect(returnPath('/b/home/overview#top')).toBe('/b/home/overview#top')
  })

  it.each([
    ['another host', 'https://evil.example/go/plex'],
    ['a host without a scheme', '//evil.example/go/plex'],
    ['a backslash browsers read as a slash', '/\\evil.example'],
    ['a script', 'javascript:alert(1)'],
    ['a relative path', 'go/plex'],
    ['a tab hidden in it', '/\t/evil.example'],
    ['a line break', '/go/plex\nLocation: x'],
    ['nothing', ''],
  ])('refuses %s', (_why, raw) => {
    expect(returnPath(raw)).toBeNull()
  })
})

describe('the path kept over a sign-in', () => {
  afterEach(() => {
    sessionStorage.clear()
    vi.useRealTimers()
  })

  it('is taken once', () => {
    keepReturn('/go/plex')
    expect(waitingReturn()).toBe('/go/plex')
    expect(takeReturn()).toBe('/go/plex')
    expect(takeReturn()).toBeNull()
  })

  it('is checked again when it is taken, so a stored address elsewhere goes nowhere', () => {
    sessionStorage.setItem('nexdeck.return', JSON.stringify({ path: '//evil.example', at: Date.now() }))
    expect(takeReturn()).toBeNull()
  })

  it('is forgotten after ten minutes', () => {
    vi.useFakeTimers()
    keepReturn('/go/plex')
    vi.advanceTimersByTime(11 * 60_000)
    expect(takeReturn()).toBeNull()
  })
})
