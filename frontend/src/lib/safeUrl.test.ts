import { describe, expect, it } from 'vitest'

import { isSafeUrl, safeUrl } from './safeUrl'

describe('safeUrl', () => {
  it('keeps the addresses a board is made of', () => {
    for (const url of [
      'https://example.com/post',
      'http://192.0.2.10:7878/add/new?term=x',
      'https://news.ycombinator.com/item?id=1',
      'mailto:admin@example.com',
    ]) {
      expect(safeUrl(url)).toBe(url)
    }
  })

  it('keeps an address that stays inside the app', () => {
    expect(safeUrl('/b/home')).toBe('/b/home')
    expect(safeUrl('#top')).toBe('#top')
    expect(safeUrl('?page=2')).toBe('?page=2')
  })

  it('refuses a scheme that would run as part of nexdeck', () => {
    // These come out of feeds and third-party APIs, not from the operator.
    for (const url of [
      'javascript:alert(1)',
      'JavaScript:alert(1)',
      '  javascript:alert(1)  ',
      'java\tscript:alert(1)',
      'data:text/html,<script>alert(1)</script>',
      'vbscript:msgbox(1)',
      'blob:https://example.com/x',
      'file:///etc/passwd',
    ]) {
      expect(safeUrl(url)).toBe('')
    }
  })

  it('refuses what is not an address at all', () => {
    for (const value of ['', '   ', null, undefined, 42, {}, []]) {
      expect(safeUrl(value)).toBe('')
    }
  })

  it('says plainly whether it would link to something', () => {
    expect(isSafeUrl('https://example.com')).toBe(true)
    expect(isSafeUrl('javascript:alert(1)')).toBe(false)
  })
})
