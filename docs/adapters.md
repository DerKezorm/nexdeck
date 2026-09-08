# Integrations and widgets

An **integration** is one configured connection to a service: an address and
credentials. A **widget** shows one view of it on a board. Many widgets can
share one integration; the server asks the service once per widget interval
and caches identical requests for a few seconds.

Every adapter lives in one file under `backend/app/adapters/`. It declares
its connection fields, its widgets, and how to fetch, act and fake data.
The frontend never knows a service: every widget returns a `WidgetData`
that one of fifteen renderers draws.

## Adapters in 0.2.0

| Adapter | Widgets | Actions | Credentials |
|---|---|---|---|
| Docker | containers, summary, load, logs | start, stop, restart, pause, resume | socket or TCP |
| Proxmox VE | node, guests, summary | start, shutdown, reboot | API token |
| Portainer | containers, summary | container actions | access token |
| Coolify | applications, deployments, status | | API token; the API has to be switched on in Coolify |
| Synology DSM | system, volumes, disks, containers, vms | start, stop, restart; power on, shut down, reboot | user and password; containers and VM details through DSM's own interface calls |
| Unraid | system, array, guests | | API key (GraphQL) |
| Nextcloud | overview, active users, free space | | serverinfo token, or an administrator account |
| TrueNAS | system, pools, alerts | | API key |
| Proxmox Backup Server | datastores, host, tasks | | API token; DatastoreAudit on /datastore and Sys.Audit on /system |
| Syncthing | folders, status | | API key |
| Pi-hole | summary, top blocked | pause 5 min, enable | app password (v6) |
| AdGuard Home | summary, top blocked | pause 5 min, enable | user and password |
| UniFi Network | network, console, devices, findings, wlans | | API key (Network 9.0+), or a local account without two-factor |
| Speedtest Tracker | latest | | API token |
| Traefik | overview, routers | | none, or basic authentication |
| Nginx Proxy Manager | proxy hosts, certificates, status | | an account; the token is fetched and kept |
| OPNsense | system, gateways | | API key and secret |
| pfSense | system, interfaces | | API key of the package pfSense-pkg-RESTAPI |
| MikroTik | system, interfaces | | user with the read policy; needs RouterOS 7 with the REST service on |
| FRITZ!Box | connection, line | | none; TR-064 on port 49000, the part of it that answers without credentials |
| Tailscale | devices, status | | API access token from the admin console |
| Headscale | nodes, status | | API key from `headscale apikeys create` |
| Gluetun | tunnel | | none, or the API key if the control server has roles |
| Technitium DNS | blocking, top blocked | | API token |
| NextDNS | blocking, top blocked | | API key and the profile ID |
| authentik | status, failed sign-ins | | API token of a service account with read access |
| Reolink | cameras, camera (snapshot or live video), findings | | user and password of a device account; HTTP or HTTPS switched on in the device's port settings |
| Frigate | cameras, detections, status | | none |
| Plex | now playing, library, recently added (covers), findings, server load, users and devices, top of the week | | Sign in with Plex (PIN at plex.tv fills token and server address), or the owner's token |
| Jellyfin, Emby | now playing, library, recently added (covers), findings, users and devices, top of the week | | API key |
| Nexview | requests, library, instances | | API key |
| Seerr | requests, counts | approve, decline | API key |
| Overseerr, Jellyseerr | requests, counts | approve, decline | API key; same API as Seerr, listed under their own names |
| Tautulli | now playing, streams, most watched | | API key |
| Immich | archive, storage, users | | API key of an administrator |
| Bazarr | status, missing subtitles, recently fetched | | API key |
| Audiobookshelf | library, listening now | | API key |
| Navidrome | library, playing now | | account; the Subsonic API signs each request with a salted token |
| Komga | library, recently added | | API key, or the account on older versions |
| Kavita | library, recently added | | API key; the token is fetched once and kept |
| Calibre-Web | library, recently added | | account; it has no API, so the address of its own table view is used |
| Tdarr | queue, nodes | | optional API key |
| Unmanic | workers, queue | | none |
| FileFlows | status, running | | optional access token |
| Maintainerr | collections, status | | none |
| Jellystat | libraries, most watched | | API key |
| Radarr, Sonarr, Lidarr, Readarr | queue, status, calendar | search missing | API key |
| Prowlarr | indexers, status | | API key |
| SABnzbd, NZBGet, qBittorrent, Transmission, Deluge | queue, speed | pause, resume | key or password |
| Home Assistant | entity, entity list | turn on/off, scenes, scripts, covers, locks | long-lived token; live over WebSocket |
| Uptime Kuma | monitors, summary | | API key (metrics endpoint) |
| n8n | workflows, last runs, summary | publish, unpublish | API key from Settings > n8n API |
| Beszel | hosts, host | | user and password |
| Glances | system, file systems, sensors | | optional password |
| Scrutiny | disks, disk health | | none |
| UPS (PeaNUT) | UPS, UPS details | | optional sign-in |
| Gotify | messages, message count | | client token (an application token may only write) |
| ntfy | messages | | topic, and a token for a protected one |
| Prometheus | query value, query list | | optional basic auth |
| Grafana | alerts, status | | service account token; needs unified alerting, so Grafana 9.0 or newer |
| JSON API | value, list | | optional bearer token |
| iCal feed | events | | feed address |
| Paperless-ngx | archive, latest documents | | API token from the user profile |
| evcc | energy, charging | | none; the state is readable without a password |
| Weather (Open-Meteo), RSS feeds, Calendar, Basics | current, headlines, upcoming, clock, notes, bookmarks, iframe, app tile | | none |
| Hacker News | stories | | none |
| YouTube | videos | | none; the channel feeds need no account |
| GitHub releases | releases | | none; sixty requests an hour per address |
| Share prices | prices | | none |
| Twitch | live | | client ID and secret of an application at dev.twitch.tv |
| Wake-on-LAN | wake | wake | none; a MAC address and a network that carries the broadcast |

