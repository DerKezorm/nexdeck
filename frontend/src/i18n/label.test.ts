/**
 * A language translated by machine says so wherever one is chosen, until a speaker has read it through; the others
 * stand by their own name.
 */
import { describe, expect, it } from 'vitest'

import { BETA, LANGUAGES, languageLabel } from './index'

describe('the name of a language in the pickers', () => {
  it('carries Beta for the four languages not yet read through, and only for those', () => {
    expect([...BETA].sort()).toEqual(['nl', 'pl', 'pt', 'ru'])
    expect(languageLabel('ru')).toBe('Русский (Beta)')
    expect(languageLabel('pt')).toBe('Português (Brasil) (Beta)')
    expect(languageLabel('de')).toBe('Deutsch')
    expect(Object.keys(LANGUAGES).filter((code) => languageLabel(code).endsWith('(Beta)')).sort()).toEqual(['nl', 'pl', 'pt', 'ru'])
  })
})
