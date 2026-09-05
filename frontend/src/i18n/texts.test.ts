/**
 * Server texts are translated by their English wording. English passes
 * through, German comes from the table or from a pattern, and anything the
 * table does not know stays as it came.
 */
import i18next from 'i18next'

import './index'
import de from './texts.de.json'
import { registerTexts, translateText, type TextBundle } from './texts'

describe('server texts', () => {
  beforeAll(() => {
    registerTexts('de', de as TextBundle)
  })
  afterEach(async () => {
    await i18next.changeLanguage('en')
  })

  it('pass through in English', () => {
    expect(translateText('labels', 'Used')).toBe('Used')
    expect(translateText('adapter', 'Show seconds')).toBe('Show seconds')
  })

  it('translate known words in German', async () => {
    await i18next.changeLanguage('de')
    expect(translateText('labels', 'Used')).toBe('Belegt')
    expect(translateText('labels', 'Restart')).toBe('Neustarten')
    expect(translateText('adapter', 'Show seconds')).toBe('Sekunden anzeigen')
    expect(translateText('adapter', "Empty means the browser's zone.")).toBe('Leer nimmt die Zeitzone des Browsers.')
  })

  it('translate phrases with numbers by pattern', async () => {
    await i18next.changeLanguage('de')
    expect(translateText('labels', '1.1 TB of 3.6 TB · normal')).toBe('1.1 TB von 3.6 TB · normal')
    expect(translateText('labels', '3 problem(s)')).toBe('3 Problem(e)')
    expect(translateText('labels', '1 error finding(s), 2 warning(s)')).toBe('1 Fehler-Befund(e), 2 Warnung(en)')
    expect(translateText('labels', 'Up 3 days')).toBe('Läuft seit 3 Tagen')
    expect(translateText('labels', '3 device(s) offline')).toBe('3 Gerät(e) offline')
    expect(translateText('labels', 'UniFi answers · 24 devices online · 76 clients')).toBe('UniFi antwortet · 24 Geräte online · 76 Clients')
    expect(translateText('labels', 'Switch · USW-Flex · firmware update available')).toBe('Switch · USW-Flex · Firmware-Update verfügbar')
    expect(translateText('labels', 'Guests (VLAN 80) · open · 2.4 + 5 GHz · guest portal · on 3 access points · off')).toBe('Guests (VLAN 80) · offen · 2.4 + 5 GHz · Gästeportal · auf 3 Access Points · aus')
    expect(translateText('labels', '1 gateway · 13 switches · 10 access points')).toBe('1 Gateway · 13 Switches · 10 Access Points')
    expect(translateText('labels', '52 wireless · 24 wired')).toBe('52 WLAN · 24 Kabel')
  })

  it('leave unknown text alone', async () => {
    await i18next.changeLanguage('de')
    expect(translateText('labels', 'Living room · 4K · Direct play')).toBe('Living room · 4K · Direct play')
    expect(translateText('labels', 'A sentence made of steel')).toBe('A sentence made of steel')
    expect(translateText('labels', '')).toBe('')
    expect(translateText('labels', null)).toBe('')
  })

  it('has a full and clean German table', () => {
    for (const section of ['adapter', 'labels'] as const) {
      for (const [english, german] of Object.entries(de[section])) {
        expect(english.trim(), section).not.toBe('')
        expect(german.trim(), `${section}: ${english}`).not.toBe('')
        expect(german, `${section}: ${english}`).not.toContain('—')
      }
    }
    expect(Object.keys(de.adapter).length).toBeGreaterThan(200)
    expect(Object.keys(de.labels).length).toBeGreaterThan(80)
  })
})
