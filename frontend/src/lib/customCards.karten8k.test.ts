/** Etappe 8, small things (karten8k): no problem of the server is shown with a placeholder left open. */
import i18next from 'i18next'
import { afterEach, describe, expect, it } from 'vitest'

import deScreen from '../i18n/de.json'
import answers from '../test/karten12Answers.json'
import { problemText } from './customCards'

type Problem = Parameters<typeof problemText>[1]

afterEach(async () => {
  await i18next.changeLanguage('en')
})

describe('karten8k: the words of a problem', () => {
  const forms = (): Problem[] => {
    const found: Problem[] = []
    const walk = (value: unknown): void => {
      if (Array.isArray(value)) value.forEach(walk)
      else if (value && typeof value === 'object') {
        const one = value as Record<string, unknown>
        if (typeof one.code === 'string' && one.code.startsWith('card_') && 'params' in one) found.push(one as unknown as Problem)
        Object.values(one).forEach(walk)
      }
    }
    walk(answers)
    return found
  }

  it('karten8k: a form that is none of the forms is told with the list of forms', () => {
    const problem = forms().find((one) => one.path === 'form')!
    expect(problemText(i18next.t, problem)).toBe('This must be one of value, stats, list, posters, builder.')
  })

  it('karten8k: every problem the server really sent has all its placeholders filled', async () => {
    expect(forms().length).toBeGreaterThan(0)
    for (const problem of forms()) expect(problemText(i18next.t, problem)).not.toContain('{{')
    await i18next.changeLanguage('de')
    i18next.addResourceBundle('de', 'translation', deScreen, true, true)
    for (const problem of forms()) expect(problemText(i18next.t, problem)).not.toContain('{{')
  })
})
