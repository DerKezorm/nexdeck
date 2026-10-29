/** The hint under a failure in the editor is in the language on screen, not the server's English (found in a real run on 1.0.0). */
import { render, screen } from '@testing-library/react'
import i18next from 'i18next'
import { afterEach, describe, expect, it } from 'vitest'

import deScreen from '../../i18n/de.json'
import texts from '../../i18n/texts.de.json'
import { registerTexts } from '../../i18n/texts'
import { FailureNote } from './FailureNote'

afterEach(async () => {
  await i18next.changeLanguage('en')
})

const failure = { code: 'http_error', message: 'The service answered with HTTP 422.', hint: 'Check the path of the request; the service may not have it.' }

describe('karten17v: the hint of a failure', () => {
  it('stays the server sentence in English and is translated in German', async () => {
    const { rerender } = render(<FailureNote failure={failure} />)
    expect(screen.getByTestId('card-failure')).toHaveTextContent('Check the path of the request; the service may not have it.')
    registerTexts('de', texts)
    i18next.addResourceBundle('de', 'translation', deScreen, true, true)
    await i18next.changeLanguage('de')
    rerender(<FailureNote failure={failure} />)
    const note = screen.getByTestId('card-failure')
    expect(note).toHaveTextContent('Der Dienst antwortet mit einem Fehler.')
    expect(note).toHaveTextContent('Prüf den Pfad der Anfrage; vielleicht kennt der Dienst ihn nicht.')
  })
})
