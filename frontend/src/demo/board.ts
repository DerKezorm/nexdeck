/**
 * A board full of invented data, used by the design preview and by the
 * screenshots on the project page. Nothing here is real.
 */
import type { Breakpoint, LayoutItem, WidgetData, WidgetView } from '../lib/types'

function wave(count: number, base: number, amplitude: number, seed = 1): number[] {
  const out: number[] = []
  for (let i = 0; i < count; i++) {
    const t = i / 6 + seed
    out.push(Math.round((base + Math.sin(t) * amplitude + Math.sin(t * 2.7) * amplitude * 0.4 + (((i * seed * 31) % 7) - 3) * amplitude * 0.05) * 10) / 10)
  }
  return out
}

const uptime = (down: number[] = []) => Array.from({ length: 48 }, (_, i) => (down.includes(i) ? 0 : i < 3 ? null : 1))

interface DemoWidget {
  view: WidgetView
  data: WidgetData
  series?: Record<string, number[]>
  layout: { lg: [number, number, number, number]; md?: [number, number, number, number]; sm?: [number, number, number, number] }
}

export const DEMO_WIDGETS: DemoWidget[] = [
  {
    view: { id: 1, kind: 'core.clock', title: 'Clock', icon: '', link: '', renderer: 'clock', options: {}, integration_id: null, refresh_seconds: null },
    data: { status: 'ok', meta: { date: true, label: 'Home' } },
    layout: { lg: [0, 0, 3, 2], md: [0, 0, 4, 2], sm: [0, 0, 4, 2] },
  },
  {
    view: { id: 2, kind: 'weather.current', title: 'Weather', icon: 'lucide:cloud-sun', link: '', renderer: 'weather', options: {}, integration_id: null, refresh_seconds: 900 },
    data: {
      status: 'ok',
      primary: { label: 'Springfield', value: 21.4, unit: '°C' },
      secondary: [
        { label: 'Feels', value: 20.1, unit: '°C' },
        { label: 'Humidity', value: 58, unit: '%' },
      ],
      items: [
        { date: '2026-09-04', condition: 'partly-cloudy', high: 24, low: 14 },
        { date: '2026-09-05', condition: 'clear', high: 26, low: 15 },
        { date: '2026-09-06', condition: 'showers', high: 20, low: 13 },
        { date: '2026-09-07', condition: 'rain', high: 18, low: 12 },
        { date: '2026-09-08', condition: 'mostly-clear', high: 22, low: 13 },
      ],
      meta: { condition: 'partly-cloudy', is_day: true },
    },
    layout: { lg: [3, 0, 3, 2], md: [4, 0, 4, 2], sm: [0, 2, 4, 2] },
  },
  {
    view: { id: 3, kind: 'docker.load', title: 'Docker load', icon: 'docker', link: '', renderer: 'stats', options: {}, integration_id: 1, refresh_seconds: 20 },
    data: {
      status: 'ok',
      primary: { label: 'CPU', value: 38.2, unit: '%' },
      secondary: [
        { label: 'Memory', value: 62, unit: '%', metric: 'memory' },
        { label: 'Network', value: '48 MB/s', metric: 'net' },
      ],
      metrics: { cpu: 38.2, memory: 62, net: 48 },
    },
    series: { cpu: wave(40, 35, 12, 2), memory: wave(40, 60, 4, 3), net: wave(40, 40, 30, 5) },
    layout: { lg: [6, 0, 3, 2], md: [0, 2, 4, 2], sm: [0, 4, 4, 2] },
  },
  {
    view: { id: 4, kind: 'nexview.requests', title: 'Nexview requests', icon: 'lucide:clapperboard', link: '', renderer: 'value', options: {}, integration_id: 2, refresh_seconds: 60 },
    data: {
      status: 'warn',
      primary: { label: 'Open requests', value: 7 },
      secondary: [
        { label: 'Today', value: 3 },
        { label: 'Approved', value: 12 },
      ],
      metrics: { open: 7 },
      actions: [{ id: 'approve_all', label: 'Approve all', icon: 'check', confirm: true }],
    },
    series: { open: wave(40, 6, 3, 7).map((v) => Math.max(0, Math.round(v))) },
    layout: { lg: [9, 0, 3, 2], md: [4, 2, 4, 2], sm: [0, 6, 4, 2] },
  },
  {
    view: { id: 5, kind: 'docker.containers', title: 'Containers', icon: 'docker', link: '', renderer: 'list', options: {}, integration_id: 1, refresh_seconds: 15 },
    data: {
      status: 'warn',
      items: [
        { id: 'a', title: 'jellyfin', subtitle: 'Up 6 days', status: 'ok', state: 'running', cpu: 41.2, memory_percent: 38, value: '1.4 GB', actions: [{ id: 'restart', label: 'Restart', icon: 'rotate-cw', confirm: true }, { id: 'stop', label: 'Stop', icon: 'square', confirm: true, danger: true }] },
        { id: 'b', title: 'radarr', subtitle: 'Up 6 days', status: 'ok', state: 'running', cpu: 2.1, memory_percent: 12, value: '412 MB', actions: [{ id: 'restart', label: 'Restart', icon: 'rotate-cw', confirm: true }] },
        { id: 'c', title: 'sonarr', subtitle: 'Up 6 days', status: 'ok', state: 'running', cpu: 1.7, memory_percent: 10, value: '386 MB', actions: [{ id: 'restart', label: 'Restart', icon: 'rotate-cw', confirm: true }] },
        { id: 'd', title: 'sabnzbd', subtitle: 'Exited (1) 4 minutes ago', status: 'bad', state: 'exited', actions: [{ id: 'start', label: 'Start', icon: 'play' }] },
        { id: 'e', title: 'nexview', subtitle: 'Up 2 days', status: 'ok', state: 'running', cpu: 0.8, memory_percent: 6, value: '148 MB', actions: [] },
        { id: 'f', title: 'pihole', subtitle: 'Up 13 days', status: 'ok', state: 'running', cpu: 0.4, memory_percent: 3, value: '92 MB', actions: [] },
        { id: 'g', title: 'traefik', subtitle: 'Up 13 days', status: 'ok', state: 'running', cpu: 0.9, memory_percent: 4, value: '110 MB', actions: [] },
        { id: 'h', title: 'postgres', subtitle: 'Up 13 days', status: 'ok', state: 'running', cpu: 1.2, memory_percent: 9, value: '340 MB', actions: [] },
      ],
      secondary: [
        { label: 'Running', value: 7 },
        { label: 'Stopped', value: 1 },
      ],
    },
    layout: { lg: [0, 2, 4, 4], md: [0, 4, 4, 4], sm: [0, 8, 4, 4] },
  },
  {
    view: { id: 6, kind: 'jellyfin.nowplaying', title: 'Now playing', icon: 'jellyfin', link: '', renderer: 'nowplaying', options: {}, integration_id: 3, refresh_seconds: 15 },
    data: {
      status: 'ok',
      items: [
        { title: 'The Quiet Harbour', subtitle: 'Living room · 4K · Direct play', progress: 42, remaining: '1:04', state: 'playing' },
        { title: 'Harbour Lights S03E04', subtitle: 'Bedroom TV · 1080p · Transcode', progress: 71, remaining: '0:14', state: 'playing' },
        { title: 'Orbital', subtitle: 'Phone · 720p', progress: 12, remaining: '1:52', state: 'paused' },
      ],
      secondary: [
        { label: 'Streams', value: 3 },
        { label: 'Transcoding', value: 1 },
        { label: 'Bandwidth', value: '34 Mbps' },
      ],
    },
    layout: { lg: [4, 2, 4, 3], md: [4, 4, 4, 3], sm: [0, 12, 4, 3] },
  },
  {
    view: { id: 7, kind: 'radarr.queue', title: 'Radarr queue', icon: 'radarr', link: '', renderer: 'list', options: {}, integration_id: 4, refresh_seconds: 20 },
    data: {
      status: 'ok',
      items: [
        { title: 'Copper Sky (2025)', subtitle: '12 min left · 4.2 GB', progress: 78, value: '78%', status: 'ok' },
        { title: 'Nightshift (2026)', subtitle: '41 min left · 7.9 GB', progress: 34, value: '34%', status: 'ok' },
        { title: 'The Last Ferry (2026)', subtitle: 'Importing', progress: 100, value: '100%', status: 'ok' },
        { title: 'Paper Towns of Mars (2026)', subtitle: 'Stalled · no connections', progress: 3, value: '3%', status: 'warn' },
      ],
      secondary: [{ label: 'In queue', value: 4 }],
      actions: [{ id: 'search_missing', label: 'Search missing', icon: 'search', confirm: true }],
    },
    layout: { lg: [8, 2, 4, 3], md: [0, 8, 4, 3], sm: [0, 15, 4, 3] },
  },
  ...['radarr', 'sonarr', 'jellyfin', 'pi-hole'].map((name, index) => ({
    view: {
      id: 10 + index,
      kind: 'core.app',
      title: name === 'pi-hole' ? 'Pi-hole' : name.charAt(0).toUpperCase() + name.slice(1),
      icon: name,
      link: `https://${name}.example.com`,
      renderer: 'app',
      options: {},
      integration_id: null,
      refresh_seconds: null,
      health: { id: index, kind: 'http', target: '', last_ok: name !== 'sonarr', last_latency_ms: [42, 1230, 58, 12][index], down_since: name === 'sonarr' ? '2026-09-04T10:00:00Z' : null, last_error: '', bars: uptime(name === 'sonarr' ? [44, 45, 46, 47] : name === 'jellyfin' ? [21] : []) },
    } as WidgetView,
    data: { status: 'ok', meta: { description: ['Movies', 'Series', 'Media server', 'DNS filter'][index] } } as WidgetData,
    layout: { lg: [4 + index * 2, 5, 2, 1] as [number, number, number, number], md: [4 + (index % 2) * 2, 7 + Math.floor(index / 2), 2, 1] as [number, number, number, number], sm: [(index % 2) * 2, 18 + Math.floor(index / 2), 2, 1] as [number, number, number, number] },
  })),
  {
    view: { id: 20, kind: 'proxmox.node', title: 'Proxmox · pve', icon: 'proxmox', link: '', renderer: 'stats', options: {}, integration_id: 5, refresh_seconds: 20 },
    data: {
      status: 'ok',
      primary: { label: 'CPU', value: 23.4, unit: '%' },
      secondary: [
        { label: 'Memory', value: 61, unit: '%', metric: 'memory' },
        { label: 'Storage', value: 44, unit: '%' },
        { label: 'Uptime', value: '41d 6h' },
      ],
      metrics: { cpu: 23.4, memory: 61 },
    },
    series: { cpu: wave(40, 22, 10, 11), memory: wave(40, 60, 3, 12) },
    layout: { lg: [0, 6, 4, 2], md: [0, 11, 4, 2], sm: [0, 20, 4, 2] },
  },
  {
    view: { id: 21, kind: 'pihole.summary', title: 'Pi-hole', icon: 'pi-hole', link: '', renderer: 'gauge', options: {}, integration_id: 6, refresh_seconds: 30 },
    data: {
      status: 'ok',
      primary: { label: 'Blocked today', value: 18.4, unit: '%' },
      secondary: [
        { label: 'Queries', value: 42310 },
        { label: 'Blocked', value: 7788 },
      ],
      actions: [{ id: 'disable', label: 'Pause 5 min', icon: 'pause' }],
    },
    layout: { lg: [4, 6, 2, 2], md: [4, 9, 4, 2], sm: [0, 22, 4, 2] },
  },
  {
    view: { id: 22, kind: 'uptimekuma.monitors', title: 'Uptime Kuma', icon: 'uptime-kuma', link: '', renderer: 'list', options: {}, integration_id: 7, refresh_seconds: 30 },
    data: {
      status: 'warn',
      items: [
        { title: 'Reverse proxy', subtitle: '100% · 24h', status: 'ok', value: '18 ms' },
        { title: 'Nexview', subtitle: '100% · 24h', status: 'ok', value: '52 ms' },
        { title: 'Jellyfin', subtitle: '99.7% · 24h', status: 'ok', value: '61 ms' },
        { title: 'SABnzbd', subtitle: 'Down 4 min', status: 'bad', value: 'timeout' },
        { title: 'Home Assistant', subtitle: '100% · 24h', status: 'ok', value: '9 ms' },
        { title: 'NAS', subtitle: '100% · 24h', status: 'ok', value: '3 ms' },
      ],
      secondary: [
        { label: 'Up', value: 5 },
        { label: 'Down', value: 1 },
      ],
    },
    layout: { lg: [6, 6, 3, 3], md: [0, 13, 4, 3], sm: [0, 24, 4, 3] },
  },
  {
    view: { id: 23, kind: 'calendar.upcoming', title: 'Upcoming', icon: 'lucide:calendar-days', link: '', renderer: 'calendar', options: {}, integration_id: null, refresh_seconds: 600 },
    data: {
      status: 'ok',
      items: [
        { date: '2026-09-04', title: 'Harbour Lights', subtitle: 'S03E05', status: 'warn' },
        { date: '2026-09-04', title: 'Copper Sky', subtitle: 'Digital release', status: 'ok' },
        { date: '2026-09-05', title: 'Orbital Decay', subtitle: 'S01E09', status: 'warn' },
        { date: '2026-09-06', title: 'Nightshift', subtitle: 'Digital release', status: 'warn' },
        { date: '2026-09-07', title: 'Northern Shore', subtitle: 'S01E04', status: 'warn' },
      ],
    },
    layout: { lg: [9, 6, 3, 3], md: [4, 11, 4, 3], sm: [0, 27, 4, 3] },
  },
  {
    view: { id: 24, kind: 'rss.headlines', title: 'Homelab news', icon: 'lucide:rss', link: '', renderer: 'feed', options: {}, integration_id: null, refresh_seconds: 900 },
    data: {
      status: 'ok',
      items: [
        { title: 'New release: nexdeck 0.1.0 brings live boards', source: 'nexapps blog', published: Date.now() / 1000 - 3600 },
        { title: 'Why your NAS deserves a real dashboard', source: 'Homelab Weekly', published: Date.now() / 1000 - 7200 },
        { title: 'Proxmox 9.1: what changed for LXC networking', source: 'Virtualisation News', published: Date.now() / 1000 - 12000 },
        { title: 'A cheap 10G switch that does not sound like a jet', source: 'Rack Notes', published: Date.now() / 1000 - 40000 },
        { title: 'Jellyfin adds trickplay by default', source: 'Media Server Digest', published: Date.now() / 1000 - 90000 },
      ],
      meta: { style: 'list' },
    },
    layout: { lg: [0, 8, 4, 3], md: [0, 16, 4, 3], sm: [0, 30, 4, 3] },
  },
  {
    view: { id: 25, kind: 'speedtest.latest', title: 'Speedtest', icon: 'lucide:gauge', link: '', renderer: 'value', options: {}, integration_id: 8, refresh_seconds: 600 },
    data: {
      status: 'ok',
      primary: { label: 'Download', value: 941, unit: 'Mbps' },
      secondary: [
        { label: 'Upload', value: 48, unit: 'Mbps' },
        { label: 'Ping', value: 9, unit: 'ms' },
      ],
      metrics: { download: 941 },
    },
    series: { download: wave(40, 920, 40, 21) },
    layout: { lg: [4, 8, 2, 2], md: [4, 14, 4, 2], sm: [0, 33, 4, 2] },
  },
  {
    view: { id: 26, kind: 'synology.system', title: 'NAS · storage', icon: 'synology', link: '', renderer: 'stats', options: {}, integration_id: 9, refresh_seconds: 30 },
    data: {
      status: 'warn',
      primary: { label: 'Volume 1', value: 82, unit: '%' },
      secondary: [
        { label: 'CPU', value: 12, unit: '%', metric: 'cpu' },
        { label: 'Memory', value: 34, unit: '%' },
        { label: 'Temp', value: 41, unit: '°C' },
      ],
      metrics: { volume: 82, cpu: 12 },
    },
    series: { cpu: wave(40, 12, 6, 31) },
    layout: { lg: [6, 9, 4, 2], md: [0, 19, 4, 2], sm: [0, 35, 4, 2] },
  },
  {
    view: { id: 27, kind: 'homeassistant.entity', title: 'Living room', icon: 'home-assistant', link: '', renderer: 'value', options: {}, integration_id: 10, refresh_seconds: 10 },
    data: {
      status: 'ok',
      primary: { label: 'Temperature', value: 21.5, unit: '°C' },
      secondary: [
        { label: 'Lights on', value: 3 },
        { label: 'Doors', value: 'closed' },
      ],
      metrics: { temperature: 21.5 },
      actions: [{ id: 'scene', label: 'Evening scene', icon: 'lamp' }],
    },
    series: { temperature: wave(40, 21.5, 0.8, 41) },
    layout: { lg: [10, 9, 2, 2], md: [4, 16, 4, 2], sm: [0, 37, 4, 2] },
  },

  // --- The three drawings a card can be asked for -------------------------
  {
    view: { id: 28, kind: 'prowlarr.indexers', title: 'Indexers', icon: 'prowlarr', link: '', renderer: 'list', options: { view: 'bars' }, integration_id: 11, refresh_seconds: 300 },
    data: {
      status: 'ok',
      items: [
        { title: 'NZBgeek', value: 412 },
        { title: 'DrunkenSlug', value: 268 },
        { title: 'NZBFinder', value: 121 },
        { title: 'Tabula Rasa', value: 47 },
        { title: 'Newznab', value: 9 },
      ],
      secondary: [{ label: 'Grabs', value: 857 }],
      meta: { renderer: 'bars' },
    },
    layout: { lg: [0, 11, 4, 3], md: [0, 18, 4, 3], sm: [0, 39, 4, 3] },
  },
  {
    view: { id: 29, kind: 'pihole.summary', title: 'Pi-hole', icon: 'pi-hole', link: '', renderer: 'gauge', options: { view: 'ring' }, integration_id: 12, refresh_seconds: 30 },
    data: {
      status: 'ok',
      primary: { label: 'Blocked today', value: 18.4, unit: '%' },
      secondary: [
        { label: 'Queries', value: 38412 },
        { label: 'Clients', value: 23 },
      ],
      metrics: { blocked_percent: 18.4, queries: 38412 },
      meta: {
        renderer: 'ring',
        // Blocked is already inside the total, so the second slice is the
        // difference and not the total itself.
        ring: [
          { label: 'Blocked', value: 7068 },
          { label: 'Allowed', value: 31344 },
        ],
      },
    },
    layout: { lg: [4, 11, 3, 3], md: [4, 18, 4, 3], sm: [0, 42, 4, 3] },
  },
  {
    view: { id: 30, kind: 'unifi.console', title: 'WAN', icon: 'unifi', link: '', renderer: 'list', options: { view: 'chart' }, integration_id: 13, refresh_seconds: 30 },
    data: {
      status: 'ok',
      primary: { label: 'WAN in', value: 42.6, unit: 'MB/s', metric: 'wan_down' },
      secondary: [{ label: 'WAN out', value: 8.1, unit: 'MB/s', metric: 'wan_up' }],
      metrics: { wan_down: 42.6, wan_up: 8.1 },
      meta: { renderer: 'chart' },
    },
    series: { wan_down: wave(40, 40, 14, 7), wan_up: wave(40, 8, 3.5, 19) },
    layout: { lg: [7, 11, 5, 3], md: [0, 21, 8, 3], sm: [0, 45, 4, 3] },
  },
  {
    // The same card as `plex.load` on the Media board, asked for a dial and
    // told which of its four rows the needle follows.
    view: { id: 31, kind: 'plex.load', title: 'Server load', icon: 'plex', link: '', renderer: 'stats', options: { view: 'gauge', gauge_part: 'host_memory' }, integration_id: 14, refresh_seconds: 15 },
    data: {
      status: 'ok',
      primary: { label: 'Host RAM', value: 62, unit: '%', metric: 'host_memory', part: 'host_memory' },
      secondary: [
        { label: 'Plex CPU', value: 0, unit: '%', metric: 'plex_cpu' },
        { label: 'Plex RAM', value: 0.5, unit: '%', metric: 'plex_memory' },
        { label: 'Host CPU', value: 16, unit: '%', metric: 'host_cpu' },
      ],
      metrics: { host_memory: 62, plex_cpu: 0, plex_memory: 0.5, host_cpu: 16 },
      meta: { renderer: 'gauge', gauge: { share: 62 } },
    },
    layout: { lg: [0, 14, 3, 3], md: [0, 24, 4, 3], sm: [0, 48, 4, 3] },
  },
  {
    // The one card with a field. The blank the button leaves is part of the
    // action, so the preview carries it exactly as a fetch would.
    view: { id: 32, kind: 'metube.fetch', title: 'Fetch a video', icon: 'metube', link: '', renderer: 'ask', options: {}, integration_id: 15, refresh_seconds: 15 },
    data: {
      status: 'warn',
      actions: [{
        id: 'add', label: 'Fetch', icon: 'download',
        params: { download_type: 'video', quality: 'best', format: 'any' },
        ask: { name: 'url', label: 'Video address', kind: 'url', placeholder: 'https://...', max_length: 2048 },
      }],
      items: [{ title: 'How a cylinder lock works', subtitle: '42% · 2.3 MB/s · 40s left', status: 'warn' }],
      secondary: [{ label: 'Running', value: 1 }],
      metrics: { running: 1 },
    },
    layout: { lg: [3, 14, 3, 2], md: [4, 24, 4, 2], sm: [0, 51, 4, 2] },
  },
]

export const DEMO_LAYOUTS: Record<Breakpoint, LayoutItem[]> = {
  lg: DEMO_WIDGETS.map(({ view, layout }) => ({ i: String(view.id), x: layout.lg[0], y: layout.lg[1], w: layout.lg[2], h: layout.lg[3] })),
  md: DEMO_WIDGETS.map(({ view, layout }) => {
    const l = layout.md ?? layout.lg
    return { i: String(view.id), x: l[0], y: l[1], w: l[2], h: l[3] }
  }),
  sm: DEMO_WIDGETS.map(({ view, layout }) => {
    const l = layout.sm ?? layout.lg
    return { i: String(view.id), x: l[0], y: l[1], w: Math.min(4, l[2]), h: l[3] }
  }),
}

export const DEMO_VIEWS: WidgetView[] = DEMO_WIDGETS.map((w) => w.view)
export const DEMO_DATA: Record<number, WidgetData> = Object.fromEntries(DEMO_WIDGETS.map((w) => [w.view.id, w.data]))
export const DEMO_SERIES: Record<number, Record<string, number[]>> = Object.fromEntries(DEMO_WIDGETS.filter((w) => w.series).map((w) => [w.view.id, w.series!]))
