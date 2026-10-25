/** The words of the chronicle: made in the browser, in the reader's language. */
import i18next from 'i18next'
import { afterEach, describe, expect, it } from 'vitest'

import { setLanguage } from '../i18n/index'
import { dayOf, lineDetail, lineText, momentOf, type ChronicleLine } from './chronicle'

const t = (key: string, options?: Record<string, unknown>) => i18next.t(key, options) as string

function line(extra: Partial<ChronicleLine>): ChronicleLine {
  return { when: Date.now() / 1000, kind: 'card', level: 'bad', name: 'Synology', before: 'ok', after: 'bad', detail: '', board: 'Lab', ...extra }
}

describe('chronicle words', () => {
  afterEach(async () => {
    await i18next.changeLanguage('en')
  })

  it('says how a card turned', () => {
    expect(lineText(line({}), t, 'en')).toBe('Synology turned red')
    expect(lineText(line({ after: 'warn' }), t, 'en')).toBe('Synology turned yellow')
    expect(lineText(line({ after: 'ok' }), t, 'en')).toBe('Synology is fine again')
  })

  it('says the other kinds, and a kind it does not know by its name', () => {
    expect(lineText(line({ kind: 'version', before: '4.0.15', after: '4.0.16', name: 'Sonarr' }), t, 'en')).toBe('Sonarr runs 4.0.16 instead of 4.0.15')
    expect(lineText(line({ kind: 'recovery', detail: '12 min' }), t, 'en')).toBe('Synology answers again after 12 min')
    expect(lineText(line({ kind: 'maintenance', after: new Date(2026, 9, 25, 22, 0).toISOString() }), t, 'en')).toMatch(/^Synology in maintenance until 10:00\sPM$/)
    expect(lineText(line({ kind: 'something_new' }), t, 'en')).toBe('Synology')
  })

  it('adds why, or what a container ran before, on the second line', () => {
    expect(lineDetail(line({ detail: 'The service could not be reached.' }), t)).toBe('The service could not be reached.')
    expect(lineDetail(line({ kind: 'container_recreated', before: 'sonarr:4.0.15', after: 'sonarr:4.0.16' }), t)).toBe('sonarr:4.0.15 → sonarr:4.0.16')
    expect(lineDetail(line({ kind: 'container_recreated', before: 'same', after: 'same' }), t)).toBe('')
    expect(lineDetail(line({ kind: 'signed_in', after: 'home', detail: '192.168.1.20' }), t)).toBe('on the home network · 192.168.1.20')
  })

  it('says what happened to a custom card and what was done to it', () => {
    expect(lineText(line({ kind: 'card_definition_added', name: 'queue-size' }), t, 'en')).toBe('Custom card queue-size made')
    expect(lineText(line({ kind: 'card_definition_changed', name: 'queue-size' }), t, 'en')).toBe('Custom card queue-size changed')
    expect(lineText(line({ kind: 'card_definition_removed', name: 'queue-size' }), t, 'en')).toBe('Custom card queue-size deleted')
    expect(lineDetail(line({ kind: 'card_definition_changed', detail: 'released for users' }), t)).toBe('released for users')
  })

  it('karten9 EC-4: says which connection a card probed and the path, never the answer', () => {
    const probe = line({ kind: 'card_probe', name: 'Sonarr (NAS)', detail: '/api/v3/queue' })
    expect(lineText(probe, t, 'en')).toBe('Connection Sonarr (NAS) probed for a custom card')
    expect(lineDetail(probe, t)).toBe('/api/v3/queue')
  })

  it('speaks German', async () => {
    await setLanguage('de')
    expect(lineText(line({}), t, 'de')).toBe('Synology wurde rot')
    expect(lineText(line({ kind: 'container_restarted', name: 'plex' }), t, 'de')).toBe('Container plex neu gestartet')
  })

  it('heads a day with today, yesterday or its date', () => {
    const now = new Date(2026, 9, 25, 12, 0)
    expect(dayOf(now.getTime() / 1000, t, 'en', now)).toBe('Today')
    expect(dayOf(new Date(2026, 9, 24, 23, 0).getTime() / 1000, t, 'en', now)).toBe('Yesterday')
    expect(dayOf(new Date(2026, 9, 20, 9, 0).getTime() / 1000, t, 'en', now)).toContain('20')
    expect(momentOf(new Date(2026, 9, 24, 22, 10).getTime() / 1000, 'en', t, now)).toMatch(/^yesterday 10:10\sPM$/)
  })
})
