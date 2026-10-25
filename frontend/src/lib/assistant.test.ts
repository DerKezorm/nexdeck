import i18n from 'i18next'
import { describe, expect, it } from 'vitest'

import { factText } from './assistant'
import { blocks, dayGroup, inline } from './assistantWords'

describe('the words of an answer', () => {
  it('knows bold, and leaves a lone mark as it was written', () => {
    expect(inline('**Plex** is down')).toEqual([{ text: 'Plex', bold: true }, { text: ' is down', bold: false }])
    expect(inline('a **b')).toEqual([{ text: 'a ', bold: false }, { text: '**b', bold: false }])
    expect(inline('**a** and **b**').filter((part) => part.bold).map((part) => part.text)).toEqual(['a', 'b'])
  })

  it('makes paragraphs and lists, numbered ones too', () => {
    expect(blocks('First line\nsame paragraph\n\n- one\n- two\n1. three').map((block) => block.kind)).toEqual(['p', 'ul'])
    const list = blocks('Intro:\n- one\n- two')
    expect(list).toHaveLength(2)
    expect(list[1].kind === 'ul' && list[1].items.length).toBe(2)
  })
})

describe('the day of a conversation', () => {
  const now = new Date(2026, 9, 25, 9, 0)
  it('is today, yesterday, this week or earlier', () => {
    expect(dayGroup(new Date(2026, 9, 25, 0, 5).toISOString(), now)).toBe('today')
    expect(dayGroup(new Date(2026, 9, 24, 23, 0).toISOString(), now)).toBe('yesterday')
    expect(dayGroup(new Date(2026, 9, 20, 12, 0).toISOString(), now)).toBe('week')
    expect(dayGroup(new Date(2026, 9, 1).toISOString(), now)).toBe('older')
  })
})

describe('what a button hits', () => {
  it('is worded with the right number', () => {
    const t = i18n.getFixedT('en')
    expect(factText(t, { fact: 'streams', count: 1, names: ['Dune'] })).toBe('1 stream ends: Dune')
    expect(factText(t, { fact: 'downloads', count: 5 })).toBe('5 downloads stop')
    expect(factText(t, { fact: 'devices', count: 3, names: ['light.kitchen', 'light.hall', 'switch.tv'] })).toBe('Switches 3 devices: light.kitchen, light.hall, switch.tv')
    expect(factText(t, { fact: 'up', text: 'Up 3 days' })).toBe('Docker: Up 3 days')
  })
})
