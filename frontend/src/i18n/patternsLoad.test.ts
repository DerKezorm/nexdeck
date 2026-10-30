/**
 * The phrases with numbers of a language come with it when it is chosen, not in the first load: choosing one leaves
 * its patterns registered, and a language whose loader was forgotten would show "3 device(s) offline" in English.
 */
import { afterAll, describe, expect, it } from 'vitest'

import { LANGUAGES, setLanguage } from './index'
import { PATTERNS, translateText } from './texts'

describe('the patterns of a language', () => {
  afterAll(async () => {
    await setLanguage('en')
  })

  it('are not there before the language is chosen', () => {
    expect(Object.keys(PATTERNS)).toEqual(['de'])
  })

  for (const code of Object.keys(LANGUAGES).filter((code) => code !== 'en')) {
    it(`${code}: arrive when it is chosen`, async () => {
      await setLanguage(code)
      expect(PATTERNS[code]?.length).toBe(PATTERNS.de.length)
      const translated = translateText('labels', '3 device(s) offline')
      expect(translated).not.toBe('3 device(s) offline')
      expect(translated).toContain('3')
    })
  }
})
