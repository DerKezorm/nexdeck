/**
 * What a custom card can show of a service, in words people use (the guided way of the card editor, step Data).
 *
 * Each suggestion is one GET path below the address of the connection, relative, read only and without a secret: the
 * connection adds its own credentials. Its title and sentence stand in the editor's words under
 * `editor.guided.want.<kind>.<id>`. `rows` names the list of the answer whose entries are the rows (`@` for an answer
 * that is a list itself); left out, the largest list of entries is taken, and `fields` says that the answer is read as
 * single values even though it holds lists. `preset` is what the card starts as once the answer is in.
 *
 * ⚠️ Every path is taken from the code of the integration (`backend/app/adapters/<kind>.py`) or from the service's
 * own API documentation, named beside it. A path nobody has seen answer does not belong here.
 */
/** One comparison of a sentence: the column, how it compares, and with what (the operators of a card). */
export interface Condition {
  field: string
  op: string
  value: string | number | boolean
}

export type Preset =
  | { form: 'value'; count: Condition[]; label: true; warn?: number }
  | { form: 'list'; title: string; subtitle?: string; value?: string; bad?: Condition }
  | { form: 'posters'; image: string; title: string; subtitle?: string }

export type SuggestionIcon = 'list' | 'number' | 'pictures' | 'server' | 'play' | 'calendar' | 'storage' | 'download' | 'health' | 'info' | 'library' | 'people'

export interface CardSuggestion {
  id: string
  icon: SuggestionIcon
  path: string
  every: string
  rows?: string
  /**
   * The field of the answer that holds how many there are in all, for a service that answers one page of a longer list
   * (`totalRecords` of the *arr queue). A count of "everything" reads this field instead of counting the page.
   */
  total?: string
  fields?: true
  /** A picture of each row made from its fields, for a service whose rows name no picture of their own. */
  image?: string
  preset?: Preset
}

/** What the *arr services list when something needs looking at: the message, where it comes from, red for an error. */
const HEALTH: Preset = { form: 'list', title: 'message', subtitle: 'source', bad: { field: 'type', op: '==', value: 'error' } }

const ARR_V3 = (noun: { id: string; path: string }): CardSuggestion[] => [
  // arr_base.py: `self.api(config, ctx, "queue", params={"pageSize": 100, ...})` below /api/v3, the records of the
  // answer are the downloads. Without `pageSize` the service answers ten (Sonarr API docs, "GET /api/v3/queue":
  // page, pageSize), so a queue of forty would read as ten; `totalRecords` says how many there are in all.
  { id: 'queue', icon: 'download', path: '/api/v3/queue?pageSize=100', every: '60s', rows: 'records', total: 'totalRecords', preset: { form: 'list', title: 'title', subtitle: 'status' } },
  // arr_base.py: `self.api(config, ctx, "calendar")`; without start and end it answers today and tomorrow.
  { id: 'calendar', icon: 'calendar', path: '/api/v3/calendar', every: '1h', rows: '@', preset: { form: 'list', title: 'title' } },
  // arr_base.py: `self.api(config, ctx, "health")`, a list of what needs looking at.
  { id: 'health', icon: 'health', path: '/api/v3/health', every: '5m', rows: '@', preset: HEALTH },
  // sonarr.py / radarr.py: `list_path`, everything the service manages.
  { id: noun.id, icon: 'library', path: noun.path, every: '1h', rows: '@' },
]

