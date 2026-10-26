import i18next from 'i18next'
import { describe, expect, it } from 'vitest'

import de from '../i18n/de.json'
import en from '../i18n/en.json'
import es from '../i18n/es.json'
import fr from '../i18n/fr.json'
import it_ from '../i18n/it.json'
import { failureText } from '../pages/cardEditor/FailureNote'
import { pausedUntil } from './testResult'

const SERVER = 'Signing in is paused until 14:30 after three failed attempts.'

describe('the pause after failed sign-ins (KARTEN-3 EC-4)', () => {
  it('takes the time out of the sentence of the server', () => {
    expect(pausedUntil(SERVER)).toEqual({ time: '14:30' })
    expect(pausedUntil('nothing here')).toEqual({ time: '' })
  })

  it.each([
    ['de', de, 'Uhr'],
    ['es', es, 'las 14:30'],
    ['fr', fr, 'jusqu\'à 14:30'],
    ['it', it_, 'alle 14:30'],
  ])('is worded in %s with the time in it, not in English', async (language, bundle, part) => {
    const instance = i18next.createInstance()
    await instance.init({ lng: language, resources: { [language]: { translation: bundle } }, interpolation: { escapeValue: false } })
    const said = failureText(instance.t, language, { code: 'sign_in_paused', message: SERVER, hint: '' })
    expect(said).toContain('14:30')
    expect(said).toContain(part)
    expect(said).not.toContain('{{')
    expect(said).not.toContain('Signing in is paused')
  })

  it('has a sentence in every language, with the same place for the time', () => {
    for (const bundle of [en, de, es, fr, it_]) {
      expect((bundle as { errors: { widget: Record<string, string> } }).errors.widget.sign_in_paused).toContain('{{time}}')
    }
  })
})
