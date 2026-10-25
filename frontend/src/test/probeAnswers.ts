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
