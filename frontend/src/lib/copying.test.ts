import i18next from 'i18next'
import { describe, expect, it } from 'vitest'

import { copyNotes } from './copying'

describe('what a copy says afterwards', () => {
  it('names the cards that stayed behind', () => {
    void i18next.changeLanguage('en')
    const said = copyNotes([
      { code: 'held_left', name: 'Media', count: 2 },
      { code: 'held_left', name: 'Lab', count: 1 },
    ], i18next.t)
    expect(said).toEqual([
      '2 cards of Media stayed behind, because you could not add them there yourself.',
      'One card of Lab stayed behind, because you could not add it there yourself.',
    ])
  })

  it('says nothing about a note it does not know', () => {
    expect(copyNotes([{ code: 'something_new', name: 'X' }], i18next.t)).toEqual([])
  })
})
