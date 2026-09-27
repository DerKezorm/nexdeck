import i18next from 'i18next'

/**
 * Texts that arrive from the server in English and are translated by their
 * English wording: adapter field labels and help, widget names and
 * descriptions, and the labels of values, chips, rows and actions.
 *
 * English needs no table. Every other language ships one JSON file with two
 * sections; an unknown text is shown as it came, so a new adapter never
 * breaks a page, it only stays English until the table knows it.
 */
export type TextSection = 'adapter' | 'labels'
export type TextBundle = Record<TextSection, Record<string, string>>

const bundles: Record<string, TextBundle> = {}

export function registerTexts(language: string, bundle: TextBundle): void {
  bundles[language] = bundle
}

/** Phrases with numbers or sizes inside: the number stays, the words change. */
export const PATTERNS: Record<string, [RegExp, string][]> = {
  de: [
    [/^([\d.,]+ [KMGTP]?B) of ([\d.,]+ [KMGTP]?B)$/, '$1 von $2'],
    [/^(\d+) problem\(s\)$/, '$1 Problem(e)'],
    [/^(\d+) queries, (\d+) grabs$/, '$1 Abfragen, $2 Treffer'],
    [/^(\d+) min left$/, 'noch $1 min'],
    [/^mem (\d+)%$/, 'RAM $1%'],
    [/^disk (\d+)%$/, 'Platte $1%'],
    [/^(\d+) error finding\(s\), (\d+) warning\(s\)$/, '$1 Fehler-Befund(e), $2 Warnung(en)'],
    [/^(\d+) device\(s\) offline$/, '$1 Gerät(e) offline'],
    [/^(\d+) devices online$/, '$1 Geräte online'],
    [/^(\d+) clients$/, '$1 Clients'],
    [/^memory (\d+)%$/, 'RAM $1%'],
    [/^restarted (\d+) min ago$/, 'vor $1 min neu gestartet'],
    [/^on 1 access point$/, 'auf 1 Access Point'],
    [/^1 gateway$/, '1 Gateway'],
    [/^(\d+) gateways$/, '$1 Gateways'],
    [/^1 switch$/, '1 Switch'],
    [/^(\d+) switches$/, '$1 Switches'],
    [/^1 access point$/, '1 Access Point'],
    [/^(\d+) access points$/, '$1 Access Points'],
    [/^(\d+) wireless$/, '$1 WLAN'],
    [/^(\d+) wired$/, '$1 Kabel'],
    [/^(\d+) update\(s\) available$/, '$1 Update(s) verfügbar'],
    [/^(\d+) play\(s\)$/, '$1 Wiedergabe(n)'],
    [/^battery (\d+)%$/, 'Akku $1 %'],
    [/^(\d+) cameras$/, '$1 Kameras'],
    [/^Channel (\d+)$/, 'Kanal $1'],
    [/^(\d+) failed sign-ins in 24 h$/, '$1 gescheiterte Anmeldungen in 24 h'],
    [/^(\d+) error\(s\) in 24 h$/, '$1 Fehler in 24 h'],
    [/^(\d+) errors$/, '$1 Fehler'],
    [/^([\d.,]+ [KMGTP]?i?B) free$/, '$1 frei'],
    [/^(\d+) found$/, '$1 gefunden'],
    [/^([\d.,]+ [KMGTP]?i?B) free of ([\d.,]+ [KMGTP]?i?B)$/, '$1 frei von $2'],
    [/^Account (\d+)$/, 'Konto $1'],
    [/^Device (\d+)$/, 'Gerät $1'],
    [/^Update (.+) available$/, 'Update $1 verfügbar'],
    [/^(.+) is being scanned$/, '$1 wird gerade gescannt'],
    [/^(.+) last scanned (\d+) days ago$/, '$1 zuletzt vor $2 Tagen gescannt'],
    [/^Plex uses (\d+)% CPU$/, 'Plex nutzt $1 % CPU'],
    [/^The host is at (\d+)% CPU$/, 'Der Host liegt bei $1 % CPU'],
    [/^(\d+) video transcodes running$/, '$1 Video-Transcodes laufen'],
    [/^(\d+) libraries$/, '$1 Bibliotheken'],
    [/^on (\d+) access points$/, 'auf $1 Access Points'],
    [/^Up (\d+) days$/, 'Läuft seit $1 Tagen'],
    [/^Up (\d+) hours$/, 'Läuft seit $1 Stunden'],
    [/^Up (\d+) minutes$/, 'Läuft seit $1 Minuten'],
    [/^Up (\d+) seconds$/, 'Läuft seit $1 Sekunden'],
    [/^Up About an hour$/, 'Läuft seit etwa einer Stunde'],
    [/^Up About a minute$/, 'Läuft seit etwa einer Minute'],
    [/^(\d+) days ago$/, 'vor $1 Tagen'],
    [/^(\d+) weeks ago$/, 'vor $1 Wochen'],
    [/^(\d+) months ago$/, 'vor $1 Monaten'],
    [/^Exited \((\d+)\) (\d+) months ago$/, 'Beendet ($1) vor $2 Monaten'],
    [/^Exited \((\d+)\) (\d+) weeks ago$/, 'Beendet ($1) vor $2 Wochen'],
    [/^Exited \((\d+)\) (\d+) days ago$/, 'Beendet ($1) vor $2 Tagen'],
    [/^Exited \((\d+)\) (\d+) hours ago$/, 'Beendet ($1) vor $2 Stunden'],
    [/^Exited \((\d+)\) (\d+) minutes ago$/, 'Beendet ($1) vor $2 Minuten'],
    [/^Up (\d+) weeks$/, 'Läuft seit $1 Wochen'],
    [/^Up (\d+) months$/, 'Läuft seit $1 Monaten'],
    [/^(\d+) hours ago$/, 'vor $1 Stunden'],
    [/^(\d+) minutes ago$/, 'vor $1 Minuten'],
    [/^finished (.+)$/, 'fertig $1'],
    [/^last (.+)$/, 'zuletzt $1'],
    [/^renewed (\d+) days ago$/, 'vor $1 Tagen erneuert'],
    [/^runs at ([\d.]+ [MG]bit\/s)$/, 'läuft mit $1'],
    [/^(\d+) errors in the last hour$/, '$1 Fehler in der letzten Stunde'],
    [/^(\d+) of (\d+) ports up$/, '$1 von $2 Ports verbunden'],
    [/^(\d+) uplink\(s\) down$/, '$1 Uplink(s) ausgefallen'],
    [/^class (\d)$/, 'Klasse $1'],
    [/^(\d+) new episodes$/, '$1 neue Folgen'],
    [/^Season (\d+)$/, 'Staffel $1'],
    [/^Memory ([\d.]+ %)$/, 'Speicher $1'],
    [/^Disk (\d+ %)$/, 'Platte $1'],
    [/^(\S+) documents$/, '$1 Dokumente'],
    [/^File backup (\d+ (?:min|h|d)) ago$/, 'Dateisicherung vor $1'],
    [/^Image backup (\d+ (?:min|h|d)) ago$/, 'Image-Sicherung vor $1'],
    [/^Offline, last seen (\d+ (?:min|h|d)) ago$/, 'Nicht erreichbar, zuletzt vor $1'],
    [/^(\d+ (?:min|h|d)) ago$/, 'vor $1'],
    [/^up (.+)$/, 'seit $1'],
    [/^(\d+) restarts$/, '$1 Neustarts'],
    [/^(\d+) unhealthy$/, '$1 ungesund'],
    [/^(\S+) available$/, '$1 verfügbar'],
    [/^The device answers$/, 'Das Gerät antwortet'],
    [/^(.+) answers$/, '$1 antwortet'],
  ],
  es: [
    [/^([\d.,]+ [KMGTP]?B) of ([\d.,]+ [KMGTP]?B)$/, '$1 de $2'],
    [/^(\d+) problem\(s\)$/, '$1 problema(s)'],
    [/^(\d+) queries, (\d+) grabs$/, '$1 consultas, $2 capturas'],
    [/^(\d+) min left$/, 'quedan $1 min'],
    [/^mem (\d+)%$/, 'RAM $1 %'],
    [/^disk (\d+)%$/, 'disco $1 %'],
    [/^(\d+) error finding\(s\), (\d+) warning\(s\)$/, '$1 hallazgo(s) de error, $2 advertencia(s)'],
    [/^(\d+) device\(s\) offline$/, '$1 dispositivo(s) desconectado(s)'],
    [/^(\d+) devices online$/, '$1 dispositivos en línea'],
    [/^(\d+) clients$/, '$1 clientes'],
    [/^memory (\d+)%$/, 'memoria $1 %'],
    [/^restarted (\d+) min ago$/, 'reiniciado hace $1 min'],
    [/^on 1 access point$/, 'en 1 punto de acceso'],
    [/^1 gateway$/, '1 gateway'],
    [/^(\d+) gateways$/, '$1 gateways'],
    [/^1 switch$/, '1 switch'],
    [/^(\d+) switches$/, '$1 switches'],
    [/^1 access point$/, '1 punto de acceso'],
    [/^(\d+) access points$/, '$1 puntos de acceso'],
    [/^(\d+) wireless$/, '$1 inalámbricos'],
    [/^(\d+) wired$/, '$1 por cable'],
    [/^(\d+) update\(s\) available$/, '$1 actualización(es) disponible(s)'],
    [/^(\d+) play\(s\)$/, '$1 reproducción(es)'],
    [/^battery (\d+)%$/, 'batería $1 %'],
    [/^(\d+) cameras$/, '$1 cámaras'],
    [/^Channel (\d+)$/, 'Canal $1'],
    [/^(\d+) failed sign-ins in 24 h$/, '$1 inicios de sesión fallidos en 24 h'],
    [/^(\d+) error\(s\) in 24 h$/, '$1 error(es) en 24 h'],
    [/^(\d+) errors$/, '$1 errores'],
    [/^([\d.,]+ [KMGTP]?i?B) free$/, '$1 libres'],
    [/^(\d+) found$/, '$1 encontrados'],
    [/^([\d.,]+ [KMGTP]?i?B) free of ([\d.,]+ [KMGTP]?i?B)$/, '$1 libres de $2'],
    [/^Account (\d+)$/, 'Cuenta $1'],
    [/^Device (\d+)$/, 'Dispositivo $1'],
    [/^Update (.+) available$/, 'Actualización $1 disponible'],
    [/^(.+) is being scanned$/, 'Se está escaneando $1'],
    [/^(.+) last scanned (\d+) days ago$/, '$1 escaneado por última vez hace $2 días'],
    [/^Plex uses (\d+)% CPU$/, 'Plex usa un $1 % de CPU'],
    [/^The host is at (\d+)% CPU$/, 'El host está al $1 % de CPU'],
    [/^(\d+) video transcodes running$/, '$1 transcodificaciones de vídeo en marcha'],
    [/^(\d+) libraries$/, '$1 bibliotecas'],
    [/^on (\d+) access points$/, 'en $1 puntos de acceso'],
    [/^Up (\d+) days$/, 'Activo desde hace $1 días'],
    [/^Up (\d+) hours$/, 'Activo desde hace $1 horas'],
    [/^Up (\d+) minutes$/, 'Activo desde hace $1 minutos'],
    [/^Up (\d+) seconds$/, 'Activo desde hace $1 segundos'],
    [/^Up About an hour$/, 'Activo desde hace una hora aproximadamente'],
    [/^Up About a minute$/, 'Activo desde hace un minuto aproximadamente'],
    [/^(\d+) days ago$/, 'hace $1 días'],
    [/^(\d+) weeks ago$/, 'hace $1 semanas'],
    [/^(\d+) months ago$/, 'hace $1 meses'],
    [/^Exited \((\d+)\) (\d+) months ago$/, 'Terminado ($1) hace $2 meses'],
    [/^Exited \((\d+)\) (\d+) weeks ago$/, 'Terminado ($1) hace $2 semanas'],
    [/^Exited \((\d+)\) (\d+) days ago$/, 'Terminado ($1) hace $2 días'],
    [/^Exited \((\d+)\) (\d+) hours ago$/, 'Terminado ($1) hace $2 horas'],
    [/^Exited \((\d+)\) (\d+) minutes ago$/, 'Terminado ($1) hace $2 minutos'],
    [/^Up (\d+) weeks$/, 'Activo desde hace $1 semanas'],
    [/^Up (\d+) months$/, 'Activo desde hace $1 meses'],
    [/^(\d+) hours ago$/, 'hace $1 horas'],
    [/^(\d+) minutes ago$/, 'hace $1 minutos'],
    [/^finished (.+)$/, 'terminado $1'],
    [/^last (.+)$/, 'último $1'],
    [/^renewed (\d+) days ago$/, 'renovado hace $1 días'],
    [/^runs at ([\d.]+ [MG]bit\/s)$/, 'funciona a $1'],
    [/^(\d+) errors in the last hour$/, '$1 errores en la última hora'],
    [/^(\d+) of (\d+) ports up$/, '$1 de $2 puertos activos'],
    [/^(\d+) uplink\(s\) down$/, '$1 uplink(s) caído(s)'],
    [/^class (\d)$/, 'clase $1'],
    [/^(\d+) new episodes$/, '$1 episodios nuevos'],
    [/^Season (\d+)$/, 'Temporada $1'],
    [/^Memory ([\d.]+ %)$/, 'Memoria $1'],
    [/^Disk (\d+ %)$/, 'Disco $1'],
    [/^(\S+) documents$/, '$1 documentos'],
    [/^File backup (\d+ (?:min|h|d)) ago$/, 'Copia de archivos hace $1'],
    [/^Image backup (\d+ (?:min|h|d)) ago$/, 'Copia de imagen hace $1'],
    [/^Offline, last seen (\d+ (?:min|h|d)) ago$/, 'Desconectado, visto por última vez hace $1'],
    [/^(\d+ (?:min|h|d)) ago$/, 'hace $1'],
    [/^up (.+)$/, 'activo desde hace $1'],
    [/^(\d+) restarts$/, '$1 reinicios'],
    [/^(\d+) unhealthy$/, '$1 no sanos'],
    [/^(\S+) available$/, '$1 disponible'],
    [/^The device answers$/, 'El dispositivo responde'],
    [/^(.+) answers$/, '$1 responde'],
  ],
}

