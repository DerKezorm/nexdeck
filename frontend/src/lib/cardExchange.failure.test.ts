/**
 * A refused import as a sentence of the interface (KARTEN-12 EC-1, AC-7), with the refusals the server really sends
 * (`src/test/karten12Answers.json`).
 */
import i18next from 'i18next'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { post } from '../api/client'
import deScreen from '../i18n/de.json'
import answers from '../test/karten12Answers.json'
import { importFailure } from './cardExchange'

/** The refusal as the client turns it into an error, from the body the server sent. */
async function refusal(body: unknown, status = 400): Promise<unknown> {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })))
  return post('/cards/import', {}).then(
    () => null,
    (failure: unknown) => failure,
  )
}

afterEach(async () => {
  vi.unstubAllGlobals()
  await i18next.changeLanguage('en')
})

describe('a refused import in words', () => {
  it('karten12 ec1: a problem of the file is worded by its code with its line, in English and in German', async () => {
    const failure = await refusal(answers.cards_import_invalid)
    expect(importFailure(i18next.t, failure)).toBe('The file has a problem. Line 1: This is neither a card (nexdeck-card: 1) nor an integration (nexdeck: integration).')
    i18next.addResourceBundle('de', 'translation', deScreen, true, true)
    await i18next.changeLanguage('de')
    expect(importFailure(i18next.t, failure)).toBe('Die Datei hat ein Problem. Zeile 1: Das ist weder eine Karte (nexdeck-card: 1) noch eine Anbindung (nexdeck: integration).')
  })

  it('karten12 ac7: asking for the definitions as a member, and a board file that cannot be imported, read as sentences', async () => {
    i18next.addResourceBundle('de', 'translation', deScreen, true, true)
    await i18next.changeLanguage('de')
    expect(importFailure(i18next.t, await refusal(answers.board_import_member_create, 403))).toBe('Nur ein Admin kann die eigenen Karten und Anbindungen einer Board-Datei anlegen.')
    expect(importFailure(i18next.t, await refusal(answers.board_import_bad))).toBe(`Die Datei lässt sich nicht importieren: ${answers.board_import_bad.detail.message}`)
  })
})