export const SUGGESTIONS: Record<string, CardSuggestion[]> = {
  homeassistant: [
    // homeassistant.py reads /api/states/{entity_id}; /api/states is the list of all of them
    // (https://developers.home-assistant.io/docs/api/rest/, "GET /api/states").
    {
      id: 'states',
      icon: 'list',
      path: '/api/states',
      every: '30s',
      rows: '@',
      preset: {
        form: 'value',
        count: [
          { field: 'entity_id', op: 'starts_with', value: 'light.' },
          { field: 'state', op: '==', value: 'on' },
        ],
        label: true,
        warn: 8,
      },
    },
    // homeassistant.py: `/api/config`.
    { id: 'config', icon: 'info', path: '/api/config', every: '1h', fields: true },
    // https://developers.home-assistant.io/docs/api/rest/, "GET /api/calendars".
    { id: 'calendars', icon: 'calendar', path: '/api/calendars', every: '1h', rows: '@', preset: { form: 'list', title: 'name', subtitle: 'entity_id' } },
  ],
  proxmox: [
    // proxmox.py: `_get` puts /api2/json in front of "/cluster/resources?type=vm"; the guests are under data.
    {
      id: 'guests',
      icon: 'server',
      path: '/api2/json/cluster/resources?type=vm',
      every: '60s',
      rows: 'data',
      preset: { form: 'list', title: 'name', subtitle: 'type', value: 'mem', bad: { field: 'status', op: '!=', value: 'running' } },
    },
    // proxmox.py: "/nodes".
    { id: 'nodes', icon: 'server', path: '/api2/json/nodes', every: '60s', rows: 'data' },
    // https://pve.proxmox.com/pve-docs/api-viewer/#/cluster/resources, type "storage".
    { id: 'storage', icon: 'storage', path: '/api2/json/cluster/resources?type=storage', every: '5m', rows: 'data' },
  ],
  plex: [
    // plex.py reads recentlyAdded per library; /library/recentlyAdded is all of them, the first twelve
    // (https://plexapi.dev, "Get Recently Added"), as the example card in notes/karten-testkarten.md.
    {
      id: 'recent',
      icon: 'pictures',
      path: '/library/recentlyAdded?X-Plex-Container-Start=0&X-Plex-Container-Size=12',
      every: '5m',
      rows: 'MediaContainer.Metadata',
      preset: { form: 'posters', image: 'thumb', title: 'title', subtitle: 'year' },
    },
    // plex.py: "/status/sessions".
    // Without a viewer the answer is `{"MediaContainer": {"size": 0}}`: there is no `Metadata` at all, which is an empty list.
    { id: 'playing', icon: 'play', path: '/status/sessions', every: '30s', rows: 'MediaContainer.Metadata', preset: { form: 'list', title: 'title', subtitle: 'User.title' } },
    // plex.py: "/library/sections".
    { id: 'libraries', icon: 'library', path: '/library/sections', every: '1h', rows: 'MediaContainer.Directory' },
  ],
  jellyfin: [
    // jellyfin.py: "/Items" with these parameters, as the example card in notes/karten-testkarten.md.
    {
      id: 'latest',
      icon: 'pictures',
      path: '/Items?SortBy=DateCreated&SortOrder=Descending&IncludeItemTypes=Movie,Series&Recursive=true&Limit=12&Fields=ProductionYear',
      every: '5m',
      rows: 'Items',
      image: '/Items/{Id}/Images/Primary?maxHeight=360',
      preset: { form: 'posters', image: '/Items/{Id}/Images/Primary?maxHeight=360', title: 'Name', subtitle: 'ProductionYear' },
    },
    // jellyfin.py: "/Sessions".
    { id: 'sessions', icon: 'play', path: '/Sessions', every: '30s', rows: '@', preset: { form: 'list', title: 'UserName', subtitle: 'DeviceName' } },
    // jellyfin.py: "/Library/VirtualFolders".
    { id: 'libraries', icon: 'library', path: '/Library/VirtualFolders', every: '1h', rows: '@' },
  ],
  immich: [
    // immich.py: `_get` puts /api in front of "/server/storage", "/server/statistics" and "/server/about".
    { id: 'storage', icon: 'storage', path: '/api/server/storage', every: '10m', fields: true },
    { id: 'statistics', icon: 'pictures', path: '/api/server/statistics', every: '1h' },
    { id: 'about', icon: 'info', path: '/api/server/about', every: '1h', fields: true },
  ],
  portainer: [
    // portainer.py: "/api/endpoints", the Docker environments.
    { id: 'environments', icon: 'server', path: '/api/endpoints', every: '5m', rows: '@' },
    // https://app.swaggerhub.com/apis/portainer/portainer-ce, "GET /stacks" (StackList).
    { id: 'stacks', icon: 'list', path: '/api/stacks', every: '5m', rows: '@' },
  ],
  sonarr: ARR_V3({ id: 'series', path: '/api/v3/series' }),
  radarr: ARR_V3({ id: 'movies', path: '/api/v3/movie' }),
  lidarr: [
    // lidarr.py: `api_version = "v1"`, `list_path = "artist"`; arr_base.py: queue (as for Sonarr: `pageSize`, `totalRecords`) and health.
    { id: 'queue', icon: 'download', path: '/api/v1/queue?pageSize=100', every: '60s', rows: 'records', total: 'totalRecords', preset: { form: 'list', title: 'title', subtitle: 'status' } },
    { id: 'health', icon: 'health', path: '/api/v1/health', every: '5m', rows: '@', preset: HEALTH },
    { id: 'artists', icon: 'library', path: '/api/v1/artist', every: '1h', rows: '@' },
  ],
  prowlarr: [
    // prowlarr.py: `api_version = "v1"`, `list_path = "indexer"`; arr_base.py: health.
    { id: 'indexers', icon: 'list', path: '/api/v1/indexer', every: '1h', rows: '@' },
    { id: 'health', icon: 'health', path: '/api/v1/health', every: '5m', rows: '@', preset: HEALTH },
  ],
  adguard: [
    // adguard.py: `_get` puts /control in front of "/stats" and "/status".
    { id: 'stats', icon: 'number', path: '/control/stats', every: '5m', fields: true },
    { id: 'status', icon: 'info', path: '/control/status', every: '5m', fields: true },
  ],
  truenas: [
    // truenas.py: the REST API below /api/v2.0, "/pool", "/alert/list" and "/system/info".
    { id: 'pools', icon: 'storage', path: '/api/v2.0/pool', every: '5m', rows: '@' },
    { id: 'alerts', icon: 'health', path: '/api/v2.0/alert/list', every: '5m', rows: '@' },
    { id: 'system', icon: 'info', path: '/api/v2.0/system/info', every: '1h', fields: true },
  ],
  traefik: [
    // traefik.py: `_get` puts /api in front of "/overview"; https://doc.traefik.io/traefik/operations/api/,
    // "/api/http/routers" and "/api/http/services".
    { id: 'routers', icon: 'list', path: '/api/http/routers', every: '5m', rows: '@' },
    { id: 'services', icon: 'server', path: '/api/http/services', every: '5m', rows: '@' },
    { id: 'overview', icon: 'number', path: '/api/overview', every: '5m', fields: true },
  ],
  audiobookshelf: [
    // audiobookshelf.py: `_get` puts /api in front of "/libraries" (under libraries) and "/users/online" (openSessions).
    { id: 'libraries', icon: 'library', path: '/api/libraries', every: '1h', rows: 'libraries' },
    { id: 'online', icon: 'people', path: '/api/users/online', every: '30s', rows: 'openSessions', preset: { form: 'list', title: 'displayTitle', subtitle: 'displayAuthor' } },
  ],
}
// emby.py: Emby is Jellyfin's adapter with another name, the same paths and the same answers.
SUGGESTIONS.emby = SUGGESTIONS.jellyfin

/** The suggestions for a kind of connection; none for a kind nexdeck has no list for. */
export function suggestionsFor(kind: string | undefined): CardSuggestion[] {
  return (kind && SUGGESTIONS[kind]) || []
}

/** The suggestion a card's request follows, by its path. */
export function suggestionOf(kind: string | undefined, path: string | undefined): CardSuggestion | null {
  if (!path) return null
  return suggestionsFor(kind).find((one) => one.path === path.trim()) ?? null
}

/** The words of a suggestion: emby shares Jellyfin's. */
export function wordsKey(kind: string, suggestion: CardSuggestion, part: 'title' | 'text' | 'label'): string {
  const own = kind === 'emby' ? 'jellyfin' : kind
  return `editor.guided.want.${own}.${suggestion.id}.${part}`
}
