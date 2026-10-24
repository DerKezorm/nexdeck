import { describe, expect, it } from 'vitest'

import { anyCardDown, cardStatus } from './cardStatus'
import type { WidgetData, WidgetView } from './types'

const card = (id: number, findings = false): WidgetView =>
  ({ id, kind: 'demo.value', title: '', icon: '', link: '', renderer: 'value', options: findings ? { show_findings: true } : {}, integration_id: null, refresh_seconds: null }) as WidgetView
const answer = (status: WidgetData['status'], error?: string): WidgetData => ({ status, error })

describe('how a card stands', () => {
  it('is red when the fetch failed, whatever the service said', () => {
    expect(cardStatus(card(1), answer('ok', 'timed out'))).toBe('bad')
  })

  it('keeps a reported alarm quiet unless the findings are switched on', () => {
    expect(cardStatus(card(1), answer('bad'))).toBe('ok')
    expect(cardStatus(card(1), answer('warn'))).toBe('ok')
    expect(cardStatus(card(1, true), answer('bad'))).toBe('bad')
    expect(cardStatus(card(1, true), answer('warn'))).toBe('warn')
  })

  it('does not know before the first answer', () => {
    expect(cardStatus(card(1), undefined)).toBe('unknown')
  })
})

describe('the background behind the board', () => {
  it('turns red for a card that shows red, and only for that', () => {
    const widgets = [card(1), card(2, true)]
    expect(anyCardDown(widgets, { 1: answer('ok'), 2: answer('ok') })).toBe(false)
    // An alarm the card keeps quiet does not colour the room either.
    expect(anyCardDown(widgets, { 1: answer('bad'), 2: answer('warn') })).toBe(false)
    expect(anyCardDown(widgets, { 1: answer('ok'), 2: answer('bad') })).toBe(true)
    expect(anyCardDown(widgets, { 1: answer('ok', 'refused'), 2: undefined })).toBe(true)
  })
})

describe('the attention card', () => {
  const attention = { ...card(9), kind: 'core.problems', renderer: 'attention' } as WidgetView

  it('always shows its colour: saying what is yellow and red is all it is for', () => {
    expect(cardStatus(attention, answer('bad'))).toBe('bad')
    expect(cardStatus(attention, answer('warn'))).toBe('warn')
  })

  it('never turns the room red on its own; the cards it repeats do that', () => {
    expect(anyCardDown([attention, card(1)], { 9: answer('bad'), 1: answer('bad') })).toBe(false)
  })
})
