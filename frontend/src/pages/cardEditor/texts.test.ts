/** The Texts step's writing (KARTEN-9 AC-8): one field per language, English first, the YAML stays tidy. */
import { describe, expect, it } from 'vitest'

import { changeCard, parseCard, readAt, type CardDoc } from '../../lib/cardDocument'
import { languagesOf, removeLanguage, textIn, textSpots, writeText } from './texts'
import { refusalOf } from './guided/guided'
import { NEW_CARD, slugFrom } from './templates'

function card(text: string): CardDoc {
  const parsed = parseCard(text)
  if (!parsed.ok) throw new Error(JSON.stringify(parsed.problems))
  return parsed.card
}

const STATS = `nexdeck-card: 1
name: Storage
form: stats
stats:
  - diskUseRaw
  - {path: free, label: {en: Free, de: Frei}}
`

describe('karten9 AC-8: the texts of a card', () => {
  it('lists name and description, a label and a unit per value, in order', () => {
    const spots = textSpots(card(STATS)).map((spot) => spot.id)
    expect(spots).toEqual(['name', 'description', 'stats.0.label', 'stats.0.unit', 'stats.1.label', 'stats.1.unit'])
    expect(textSpots(card('name: A\nform: list\nitem: {title: t, value: v}\n')).map((spot) => spot.id)).toEqual(['name', 'description', 'item.value.unit', 'empty'])
  })

  it('has English first, then the languages written', () => {
    const one = card(STATS)
    expect(languagesOf(one, textSpots(one))).toEqual(['en', 'de'])
  })

  it('writes a second language by turning the text into one per language', () => {
    const one = card(STATS)
    const name = textSpots(one)[0]
    const after = changeCard(one, (doc) => writeText(doc, name, 'de', 'Speicher'))
    expect(readAt(after, ['name'])).toEqual({ en: 'Storage', de: 'Speicher' })
    expect(textIn(after, name, 'de')).toBe('Speicher')
    expect(textIn(after, name, 'en')).toBe('Storage')
  })

  it('writes a label on a value written short, which becomes its long form', () => {
    const one = card(STATS)
    const label = textSpots(one).find((spot) => spot.id === 'stats.0.label')!
    const after = changeCard(one, (doc) => writeText(doc, label, 'en', 'In use'))
    expect(readAt(after, ['stats', 0])).toEqual({ path: 'diskUseRaw', label: 'In use' })
  })

  it('removes a language left empty, and the whole text when English goes too', () => {
    const one = card(STATS)
    const label = textSpots(one).find((spot) => spot.id === 'stats.1.label')!
    const noGerman = changeCard(one, (doc) => writeText(doc, label, 'de', ''))
    expect(readAt(noGerman, ['stats', 1, 'label'])).toEqual({ en: 'Free' })
    const none = changeCard(noGerman, (doc) => writeText(doc, label, 'en', ''))
    expect(readAt(none, ['stats', 1, 'label'])).toBeUndefined()
  })

  it('keeps an empty English name for the check to name, it is required', () => {
    const one = card(STATS)
    const after = changeCard(one, (doc) => writeText(doc, textSpots(one)[0], 'en', ''))
    expect(readAt(after, ['name'])).toBe('')
  })

  it('takes a language out of every text at once', () => {
    let one = card(STATS)
    one = changeCard(one, (doc) => writeText(doc, textSpots(one)[0], 'de', 'Speicher'))
    one = changeCard(one, (doc) => removeLanguage(doc, textSpots(one), 'de'))
    expect(readAt(one, ['name'])).toEqual({ en: 'Storage' })
    expect(readAt(one, ['stats', 1, 'label'])).toEqual({ en: 'Free' })
  })
})

describe('karten9 AC-2, umbau U3: what a new card starts from', () => {
  it('is one request and nothing chosen yet, no kind, no name, and the guided way can show it', () => {
    const one = card(NEW_CARD)
    expect(readAt(one, ['requires'])).toEqual([])
    expect(readAt(one, ['name'])).toBe('')
    expect(readAt(one, ['requests'])).toEqual([{ id: 'main', path: '/' }])
    expect(refusalOf(one)).toBeNull()
  })

  it('makes a short name from a name', () => {
    expect(slugFrom('Nächste Folgen!')).toBe('nachste-folgen')
    expect(slugFrom('  Große Straße  ')).toBe('grosse-strasse')
    expect(slugFrom('x'.repeat(70))).toHaveLength(60)
  })
})