Adapters marked **beta** in the interface have not been confirmed against a
live instance yet. They are built against the documented API and recorded
answers; a report with the service's version is welcome.

### Texts

Everything an adapter says is English: field labels, help texts, widget names
and descriptions, and the labels of values, chips, rows and actions. The
interface translates them by their English wording from
`frontend/src/i18n/texts.de.json`; a guard in `backend/tests/test_guards.py`
fails when a new text has no German entry. Data that is not a label (names,
sizes, identifiers) passes through untouched.

A widget that draws itself from its options (clock, notes, bookmarks, embedded
page, app tile) sets `client_only=True`; the settings sheet then hides the
refresh interval. A field of type `timezone` is offered as a list of IANA
zones. `POST /api/v1/widgets/{id}/preview` runs a fetch with draft options
without saving; the settings sheet uses it for its live preview.

An app tile may follow an integration: pick one in its settings and the
tile's link and its reachability check take the integration's address on
every read, so a changed address is changed once. A link of the tile's own
still wins.

A card can be enlarged but never made smaller than its `default_size`;
`min_size` is what the server uses when it has to squeeze a new widget into
a tight spot.

## Renderers

`value`, `gauge`, `stats`, `list`, `nowplaying`, `calendar`, `text`,
`bookmarks`, `iframe`, `clock`, `weather`, `feed`, `log`, `chart`, `app`, `posters`,
`counters`, `camera`. A fetch may pick another renderer for its data through
`meta["renderer"]`; the media library card uses that for its icon row.

Images such as posters are never linked with a token in the browser: an adapter
hands out `proxy:/path`, and `GET /api/v1/widgets/{id}/image?path=` fetches it
from the service with the adapter's `image_headers`, cached for an hour. An adapter
may override `image_source(config, path, ctx)` to turn a path into another request,
for example a camera snapshot with a session token that must not be cached
(`cache_seconds=0`). Live video goes the same way: `stream_source(config, options,
ctx)` names an HTTP-FLV stream, and `GET /api/v1/widgets/{id}/stream` relays its
bytes to the browser, which plays them with Media Source Extensions. The server
relays at most twelve streams at once.

## Writing an adapter

```python
from .base import Adapter, Context, Field, WidgetData, WidgetType, base_url

class ExampleAdapter(Adapter):
    kind = "example"
    label = "Example"
    category = "monitoring"
    description = "What it shows."
    icon = "example"          # a dashboard-icons name
    fields = (
        Field("url", "URL", type="url", required=True),
        Field("api_key", "API key", type="password", secret=True, required=True),
    )
    widgets = (
        WidgetType(kind="status", label="Status", description="...", renderer="value",
                   default_size=(2, 2), refresh_seconds=30, metrics=("value",)),
    )

    async def test(self, config, ctx):
        payload = await ctx.get_json(f"{base_url(config)}/api/version", headers={"X-Api-Key": config["api_key"]})
        return f"Example {payload['version']} answers."

    async def fetch(self, widget_kind, config, options, ctx):
        payload = await ctx.get_json(f"{base_url(config)}/api/status", headers={"X-Api-Key": config["api_key"]})
        return WidgetData(primary={"label": "Load", "value": payload["load"], "unit": "%"}, metrics={"value": payload["load"]})

    def demo(self, widget_kind, options, tick):
        from . import demo as fake
        value = fake.walk("example", tick, 5, 60)
        return WidgetData(primary={"label": "Load", "value": value, "unit": "%"}, metrics={"value": value})

ADAPTER = ExampleAdapter()
```

Rules:

- Secrets are fields with `secret=True`; they are encrypted at rest and never returned by the API.
- Raise `AdapterError` (or `AuthFailed`, `Unreachable`) with an English message and a hint; the card shows both.
- `metrics` are numbers recorded for sparklines; name them stably.
- `demo()` must return believable, moving data for every widget kind; a test checks that.
- Add a test with recorded answers under `backend/tests/`, using `respx`.
