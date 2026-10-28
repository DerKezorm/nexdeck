/** The CHANGELOG in the update dialog: only what is newer than the installed version (Etappe 8, N4). */
import { describe, expect, it } from 'vitest'

import { changelogSections, isNewerVersion, newerSections } from './changelog'

const LOG = `# Changelog

## 1.0.10 (2026-10-30)

- Faster list
- New icon

Reads one request less.

## 1.0.9 (2026-10-20)

Fixed the colour.

## 1.0.0 (2026-10-01)

First version.
`

describe('versions', () => {
  it('karten8n_n4: compares number by number, as the server does', () => {
    expect(isNewerVersion('1.0.10', '1.0.9')).toBe(true)
    expect(isNewerVersion('1.0.9', '1.0.10')).toBe(false)
    expect(isNewerVersion('1.0', '1.0.0')).toBe(false)
    expect(isNewerVersion('1.0.0.1', '1.0.0')).toBe(true)
    expect(isNewerVersion('2.0.0', '2.0.0')).toBe(false)
  })
})

describe('the sections', () => {
  it('karten8n_n4: a heading opens a section; paragraphs and lists become blocks, the title line is dropped', () => {
    const found = changelogSections(LOG)
    expect(found.map((one) => one.heading)).toEqual(['1.0.10 (2026-10-30)', '1.0.9 (2026-10-20)', '1.0.0 (2026-10-01)'])
    expect(found[0].version).toBe('1.0.10')
    expect(found[0].blocks).toEqual([
      { kind: 'list', items: ['Faster list', 'New icon'] },
      { kind: 'text', text: 'Reads one request less.' },
    ])
  })

  it('karten8n_n4: only the sections newer than the installed version stay (1.0.10 is newer than 1.0.9)', () => {
    expect(newerSections(LOG, '1.0.9').map((one) => one.version)).toEqual(['1.0.10'])
    expect(newerSections(LOG, '1.0.0').map((one) => one.version)).toEqual(['1.0.10', '1.0.9'])
    expect(newerSections(LOG, '1.0.10')).toEqual([])
  })

  it('karten8n_n4: v1.2.0 and [1.2.0] name a version, a date alone does not', () => {
    const text = '## v1.2.0\n\nA.\n\n## [1.1.0] - 2026-10-01\n\nB.\n\n## 2026-09-01\n\nC.\n'
    expect(changelogSections(text).map((one) => one.version)).toEqual(['1.2.0', '1.1.0', null])
    // One section names a version, so the one without cannot be judged and is left out.
    expect(newerSections(text, '1.1.0').map((one) => one.heading)).toEqual(['v1.2.0'])
  })

  it('karten8n_n4: when no heading names a version there is nothing to cut by and all of it stays', () => {
    const text = '# Changelog\n\n## 2026-10-28\n\nRedrawn preview.\n\n## 2026-10-27\n\nInitial release.\n'
    expect(newerSections(text, '1.0.0').map((one) => one.heading)).toEqual(['2026-10-28', '2026-10-27'])
  })

  it('karten8n_n4: text without any heading is one section without a heading', () => {
    expect(newerSections('1.1.0: counts the episodes too', '1.0.0')).toEqual([{ heading: '', version: null, blocks: [{ kind: 'text', text: '1.1.0: counts the episodes too' }] }])
  })

  it('karten8n_n4: markup stays text (the parts are strings for the page to draw as text)', () => {
    const [section] = newerSections('## 2.0.0\n\n<img src=x onerror=alert(1)> [a link](http://example.com)\n', '1.0.0')
    expect(section.blocks).toEqual([{ kind: 'text', text: '<img src=x onerror=alert(1)> [a link](http://example.com)' }])
  })
})
