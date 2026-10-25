/**
 * The finished values of a custom card in the language of whoever looks (KARTEN-6; KARTEN-1 AC-5, AC-6; KARTEN-5 EC-10).
 */
import i18next from 'i18next'
import { afterEach, beforeAll, describe, expect, it } from 'vitest'

import de from '../i18n/texts.de.json'
import { registerTexts, type TextBundle } from '../i18n/texts'
import { isCustom, labelOf, localizeCustom } from './customCard'
import type { WidgetData } from './types'

const custom = (extra: Partial<WidgetData>): WidgetData => ({ status: 'ok', meta: { custom: true }, ...extra }) as WidgetData

describe('what a custom card shows in the language of the viewer', () => {
  it('picks the label and the unit out of the languages the author wrote', () => {
    const data = custom({ primary: { label: { en: 'Queue', de: 'Warteschlange' }, value: 12, unit: { en: 'items', de: 'Einträge' }, format: 'number', text: '12' } as never })
    const seen = localizeCustom(data, 'de')!
    expect(seen.primary).toMatchObject({ label: 'Warteschlange', unit: 'Einträge', display: '12' })
    expect(localizeCustom(data, 'fr')!.primary).toMatchObject({ label: 'Queue', unit: 'items' })
  })

  it('writes a number the way the language of the viewer writes it', () => {
    const data = custom({ primary: { label: 'Size', value: 1234.5, format: 'number', digits: 1, text: '1234.5' } as never })
    expect(localizeCustom(data, 'de')!.primary!.display).toBe('1.234,5')
    expect(localizeCustom(data, 'en')!.primary!.display).toBe('1,234.5')
  })

  it('keeps the % beside the number instead of inside it, as every card with a percentage does', () => {
    const data = custom({ primary: { label: 'Disk', value: 71, unit: '%', format: 'percent', text: '71%' } as never })
    expect(localizeCustom(data, 'en')!.primary).toMatchObject({ display: '71', unit: '%' })
  })

  it('leaves what the server wrote out as it is: bytes, durations and plain words', () => {
    const data = custom({
      primary: { label: 'Free', value: 5368709120, format: 'bytes', text: '5.0 GB' } as never,
      secondary: [{ label: 'Name', value: 'nas', format: 'text', text: 'nas' }, { label: 'Up', value: 90, format: 'duration', text: '1m 30s' }],
    })
    const seen = localizeCustom(data, 'de')!
    expect(seen.primary!.display).toBe('5.0 GB')
    expect(seen.secondary!.map((row) => row.display)).toEqual(['nas', '1m 30s'])
  })

  it('writes a time in the language of the viewer, and nothing for a value that is not there', () => {
    const data = custom({ primary: { label: 'Seen', value: '2026-10-25T10:30:00Z', format: 'date', text: '2026-10-25' } as never, secondary: [{ label: 'Gone', value: null, format: 'number', text: '–' }] })
    const seen = localizeCustom(data, 'de', 'UTC')!
    expect(seen.primary!.display).toMatch(/25\.10\.2026/)
    expect(seen.secondary![0].display).toBe('–')
  })

  it('writes the cells of a row that depend on the language, and keeps the rest', () => {
    const data = custom({
      items: [
        { title: 'A', subtitle: 'S1', value: '1234.5', status: 'ok', shown: { value: { value: 1234.5, text: '1234.5', format: 'number', digits: 1, unit: { en: 'GB', de: 'Gigabyte' } } } },
        { title: 'B', subtitle: '', value: '', status: 'ok' },
      ],
    })
    const seen = localizeCustom(data, 'de')!
    expect(seen.items![0]).toMatchObject({ title: 'A', subtitle: 'S1', value: '1.234,5 Gigabyte' })
    expect(seen.items![0]).not.toHaveProperty('shown')
    expect(seen.items![1]).toEqual(data.items![1])
  })

  it('picks the empty text', () => {
    const data = custom({ items: [], meta: { custom: true, empty: { en: 'Nothing waiting', de: 'Nichts wartet' } } })
    expect(localizeCustom(data, 'de')!.meta!.empty).toBe('Nichts wartet')
    expect(localizeCustom(custom({ items: [], meta: { custom: true, empty: null } }), 'de')!.meta!.empty).toBeUndefined()
  })

  it('is safe to do twice', () => {
    const data = custom({ primary: { label: { en: 'Queue', de: 'Warteschlange' }, value: 7, unit: { en: 'items' }, format: 'number', text: '7' } as never })
    const once = localizeCustom(data, 'de')!
    expect(localizeCustom(once, 'de')).toEqual(once)
  })

  it('does not touch the data of any other card', () => {
    const plain = { status: 'ok', primary: { label: 'Queue', value: 3 } } as WidgetData
    expect(localizeCustom(plain, 'de')).toBe(plain)
    expect(isCustom(plain)).toBe(false)
    expect(localizeCustom(undefined)).toBeUndefined()
  })
})

describe('the table of translations (KARTEN-1 AC-6)', () => {
  beforeAll(() => registerTexts('de', de as TextBundle))
  afterEach(async () => {
    await i18next.changeLanguage('en')
  })

  it('is applied to the cards of nexdeck and never to a custom card', async () => {
    await i18next.changeLanguage('de')
    const own = { status: 'ok' } as WidgetData
    expect(labelOf(own)('Used')).toBe('Belegt')
    expect(labelOf(custom({}))('Used')).toBe('Used')
    expect(labelOf(custom({}))(null)).toBe('')
  })
})
