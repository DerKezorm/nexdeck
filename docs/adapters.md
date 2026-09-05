# Integrations and widgets

An **integration** is one configured connection to a service: an address and
credentials. A **widget** shows one view of it on a board. Many widgets can
share one integration; the server asks the service once per widget interval
and caches identical requests for a few seconds.

Every adapter lives in one file under `backend/app/adapters/`. It declares
its connection fields, its widgets, and how to fetch, act and fake data.
The frontend never knows a service: every widget returns a `WidgetData`
that one of fifteen renderers draws.

## Adapters in 0.1.0

| Adapter | Widgets | Actions | Credentials |
|---|---|---|---|
| Docker | containers, summary, load, logs | start, stop, restart, pause, resume | socket or TCP |
| Proxmox VE | node, guests, summary | start, shutdown, reboot | API token |
| Portainer | containers, summary | container actions | access token |
| Synology DSM | system, volumes, disks, containers, vms | start, stop, restart; power on, shut down, reboot | user and password; containers and VM details through DSM's own interface calls |
| Unraid | system, array, guests | | API key (GraphQL) |
| TrueNAS | system, pools, alerts | | API key |
| Pi-hole | summary, top blocked | pause 5 min, enable | app password (v6) |
| AdGuard Home | summary, top blocked | pause 5 min, enable | user and password |
| UniFi Network | network, console, devices, findings, wlans | | API key (Network 9.0+), or a local account without two-factor |
| Speedtest Tracker | latest | | API token |
| Plex | now playing, library, recently added (covers), findings, server load, users and devices, top of the week | | Sign in with Plex (PIN at plex.tv fills token and server address), or the owner's token |
| Jellyfin, Emby | now playing, library, recently added (covers), findings, users and devices, top of the week | | API key |
| Nexview | requests, library, instances | | API key |
| Seerr | requests, counts | approve, decline | API key |
| Radarr, Sonarr, Lidarr, Readarr | queue, status, calendar | search missing | API key |
| Prowlarr | indexers, status | | API key |
| SABnzbd, NZBGet, qBittorrent, Transmission, Deluge | queue, speed | pause, resume | key or password |
| Home Assistant | entity, entity list | turn on/off, scenes, scripts, covers, locks | long-lived token; live over WebSocket |
| Uptime Kuma | monitors, summary | | API key (metrics endpoint) |
| Beszel | hosts, host | | user and password |
| Glances | system, file systems, sensors | | optional password |
| Prometheus | query value, query list | | optional basic auth |
| JSON API | value, list | | optional bearer token |
| iCal | events | | feed address |
| Weather (Open-Meteo), RSS, Calendar, Basics | current, headlines, upcoming, clock, notes, bookmarks, iframe, app tile | | none |

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

A card can be enlarged but never made smaller than its `default_size`;
`min_size` is what the server uses when it has to squeeze a new widget into
a tight spot.

## Renderers

`value`, `gauge`, `stats`, `list`, `nowplaying`, `calendar`, `text`,
`bookmarks`, `iframe`, `clock`, `weather`, `feed`, `log`, `chart`, `app`, `posters`,
`counters`. A fetch may pick another renderer for its data through
`meta["renderer"]`; the media library card uses that for its icon row.

Images such as posters are never linked with a token in the browser: an adapter
hands out `proxy:/path`, and `GET /api/v1/widgets/{id}/image?path=` fetches it
from the service with the adapter's `image_headers`, cached for an hour.

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
