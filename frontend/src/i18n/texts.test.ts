/**
 * Server texts are translated by their English wording. English passes
 * through, German comes from the table or from a pattern, and anything the
 * table does not know stays as it came.
 */
import i18next from 'i18next'

import { LANGUAGES } from './index'
import de from './texts.de.json'
import es from './texts.es.json'
import fr from './texts.fr.json'
import it_ from './texts.it.json'
import { PATTERNS, registerTexts, translateText, type TextBundle } from './texts'

/** Every language besides English and German, each with its table of server texts. */
const OTHERS: Record<string, TextBundle> = { es, fr, it: it_ } as Record<string, TextBundle>

describe('server texts', () => {
  beforeAll(() => {
    registerTexts('de', de as TextBundle)
    for (const [code, bundle] of Object.entries(OTHERS)) registerTexts(code, bundle)
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
    expect(translateText('labels', '2 request(s) failed')).toBe('2 Anfrage(n) fehlgeschlagen')
    expect(translateText('labels', '1 error finding(s), 2 warning(s)')).toBe('1 Fehler-Befund(e), 2 Warnung(en)')
    expect(translateText('labels', 'Up 3 days')).toBe('Läuft seit 3 Tagen')
    expect(translateText('labels', '3 device(s) offline')).toBe('3 Gerät(e) offline')
    expect(translateText('labels', 'UniFi answers · 24 devices online · 76 clients')).toBe('UniFi antwortet · 24 Geräte online · 76 Clients')
    expect(translateText('labels', 'runs at 100 Mbit/s')).toBe('läuft mit 100 Mbit/s')
    expect(translateText('labels', '7 errors in the last hour')).toBe('7 Fehler in der letzten Stunde')
    expect(translateText('labels', 'core answers · 8 of 24 ports up · nothing to report')).toBe('core antwortet · 8 von 24 Ports verbunden · nichts zu melden')
    expect(translateText('labels', 'Switch · USW-Flex · firmware update available')).toBe('Switch · USW-Flex · Firmware-Update verfügbar')
    expect(translateText('labels', 'Guests (VLAN 80) · open · 2.4 + 5 GHz · guest portal · on 3 access points · off')).toBe('Guests (VLAN 80) · offen · 2.4 + 5 GHz · Gästeportal · auf 3 Access Points · aus')
    expect(translateText('labels', '1 gateway · 13 switches · 10 access points')).toBe('1 Gateway · 13 Switches · 10 Access Points')
    expect(translateText('labels', '52 wireless · 24 wired')).toBe('52 WLAN · 24 Kabel')
    expect(translateText('labels', 'restic/restic · Exited (0) 5 months ago')).toBe('restic/restic · Beendet (0) vor 5 Monaten')
    expect(translateText('labels', 'paperless-ngx · Up 6 hours · unhealthy')).toBe('paperless-ngx · Läuft seit 6 Stunden · ungesund')
    expect(translateText('labels', 'Music last scanned 12 days ago')).toBe('Music zuletzt vor 12 Tagen gescannt')
    expect(translateText('labels', 'Plex answers · 1.42.0 · 3 libraries')).toBe('Plex antwortet · 1.42.0 · 3 Bibliotheken')
    expect(translateText('labels', '6 play(s) · Living room TV, iPhone')).toBe('6 Wiedergabe(n) · Living room TV, iPhone')
    expect(translateText('labels', '649 play(s) · Apple TV ×2')).toBe('649 Wiedergabe(n) · Apple TV ×2')
    expect(translateText('labels', 'Jellyfin answers · 10.11.0 · 2 libraries')).toBe('Jellyfin antwortet · 10.11.0 · 2 Bibliotheken')
    expect(translateText('labels', '6 failed sign-ins in 24 h')).toBe('6 gescheiterte Anmeldungen in 24 h')
    expect(translateText('labels', '1 error(s) in 24 h · Scan media library failed')).toBe('1 Fehler in 24 h · Scan media library failed')
    expect(translateText('labels', '3 errors · root@nas')).toBe('3 Fehler · root@nas')
    expect(translateText('labels', 'Failed · The operation was canceled.')).toBe('Fehlgeschlagen · The operation was canceled.')
    expect(translateText('labels', 'The last run failed · Access denied')).toBe('Der letzte Lauf ist fehlgeschlagen · Access denied')
    expect(translateText('labels', '2.0 GB free')).toBe('2.0 GB frei')
    expect(translateText('labels', 'online · battery 84% · Person')).toBe('online · Akku 84 % · Person')
    expect(translateText('labels', 'Reolink answers · Home Hub · 3 cameras')).toBe('Reolink antwortet · Home Hub · 3 Kameras')
    expect(translateText('labels', 'signed in, no plays · Chrome ×2')).toBe('angemeldet, keine Wiedergaben · Chrome ×2')
    expect(translateText('labels', '10 new episodes')).toBe('10 neue Folgen')
    expect(translateText('labels', 'Season 3')).toBe('Staffel 3')
    // Dockhand's environment and update rows.
    expect(translateText('labels', 'Online · CPU 3.4 % · Memory 41 % · 2 unhealthy')).toBe('Online · CPU 3.4 % · Speicher 41 % · 2 ungesund')
    expect(translateText('labels', 'redis:7.2 · 7.4.1 available · Main')).toBe('redis:7.2 · 7.4.1 verfügbar · Main')
    // UrBackup, Elasticsearch, OpenWrt and Kubernetes rows.
    expect(translateText('labels', 'File backup overdue · File backup 3 d ago · Offline, last seen 2 h ago')).toBe('Dateisicherung überfällig · Dateisicherung vor 3 d · Nicht erreichbar, zuletzt vor 2 h')
    expect(translateText('labels', 'No room for a replica · 5 documents')).toBe('Kein Platz für ein Replikat · 5 Dokumente')
    expect(translateText('labels', 'Static address · 192.168.1.1/24 · up 4m 19s')).toBe('Feste Adresse · 192.168.1.1/24 · seit 4m 19s')
    expect(translateText('labels', 'Crashing · shop · 3 restarts')).toBe('Stürzt ab · shop · 3 Neustarts')
    expect(translateText('labels', '14 min ago')).toBe('vor 14 min')
  })

  it('translate the Reclaimerr phrases in every language', async () => {
    // The texts as the adapter writes them; "last (.+)" from an older card
    // stood before them once and turned "ran 14 min ago" into half German.
    const said = [
      'Movie version · 331.4 KB · Delete request open',
      'Postponed, in 23 d',
      'in 2 d',
      'at least 312.4 GB',
      'every 15 min · ran 4 min ago',
      'Postpone 7 d',
      'Last media sync 3 d ago. · Sync Media failed.',
      'The API token lacks the scope candidates:read.',
    ]
    const expected: Record<string, string[]> = {
      de: ['Filmfassung · 331.4 KB · Löschwunsch offen', 'Aufgeschoben, in 23 d', 'in 2 d', 'mindestens 312.4 GB', 'alle 15 min · lief vor 4 min',
        'Um 7 Tage aufschieben', 'Letzte Mediensynchronisierung vor 3 d. · Sync Media fehlgeschlagen.', 'Dem API-Token fehlt die Berechtigung candidates:read.'],
      es: ['Versión de película · 331.4 KB · Solicitud de borrado abierta', 'Aplazado, en 23 d', 'en 2 d', 'al menos 312.4 GB', 'cada 15 min · se ejecutó hace 4 min',
        'Aplazar 7 días', 'Última sincronización de medios hace 3 d. · Sync Media falló.', 'Al token de API le falta el permiso candidates:read.'],
      fr: ['Version du film · 331.4 KB · Demande de suppression ouverte', 'Reporté, dans 23 d', 'dans 2 d', 'au moins 312.4 GB', 'toutes les 15 min · exécutée il y a 4 min',
        'Reporter de 7 jours', 'Dernière synchronisation des médias il y a 3 d. · Sync Media a échoué.', 'Il manque au jeton d’API l’autorisation candidates:read.'],
      it: ['Versione del film · 331.4 KB · Richiesta di eliminazione aperta', 'Rinviato, tra 23 d', 'tra 2 d', 'almeno 312.4 GB', 'ogni 15 min · eseguito 4 min fa',
        'Rinvia di 7 giorni', 'Ultima sincronizzazione dei media 3 d fa. · Sync Media non riuscito.', 'Al token API manca il permesso candidates:read.'],
    }
    for (const [code, words] of Object.entries(expected)) {
      await i18next.changeLanguage(code)
      expect(said.map((text) => translateText('labels', text)), code).toEqual(words)
    }
  })

  it('translate the M3U Editor phrases in every language', async () => {
    // The texts as the adapter writes them. "(.+) failed." from an older card
    // would catch the first reason if the M3U Editor patterns stood after it.
    const said = [
      '2 viewer(s) · admin, kids · started 6 min ago · On a failover source · 3 error(s)',
      '5 of 5 channels on · 1 VOD · 5 groups · 1 streaming · synced 2 h ago',
      'Custom playlist · 3 of 3 channels on · last try 10 min ago',
      'Example News · ends in 20 min',
      'Channel 3 · ended 5 min ago · 13.0 MB',
      'Example TV: the last sync failed. · Old TV: last synced 3 d ago. · New TV: never synced.',
      'M3U Editor answers · 2 playlist(s) · 1 guide(s)',
    ]
    const expected: Record<string, string[]> = {
      de: ['2 Zuschauer · admin, kids · läuft seit 6 min · Auf einer Ersatzquelle · 3 Fehler',
        '5 von 5 Kanälen an · 1 VOD · 5 Gruppen · 1 laufen · synchronisiert vor 2 h',
        'Eigene Playlist · 3 von 3 Kanälen an · letzter Versuch vor 10 min', 'Example News · endet in 20 min', 'Kanal 3 · endete vor 5 min · 13.0 MB',
        'Example TV: Die letzte Synchronisierung schlug fehl. · Old TV: zuletzt vor 3 d synchronisiert. · New TV: nie synchronisiert.',
        'M3U Editor antwortet · 2 Playlist(s) · 1 Programmführer'],
    }
    for (const [code, words] of Object.entries(expected)) {
      await i18next.changeLanguage(code)
      expect(said.map((text) => translateText('labels', text)), code).toEqual(words)
    }
    for (const code of Object.keys(OTHERS)) {
      await i18next.changeLanguage(code)
      for (const text of said) expect(translateText('labels', text), `${code}: ${text}`).not.toBe(text)
      expect(translateText('labels', said[5]), code).not.toMatch(/failed|synced/)
    }
  })

  it('leave unknown text alone', async () => {
    await i18next.changeLanguage('de')
    expect(translateText('labels', 'Living room · 4K · Hi10P')).toBe('Living room · 4K · Hi10P')
    // "Direct play" used to stand here as the unknown one. Since Tautulli
    // arrived it is in the table, and the Plex card gets the German word too.
    expect(translateText('labels', 'Living room · 4K · Direct play')).toBe('Living room · 4K · Direktwiedergabe')
    expect(translateText('labels', 'Bedroom TV · 1080p · Transcode')).toBe('Bedroom TV · 1080p · Transkodierung')
    expect(translateText('labels', 'just now')).toBe('gerade eben')
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

  it('has a table and a list of patterns for every language on offer', () => {
    expect(['en', 'de', ...Object.keys(OTHERS)].sort()).toEqual(Object.keys(LANGUAGES).sort())
    expect(Object.keys(PATTERNS).sort()).toEqual(['de', ...Object.keys(OTHERS)].sort())
  })

  for (const [code, table] of Object.entries(OTHERS)) {
    it(`${code}: knows every text the German table does, and no other`, () => {
      for (const section of ['adapter', 'labels'] as const) {
        const german = Object.keys(de[section])
        expect(german.filter((text) => !(text in table[section])), `${section}: missing in ${code}`).toEqual([])
        expect(Object.keys(table[section]).filter((text) => !(text in de[section])), `${section}: only in ${code}`).toEqual([])
        for (const [english, translated] of Object.entries(table[section])) {
          expect(translated.trim(), `${section}: ${english}`).not.toBe('')
          expect(translated, `${section}: ${english}`).not.toContain('—')
        }
      }
    })

    it(`${code}: has a pattern for every German one, in the same order`, () => {
      // Order matters: the first pattern that fits wins, so a general one ahead
      // of a narrow one would swallow it.
      const patterns = PATTERNS[code] ?? []
      expect(patterns.map(([pattern]) => pattern.source)).toEqual(PATTERNS.de.map(([pattern]) => pattern.source))
      for (const [pattern, replacement] of patterns) {
        const groups = new RegExp(`${pattern.source}|`).exec('')!.length - 1
        for (let group = 1; group <= groups; group++) expect(replacement, pattern.source).toContain(`$${group}`)
        expect(replacement, pattern.source).not.toContain('—')
      }
    })

    it(`${code}: translates words and phrases`, async () => {
      await i18next.changeLanguage(code)
      expect(translateText('labels', 'Used')).not.toBe('Used')
      expect(translateText('adapter', 'Show seconds')).not.toBe('Show seconds')
      expect(translateText('labels', 'Up 3 days')).toMatch(/3/)
      expect(translateText('labels', 'Up 3 days')).not.toBe('Up 3 days')
      expect(translateText('labels', 'A sentence made of steel')).toBe('A sentence made of steel')
    })
  }
})