function language(): string {
  return (i18next.language || 'en').split('-')[0]
}

/** Translate one server text; unknown texts come back unchanged. */
export function translateText(section: TextSection, text: string | number | null | undefined): string {
  if (text === null || text === undefined || text === '') return ''
  const source = String(text)
  const code = language()
  if (code === 'en') return source
  const table = bundles[code]?.[section]
  if (table && Object.prototype.hasOwnProperty.call(table, source)) return table[source]
  if (section === 'labels') {
    // The same English word often names a widget and a value: Queue, Streams, Devices.
    const shared = bundles[code]?.adapter
    if (shared && Object.prototype.hasOwnProperty.call(shared, source)) return shared[source]
    if (source.includes(' · ')) {
      return source
        .split(' · ')
        .map((part) => translateText('labels', part))
        .join(' · ')
    }
    for (const [pattern, replacement] of PATTERNS[code] ?? []) {
      if (pattern.test(source)) return source.replace(pattern, replacement)
    }
  }
  return source
}

/** Field labels, help texts, widget names and descriptions of the adapters. */
export const tAdapter = (text: string | null | undefined): string => translateText('adapter', text)

/** Labels of values, chips, rows and actions on the cards. */
export const tLabel = (text: string | number | null | undefined): string => translateText('labels', text)
