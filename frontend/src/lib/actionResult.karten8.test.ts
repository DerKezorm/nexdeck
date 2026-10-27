/**
 * What a pressed button says when it failed (KARTEN-8 AC-9): the sentence of its code in the language of the person,
 * English with the words of the server, and the codes of the buttons have sentences in every language.
 */
import i18next from 'i18next'
import { describe, expect, it } from 'vitest'

import { ApiError } from '../api/client'
import de from '../i18n/de.json'
import en from '../i18n/en.json'
import es from '../i18n/es.json'
import fr from '../i18n/fr.json'
import it_ from '../i18n/it.json'
import { actionFailureText } from './actionResult'

const CODES = ['no_longer_offered', 'no_answer', 'bad_value', 'body_too_large', 'no_such_action', 'redirected', 'http_error', 'bad_path']
const failure = (code: string, message: string) => new ApiError(400, code, message)

async function in_(language: string, bundle: unknown) {
  const instance = i18next.createInstance()
  await instance.init({ lng: language, resources: { [language]: { translation: bundle as Record<string, unknown> } }, interpolation: { escapeValue: false } })
  return instance.t
}

describe('the failure of a pressed button', () => {
  it.each([
    ['de', de, 'Keine Antwort'],
    ['es', es, 'Sin respuesta'],
    ['fr', fr, 'Pas de réponse'],
    ['it', it_, 'Nessuna risposta'],
  ])('is worded in %s, not in English', async (language, bundle, start) => {
    const t = await in_(language, bundle)
    const said = actionFailureText(t, language, failure('no_answer', 'No answer. It may have run; check the service.'))
    expect(said.startsWith(start)).toBe(true)
    expect(said).not.toContain('No answer')
  })

  it('keeps the words of the server in English', async () => {
    const t = await in_('en', en)
    expect(actionFailureText(t, 'en', failure('http_error', 'The service answered HTTP 502.'))).toBe('The service answered HTTP 502.')
  })

  it('has a sentence of its own for every code of a button in every language', () => {
    for (const bundle of [en, de, es, fr, it_]) {
      const widget = (bundle as { errors: { widget: Record<string, string> } }).errors.widget
      for (const code of CODES) expect(widget[code], code).toBeTruthy()
    }
  })

  it('says the network is down when no answer came at all', async () => {
    const t = await in_('de', de)
    expect(actionFailureText(t, 'de', new TypeError('Failed to fetch'))).toBe((de as { errors: { network: string } }).errors.network)
  })
})
