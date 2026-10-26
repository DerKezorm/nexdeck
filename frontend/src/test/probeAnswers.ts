/**
 * Probe answers in the shapes the services give (`notes/karten-testkarten.md`), as `POST /cards/probe` sends them,
 * with invented names only.
 */
import type { ProbeAnswer, ProbeNode } from '../pages/cardEditor/probe'

const leaf = (path: string, key: string | number, value: string | number | boolean | null): ProbeNode => ({
  key,
  path,
  type: value === null ? 'null' : typeof value === 'number' ? 'number' : typeof value === 'boolean' ? 'bool' : 'string',
  value,
})

/** Sonarr's queue: a count and the records, of which a thousand and more were left out. */
export const SONARR_QUEUE: ProbeAnswer = {
  nodes: 14,
  cut: true,
  tree: {
    key: null,
    path: '@',
    type: 'object',
    children: [
      leaf('totalRecords', 'totalRecords', 1236),
      {
        key: 'records',
        path: 'records',
        type: 'array',
        more: 1234,
        children: [
          {
            key: 0,
            path: 'records[0]',
            type: 'object',
            children: [
              leaf('records[0].title', 'title', 'Example.Show.S02E05'),
              { key: 'series', path: 'records[0].series', type: 'object', children: [leaf('records[0].series.title', 'title', 'Example Show')] },
              leaf('records[0].sizeleft', 'sizeleft', 1024),
              leaf('records[0].status', 'status', 'downloading'),
            ],
          },
          {
            key: 1,
            path: 'records[1]',
            type: 'object',
            children: [leaf('records[1].title', 'title', 'Another.Show.S01E09'), leaf('records[1].sizeleft', 'sizeleft', 0), leaf('records[1].status', 'status', 'completed')],
          },
        ],
      },
    ],
  },
}

/** Home Assistant's states: a list at the top, each an entity. */
export const HA_STATES: ProbeAnswer = {
  nodes: 7,
  cut: false,
  tree: {
    key: null,
    path: '@',
    type: 'array',
    children: [
      { key: 0, path: '[0]', type: 'object', children: [leaf('[0].entity_id', 'entity_id', 'light.kitchen'), leaf('[0].state', 'state', 'on')] },
      { key: 1, path: '[1]', type: 'object', children: [leaf('[1].entity_id', 'entity_id', 'light.hall'), leaf('[1].state', 'state', 'off')] },
    ],
  },
}

/** Immich's storage: one object of numbers, a name with a space quoted. */
export const IMMICH_STORAGE: ProbeAnswer = {
  nodes: 4,
  cut: false,
  tree: {
    key: null,
    path: '@',
    type: 'object',
    children: [leaf('diskUsagePercentage', 'diskUsagePercentage', 42.5), leaf('diskUseRaw', 'diskUseRaw', 912680550400), leaf('"disk size"', 'disk size', '2 TB')],
  },
}

const NAME = /^[A-Za-z_][\w]*$/

/** Any answer as the probe's tree: paths from the top as the server writes them (`MediaContainer.Metadata[0].title`). */
export function answerOf(value: unknown, path = '@', key: string | number | null = null): ProbeNode {
  const inner = (part: string | number) => {
    if (typeof part === 'number') return path === '@' ? `[${part}]` : `${path}[${part}]`
    const name = NAME.test(part) ? part : JSON.stringify(part)
    return path === '@' ? name : `${path}.${name}`
  }
  if (Array.isArray(value)) return { key, path, type: 'array', children: value.map((one, index) => answerOf(one, inner(index), index)) }
  if (value !== null && typeof value === 'object') return { key, path, type: 'object', children: Object.entries(value).map(([name, one]) => answerOf(one, inner(name), name)) }
  return leaf(path, key as string, value as string | number | boolean | null)
}

const probed = (value: unknown): ProbeAnswer => {
  const tree = answerOf(value)
  const count = (node: ProbeNode): number => 1 + (node.children ?? []).reduce((sum, child) => sum + count(child), 0)
  return { tree, nodes: count(tree), cut: false }
}

const ROOMS = ['kitchen', 'hall', 'living_room', 'bath', 'office', 'bedroom', 'kids_room', 'terrace', 'garage', 'cellar']

/** Home Assistant's `/api/states` with lights, temperatures and switches, as the guided way's first example shows it. */
export const HA_HOME = probed(
  ROOMS.flatMap((room, index) => [
    { entity_id: `light.${room}`, state: [0, 2, 3, 5, 6, 9].includes(index) ? 'on' : 'off', attributes: { friendly_name: `Light ${room}` }, last_changed: `2026-10-26T0${index % 7}:1${index}:00+00:00` },
    { entity_id: `sensor.temperature_${room}`, state: String(19 + (index % 5)), attributes: { friendly_name: `Temperature ${room}` }, last_changed: '2026-10-26T06:00:00+00:00' },
    ...(index < 3 ? [{ entity_id: `switch.socket_${room}`, state: 'on', attributes: { friendly_name: `Socket ${room}` }, last_changed: '2026-10-26T05:40:00+00:00' }] : []),
  ]),
)

/** Proxmox VE's `/api2/json/cluster/resources?type=vm`: the guests under `data`. */
export const PROXMOX_GUESTS = probed({
  data: [
    { id: 'qemu/100', name: 'docker-live', node: 'pve', type: 'qemu', vmid: 100, status: 'running', mem: 6549825536, maxmem: 8589934592 },
    { id: 'qemu/101', name: 'home-assistant', node: 'pve', type: 'qemu', vmid: 101, status: 'running', mem: 2362232012, maxmem: 4294967296 },
    { id: 'lxc/102', name: 'pihole', node: 'pve', type: 'lxc', vmid: 102, status: 'running', mem: 322122547, maxmem: 1073741824 },
    { id: 'qemu/202', name: 'mint', node: 'pve', type: 'qemu', vmid: 202, status: 'stopped', mem: 0, maxmem: 4294967296 },
  ],
})

/** Plex's `/library/recentlyAdded`: the entries under `MediaContainer.Metadata`, each with a poster. */
export const PLEX_RECENT = probed({
  MediaContainer: {
    size: 3,
    Metadata: [
      { ratingKey: '7400', title: 'The Lighthouse Keeper', year: 2024, type: 'movie', thumb: '/library/metadata/7400/thumb/1730000000' },
      { ratingKey: '7401', title: 'North Wind', year: 2021, type: 'movie', thumb: '/library/metadata/7401/thumb/1730000001' },
      { ratingKey: '7402', title: 'Still Waters', year: 2025, type: 'show', thumb: '/library/metadata/7402/thumb/1730000002' },
    ],
  },
})
