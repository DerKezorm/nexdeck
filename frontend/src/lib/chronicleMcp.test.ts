/**
 * A press over MCP in the chronicle, in the reader's language: the card, the key, the button and, when somebody
 * allowed it, who. The words come from the MCP texts, fetched when such a line is on screen.
 */
import i18next from 'i18next'
import { beforeAll, describe, expect, it } from 'vitest'

import de from '../i18n/texts.de.json'
import { registerTexts, type TextBundle } from '../i18n/texts'
import { lineDetail, lineStatus, lineText, type ChronicleLine } from './chronicle'
import { loadChronicleWords } from './chronicleWords'

const t = (key: string, options?: Record<string, unknown>) => i18next.t(key, options) as string

const press: ChronicleLine = {
  when: 1_792_900_000,
  kind: 'mcp_call',
  level: 'info',
  name: 'Containers',
  before: 'Laptop (MCP)',
  after: 'Restart',
  detail: 'Restart on Containers by Laptop (MCP)',
  board: 'Lab',
}
const allowed: ChronicleLine = { ...press, user: 'Sam', detail: 'Restart on Containers by Laptop (MCP), approved by Sam' }

describe('the chronicle line of a press over MCP', () => {
  it('reads like the server sentence in English, before any words are fetched, from the server sentence itself', () => {
    expect(lineText(allowed, t, 'en')).toBe('Restart on Containers by Laptop (MCP), approved by Sam')
  })

  it('falls back to the card name when the sentence is missing', () => {
    expect(lineText({ ...press, detail: '' }, t, 'en')).toBe('Containers')
  })

  it('is news, not a fault: grey dot, no second line', () => {
    expect(lineStatus(press)).toBe('unknown')
    expect(lineDetail(press, t)).toBe('')
  })
})

describe('with the words fetched', () => {
  beforeAll(async () => {
    for (const language of ['en', 'de', 'es', 'fr', 'it']) await loadChronicleWords(language)
    // The words of the buttons themselves, which the app fetches with its other texts.
    registerTexts('de', de as TextBundle)
  })

  it('says it in English with the facts of the line', () => {
    expect(lineText({ ...press, detail: 'ignored' }, t, 'en')).toBe('Restart on Containers by Laptop (MCP)')
    expect(lineText({ ...allowed, detail: 'ignored' }, t, 'en')).toBe('Restart on Containers by Laptop (MCP), approved by Sam')
  })

  it.each([
    ['de', 'Neustarten auf Containers durch Laptop (MCP)', 'erlaubt von Sam'],
    ['es', 'en Containers por Laptop (MCP)', 'permitido por Sam'],
    ['fr', 'sur Containers par Laptop (MCP)', 'autorisé par Sam'],
    ['it', 'su Containers da Laptop (MCP)', 'consentito da Sam'],
  ])('says it in %s, with who allowed it only when somebody did', async (language, pressed, who) => {
    await i18next.changeLanguage(language)
    try {
      const direct = lineText({ ...press, detail: 'English only' }, i18next.t.bind(i18next), language)
      expect(direct).toContain(pressed)
      expect(direct).not.toContain('English only')
      expect(direct).not.toContain(who)
      expect(lineText({ ...allowed, detail: 'English only' }, i18next.t.bind(i18next), language)).toContain(who)
    } finally {
      await i18next.changeLanguage('en')
    }
  })
})
