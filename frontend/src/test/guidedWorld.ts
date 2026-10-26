/**
 * The world of the guided way's page tests: the services a card can read, the connections, the answers in their real
 * shapes and the boards of the account; `stubGuided` puts a card and these on the stubbed server.
 */
import { stub } from './cardEditor'
import { HA_HOME, PLEX_RECENT, PROXMOX_GUESTS, answerOf } from './probeAnswers'

export const SOURCES = [
  { kind: 'homeassistant', label: 'Home Assistant', icon: 'homeassistant' },
  { kind: 'proxmox', label: 'Proxmox VE', icon: 'proxmox' },
  { kind: 'plex', label: 'Plex', icon: 'plex' },
  { kind: 'jsonapi', label: 'JSON API', icon: 'jsonapi' },
  { kind: 'sonarr', label: 'Sonarr', icon: 'sonarr' },
]
export const INTEGRATIONS = [
  { id: 11, kind: 'homeassistant', name: 'Home', label: 'Home Assistant', icon: 'homeassistant', config: {}, enabled: true },
  { id: 12, kind: 'proxmox', name: 'pve', label: 'Proxmox VE', icon: 'proxmox', config: {}, enabled: true },
  { id: 13, kind: 'plex', name: 'Plex', label: 'Plex', icon: 'plex', config: {}, enabled: true },
  { id: 14, kind: 'jsonapi', name: 'Weather', label: 'JSON API', icon: 'jsonapi', config: {}, enabled: true },
  { id: 15, kind: 'plex', name: 'Plex (old)', label: 'Plex', icon: 'plex', config: {}, enabled: false },
  { id: 16, kind: 'qbittorrent', name: 'Torrents', label: 'qBittorrent', icon: 'qbittorrent', config: {}, enabled: true },
]
export const ANSWERS: Record<string, unknown> = {
  '/api/states': HA_HOME,
  '/api2/json/cluster/resources?type=vm': PROXMOX_GUESTS,
  '/library/recentlyAdded?X-Plex-Container-Start=0&X-Plex-Container-Size=12': PLEX_RECENT,
  '/v1/forecast': { nodes: 3, cut: false, tree: answerOf({ temperature: 21.5, wind: 3 }) },
}
export const BOARDS = [
  { id: 1, slug: 'shared', name: 'Shared', permission: 'view', pages: [{ id: 9, name: 'Main', slug: 'main', widget_count: 0 }] },
  {
    id: 2,
    slug: 'home',
    name: 'Home',
    permission: 'owner',
    pages: [
      { id: 5, name: 'Main', slug: 'main', widget_count: 3 },
      { id: 6, name: 'Lights', slug: 'lights', widget_count: 0 },
    ],
  },
]

export function stubGuided(card = '', more: Parameters<typeof stub>[1] = {}) {
  stub(card, {
    'GET /cards/sources': { status: 200, body: SOURCES },
    'GET /integrations': { status: 200, body: INTEGRATIONS },
    'GET /boards': { status: 200, body: BOARDS },
    'POST /cards/probe': (body) => (ANSWERS[String(body?.path)] ? { status: 200, body: ANSWERS[String(body?.path)] } : { status: 502, body: { code: 'source_failed', message: 'The service answered 404.' } }),
    'POST /cards/preview': { status: 200, body: { status: 'ok', primary: { value: 6, text: '6' }, meta: { custom: true } } },
    'POST /cards': { status: 201, body: { slug: 'lights-on', updated_at: '2026-10-26T12:00:00Z' } },
    'POST /pages/6/widgets': { status: 201, body: { widget: { id: 40 } } },
    ...more,
  })
}
