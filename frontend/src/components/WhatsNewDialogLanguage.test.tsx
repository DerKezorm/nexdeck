/**
 * "What's new" is written in English and German only. On screen in any other
 * language the window shows the English entry, never an empty window or none.
 */
import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { setLanguage } from '../i18n'
import de from '../i18n/whatsnew.de.json'
import en from '../i18n/whatsnew.en.json'
import { latestVersion, type WhatsNewEntry } from '../lib/whatsnew'
import { useAuth } from '../stores/auth'
import { WhatsNewDialog } from './WhatsNewDialog'

const version = latestVersion()!
const english = (en.entries as Record<string, WhatsNewEntry>)[version]
const german = (de.entries as Record<string, WhatsNewEntry>)[version]

describe('WhatsNewDialog in a language it is not written in', () => {
  beforeEach(() => {
    useAuth.setState({ user: { id: 1, username: 'admin', role: 'admin', seen_version: '0.0.1' } as never })
  })
  afterEach(async () => {
    await setLanguage('en')
  })

  it('shows the English entry in Spanish', async () => {
    await setLanguage('es')
    render(<WhatsNewDialog />)
    expect(screen.getByRole('dialog')).toBeTruthy()
    expect(screen.getByText(english.lead)).toBeTruthy()
    expect(screen.getByText(english.sections[0].title)).toBeTruthy()
  })

  it('still shows the German entry in German', async () => {
    await setLanguage('de')
    render(<WhatsNewDialog />)
    expect(screen.getByText(german.lead)).toBeTruthy()
  })
})
