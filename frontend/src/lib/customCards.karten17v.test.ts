/** A path the service did not answer, as the card help shows it (found in a real run on 1.0.0): the card's own words for the failure. */
import i18next from 'i18next'
import { afterEach, describe, expect, it } from 'vitest'

import deScreen from '../i18n/de.json'
import { problemText } from './customCards'

afterEach(async () => {
  await i18next.changeLanguage('en')
})

const failed = {
  code: 'card_path_failed',
  message: 'The service did not answer /api/v3/wanted/missing: The service answered with HTTP 404.',
  path: 'requests[0].path',
  line: null,
  params: { path: '/api/v3/wanted/missing', failure: 'http_error' },
}

describe('karten17v: a proposal whose path the service does not answer', () => {
  it('names the path and says the failure the way a card says it, in the language on screen', async () => {
    expect(problemText(i18next.t, failed)).toBe('/api/v3/wanted/missing does not work at this service: The service answered with an error.')
    await i18next.changeLanguage('de')
    i18next.addResourceBundle('de', 'translation', deScreen, true, true)
    expect(problemText(i18next.t, failed)).toBe('/api/v3/wanted/missing funktioniert bei diesem Dienst nicht: Der Dienst antwortet mit einem Fehler.')
  })
})
