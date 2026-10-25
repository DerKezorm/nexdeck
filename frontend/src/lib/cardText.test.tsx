import { render } from '@testing-library/react'
import i18next from 'i18next'
import { afterEach, beforeAll, describe, expect, it } from 'vitest'

import de from '../i18n/texts.de.json'
import { registerTexts, type TextBundle } from '../i18n/texts'
import { cardLabel, formatShown, pickText, type CardShown } from './cardText'

describe('the language of a card text (KARTEN-1 AC-5)', () => {
  const both = { en: 'Queue', de: 'Warteschlange' }

  it('is the language of whoever looks', () => {
    expect(pickText(both, 'de')).toBe('Warteschlange')
    expect(pickText(both, 'en')).toBe('Queue')
  })

  it('takes the language of a region as its language, and ignores the case of the code', () => {
    expect(pickText(both, 'de-AT')).toBe('Warteschlange')
    expect(pickText({ 'pt-BR': 'Fila', en: 'Queue' }, 'pt-br')).toBe('Fila')
    expect(pickText({ DE: 'Warteschlange' }, 'de')).toBe('Warteschlange')
  })

  it('is English when the viewer’s language was not written', () => {
    expect(pickText(both, 'fr')).toBe('Queue')
    expect(pickText({ de: 'Warteschlange', en: 'Queue' }, 'fr')).toBe('Queue')
    expect(pickText({ en: 'Queue', de: '' }, 'de')).toBe('Queue')
  })

  it('is the first text written when there is no English either', () => {
    expect(pickText({ de: 'Warteschlange', fr: "File d'attente" }, 'it')).toBe('Warteschlange')
    expect(pickText({ de: '  ', fr: "File d'attente" }, 'it')).toBe("File d'attente")
  })

  it('is the text itself when there is only one, and nothing when there is nothing', () => {
    expect(pickText('Queue', 'de')).toBe('Queue')
    expect(pickText(undefined, 'de')).toBe('')
    expect(pickText(null, 'de')).toBe('')
    expect(pickText({}, 'de')).toBe('')
  })
})

describe('a text of the author is not translated by nexdeck (KARTEN-1 AC-6)', () => {
  beforeAll(() => registerTexts('de', de as TextBundle))
  afterEach(async () => {
    await i18next.changeLanguage('en')
  })

  it('stays as written in German, while the same word on a card of nexdeck’s own is translated', async () => {
    await i18next.changeLanguage('de')
    expect(cardLabel('Used', 'de', false)).toBe('Belegt')
    expect(cardLabel('Used', 'de', true)).toBe('Used')
    expect(cardLabel({ en: 'Used', de: 'Gebraucht' }, 'de', true)).toBe('Gebraucht')
    expect(cardLabel({ en: 'Used' }, 'de', true)).toBe('Used')
  })
})

describe('a text with HTML in it is only text (KARTEN-1 EC-8)', () => {
  it('is shown as the letters it is made of and runs nothing', () => {
    const hostile = '<img src=x onerror="document.title=\'hacked\'">'
    const { container } = render(<span>{pickText({ en: hostile }, 'en')}</span>)
    expect(container.querySelector('img')).toBeNull()
    expect(container.textContent).toBe(hostile)
    expect(document.title).not.toBe('hacked')
  })
})

describe('numbers and times in the format of the viewer (KARTEN-5 EC-10)', () => {
  const number = (value: number, digits: number | null = null): CardShown => ({ value, text: String(value), format: 'number', digits })

  it('writes the same number the way each language does', () => {
    expect(formatShown(number(1234.5, 1), 'en')).toBe('1,234.5')
    expect(formatShown(number(1234.5, 1), 'de')).toBe('1.234,5')
    expect(formatShown(number(12), 'de')).toBe('12')
    expect(formatShown(number(3.14159), 'de')).toBe('3,14')
  })

  it('writes a percentage with the sign where the language puts it', () => {
    const share: CardShown = { value: 73.5, text: '73.5%', format: 'percent', digits: 1 }
    expect(formatShown(share, 'en')).toBe('73.5%')
    expect(formatShown(share, 'de').replace(/\s/g, ' ')).toBe('73,5 %')
  })

  it('writes a moment in the zone of the viewer', () => {
    const moment: CardShown = { value: '2026-10-25T00:58:00Z', text: '2026-10-25 02:58', format: 'datetime' }
    expect(formatShown(moment, 'de', { zone: 'Europe/Berlin' })).toMatch(/25\.10\.2026.*02:58/)
    expect(formatShown(moment, 'en', { zone: 'America/New_York' })).toMatch(/Oct 24, 2026.*8:58/)
    expect(formatShown({ ...moment, format: 'time' }, 'de', { zone: 'Europe/Berlin' })).toBe('02:58')
    // a time of day is only the time, written the way the language writes it
    expect(formatShown({ ...moment, format: 'time' }, 'en', { zone: 'America/New_York' })).toMatch(/^8:58\sPM$/)
    expect(formatShown({ ...moment, format: 'time' }, 'en', { zone: 'America/New_York' })).not.toMatch(/Oct|2026/)
    expect(formatShown({ ...moment, format: 'date' }, 'en', { zone: 'America/New_York' })).toBe('Oct 24, 2026')
  })

  it('says how long ago in the words of the language', () => {
    const when: CardShown = { value: '2026-10-25T10:00:00Z', text: '5 min', format: 'ago' }
    const now = Date.parse('2026-10-25T10:05:00Z')
    expect(formatShown(when, 'en', { now })).toBe('5 minutes ago')
    expect(formatShown(when, 'de', { now })).toBe('vor 5 Minuten')
  })

  it('keeps what the server already wrote out, adds the unit of the card, and shows a dash for nothing', () => {
    expect(formatShown({ value: 1536, text: '1.5 KB', format: 'bytes' }, 'de')).toBe('1.5 KB')
    expect(formatShown({ ...number(3), unit: { en: 'items', de: 'Stück' } }, 'de')).toBe('3 Stück')
    expect(formatShown({ ...number(3), unit: { en: 'items', de: 'Stück' } }, 'fr')).toBe('3 items')
    expect(formatShown({ value: null, text: '–', format: 'number', unit: 'items' }, 'de')).toBe('–')
  })
})
