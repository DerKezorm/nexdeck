/**
 * What a new card starts from (KARTEN-9 AC-2, decision 5): a blank card or one example per form, each a working card
 * with demo answers, so that the preview shows something before the first probe.
 *
 * The examples were written for one service each (the kind in `for`); a new card takes the name, the short name and
 * the kind its author chose, and keeps everything else, the path included, for the Source step to adjust.
 */
import { changeCard, parseCard, setAt } from '../../lib/cardDocument'
import type { CardForm } from '../../lib/customCards'

export type StartKind = 'blank' | CardForm

export interface StartChoice {
  /** The kind of connection the example was written for. */
  for: string | null
  text: string
}

const VALUE = `nexdeck-card: 1
slug: lights-on
name: Lights on
version: "1.0.0"
requires: [homeassistant]
requests:
  - id: states
    path: /api/states
    every: 30s
form: value
value:
  path: "length([?starts_with(entity_id, 'light.') && state == 'on'])"
  label: Lights switched on
rules:
  - {value: "length([?starts_with(entity_id, 'light.') && state == 'on'])", op: ">=", than: 10, then: warn}
demo:
  states:
    - {entity_id: light.kitchen, state: "on"}
    - {entity_id: light.hall, state: "off"}
`

const STATS = `nexdeck-card: 1
slug: storage
name: Storage
version: "1.0.0"
requires: [immich]
requests:
  - id: storage
    path: /api/server/storage
    every: 10m
form: stats
stats:
  - path: diskUsagePercentage
    label: Used
    format: percent
    digits: 0
    rules:
      - {op: ">=", than: 80, then: warn}
      - {op: ">=", than: 95, then: bad}
  - {path: diskUseRaw, label: In use, format: bytes}
  - {path: diskAvailableRaw, label: Free, format: bytes}
demo:
  storage: {diskUsagePercentage: 42.5, diskUseRaw: 912680550400, diskAvailableRaw: 1236950581248}
`

const LIST = `nexdeck-card: 1
slug: guests
name: Guests
version: "1.0.0"
requires: [proxmox]
requests:
  - id: guests
    path: /api2/json/cluster/resources?type=vm
    every: 60s
form: list
rows: {select: data, sort: {field: name}, limit: 20}
empty: No guests
item:
  title: name
  subtitle: {template: "{node}, {type} {vmid}"}
  value: {path: mem, format: bytes}
  status:
    - {value: status, op: "!=", than: running, then: bad}
demo:
  guests:
    data:
      - {name: web, node: pve, type: lxc, vmid: 101, mem: 536870912, status: running}
      - {name: backup, node: pve, type: qemu, vmid: 102, mem: 0, status: stopped}
`

const POSTERS = `nexdeck-card: 1
slug: latest
name: Latest
version: "1.0.0"
requires: [jellyfin]
requests:
  - id: items
    path: /Items?SortBy=DateCreated&SortOrder=Descending&IncludeItemTypes=Movie,Series&Recursive=true&Limit=12&Fields=ProductionYear
    every: 5m
form: posters
rows: {select: Items, limit: 12}
item:
  image: {template: "/Items/{Id}/Images/Primary?maxHeight=360"}
  title: Name
  subtitle: {path: ProductionYear, format: text}
demo:
  items:
    Items:
      - {Id: a1, Name: Example Movie, ProductionYear: 2025}
      - {Id: b2, Name: Example Series, ProductionYear: 2023}
`

/** A card with one request and the whole answer as its value: the Source and Look steps make it what it should be. */
const BLANK = `nexdeck-card: 1
slug: my-card
name: My card
version: "1.0.0"
requires: [jsonapi]
requests:
  - id: main
    path: /
form: value
value: "@"
`

export const STARTS: Record<StartKind, StartChoice> = {
  blank: { for: null, text: BLANK },
  value: { for: 'homeassistant', text: VALUE },
  stats: { for: 'immich', text: STATS },
  list: { for: 'proxmox', text: LIST },
  posters: { for: 'jellyfin', text: POSTERS },
}

export const START_ORDER: StartKind[] = ['blank', 'value', 'stats', 'list', 'posters']

/** A short name from a name: lower case letters, digits and hyphens, at most 60 (the rule of `slug`). */
export function slugFrom(name: string): string {
  return name
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/ß/g, 'ss')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60)
    .replace(/-+$/, '')
}

/** The text of a new card: the chosen start with the author's name, short name and kind of connection. */
export function startText(kind: StartKind, choice: { name: string; slug: string; source: string }): string {
  const parsed = parseCard(STARTS[kind].text)
  if (!parsed.ok) throw new Error(`The start ${kind} is not a card.`)
  return changeCard(parsed.card, (doc) => {
    setAt(doc, ['slug'], choice.slug)
    setAt(doc, ['name'], choice.name)
    setAt(doc, ['requires', 0], choice.source)
  }).text
}
