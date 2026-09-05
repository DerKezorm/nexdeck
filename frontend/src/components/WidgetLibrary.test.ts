/** New widgets get a readable default title, in the language of the person adding them. */
import i18next from 'i18next'

import { defaultTitle } from './WidgetLibrary'

describe('defaultTitle', () => {
  afterEach(async () => {
    if (i18next.language !== 'en') await i18next.changeLanguage('en')
  })

  it('joins service and widget, but never repeats a word', () => {
    expect(defaultTitle({ kind: 'unifi', label: 'UniFi Network' }, { label: 'Network' })).toBe('UniFi Network')
    expect(defaultTitle({ kind: 'unifi', label: 'UniFi Network' }, { label: 'Devices' })).toBe('UniFi Network Devices')
    expect(defaultTitle({ kind: 'nexview', label: 'Nexview' }, { label: 'Requests' })).toBe('Nexview Requests')
    expect(defaultTitle({ kind: 'docker', label: 'Docker' }, { label: 'Docker load' })).toBe('Docker load')
    expect(defaultTitle({ kind: 'core', label: 'Basics' }, { label: 'Clock' })).toBe('Clock')
  })

  it('names the card in German for whoever adds it in German', async () => {
    const { setLanguage } = await import('../i18n')
    await setLanguage('de')
    expect(defaultTitle({ kind: 'bazarr', label: 'Bazarr' }, { label: 'Missing subtitles' })).toBe('Bazarr Fehlende Untertitel')
    expect(defaultTitle({ kind: 'core', label: 'Basics' }, { label: 'Clock' })).toBe('Uhr')
    // The doubling rule reads the English pair, or "UniFi Network Netzwerk"
    // would be back.
    expect(defaultTitle({ kind: 'unifi', label: 'UniFi Network' }, { label: 'Network' })).toBe('UniFi Network')
    // A service that writes itself in one way keeps it; only the widget moves.
    expect(defaultTitle({ kind: 'plex', label: 'Plex' }, { label: 'Recently added' })).toBe('Plex Zuletzt hinzugefügt')
  })
})
