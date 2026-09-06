/** New widgets get a readable default title, in the language of the person adding them. */
import i18next from 'i18next'

import type { AdapterSpec, WidgetTypeSpec } from '../api/types'
import { defaultTitle, haystack } from './WidgetLibrary'

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

describe('haystack', () => {
  const wol = {
    kind: 'wol',
    label: 'Wake-on-LAN',
    category: 'hosts',
    widgets: [],
  } as unknown as AdapterSpec
  const wake = {
    kind: 'wol.wake',
    label: 'Wake',
    description: 'The state of the machine, and the button that wakes it.',
  } as unknown as WidgetTypeSpec

  it('finds a card by the name people actually type', () => {
    // ⚠️ "Wake-on-LAN" does not contain "wol". Searching the labels alone
    // meant the card could not be found by its own name.
    expect(haystack(wol, wake)).toContain('wol')
    expect('Wake-on-LAN'.toLowerCase()).not.toContain('wol')
  })

  it('still finds it by its written name and its German one', () => {
    const text = haystack(wol, wake)
    expect(text).toContain('wake-on-lan')
    expect(text).toContain('hosts')
  })

  it('covers the short names of the awkward services', () => {
    const cases: [string, string][] = [
      ['pbs', 'Proxmox Backup Server'],
      ['npm', 'Nginx Proxy Manager'],
    ]
    for (const [kind, label] of cases) {
      const adapter = { kind, label, category: 'infra', widgets: [] } as unknown as AdapterSpec
      const widget = { kind: `${kind}.status`, label: 'Status', description: '' } as unknown as WidgetTypeSpec
      expect(haystack(adapter, widget), kind).toContain(kind)
      expect(label.toLowerCase(), label).not.toContain(kind)
    }
  })
})
