# API

nexdeck's own interface uses the same API that is open to you. The
interactive documentation lives at `/api/docs` on every installation.

## Authentication

- **Browser session:** a cookie, set by `POST /api/v1/auth/login`. Unsafe methods need the header `X-Nexdeck-Request: 1`, which a cross-site form cannot send.
- **API token:** `Authorization: Bearer nd_…`. Create one under My settings > API tokens. A new token only reads: every method but `GET`, `HEAD` and `OPTIONS` is refused with `403` and the code `token_read_only`, and so are the few reads that set something going on a service (the image relay `GET /api/v1/widgets/{id}/image`, the track relay `GET /api/v1/widgets/{id}/audio/...`, `GET /api/v1/push/key`). Pick "Full access" for a script that has to change something; it then has the rights of its account. Tokens made before nexdeck had this choice keep full access.
- **Kiosk token:** `X-Kiosk-Token: nk_…` or `?kiosk=nk_…`. Reads one board, nothing else.

## Useful addresses

| Address | Purpose |
|---|---|
| `GET /api/v1/boards` | Boards the caller may open. |
| `GET /api/v1/boards/{slug}` | A board with pages, widgets and the latest live data. |
| `GET /api/v1/boards/{slug}/history` | Metric history of every widget for sparklines. |
| `GET /api/v1/stream?board={slug}` | Server-Sent Events: `widget`, `health`, `board`, `layout`, `log`, `notice`. |
| `POST /api/v1/widgets/{id}/actions/{action}` | Run a widget action with `{"params": {...}}`. Needs the act permission. `"via": "assistant"` marks a press in the chat; the action log says so. |
| `POST /api/v1/widgets/{id}/actions/{action}/impact` | What the action would hit, as facts: `up` (Docker's own words), `streams` (who is watching on a media server the container is named after), `downloads`, `devices` and `last_run` (a Home Assistant scene, group, script or automation). Same body and right as running it; nothing runs. |
| `GET /api/v1/widgets/{id}/data` | The latest data of one widget. A `forecast` says when a volume is full, a number reaches its line or a backup gets slower; a `cause` names what it is down because of. |
| `GET /api/v1/widgets/{id}/history/long` | A widget's history over `days` (up to 730) as `[[ts, avg, min, max], ...]` per metric: hours up to 30 days, days beyond. `metric` narrows it to one. |
| `POST /api/v1/widgets/{id}/refresh` | Fetch right now. |
| `GET /api/v1/widgets/{id}/music/{view}` | The library of a music player card: `albums`, `artists`, `artist`, `album`, `playlists`, `playlist`, `search`, `shuffle`, and `mix` on Jellyfin and Emby. `id`, `q`, `sort` and `offset` narrow it down. Needs the act permission. |
| `GET /api/v1/widgets/{id}/audio/{track_id}` | The sound of one track, relayed by nexdeck with `Range` passed through. `quality` is `original`, `high` or `low`, `formats` lists what the browser plays, `start` is where converted sound begins. Needs the act permission. |
| `POST /api/v1/widgets/{id}/music/playlists` | Create a playlist on the media server with `{"name": "...", "track_ids": [...]}`. `POST` and `DELETE` on `.../playlists/{playlist_id}/tracks` add tracks (`track_ids`) and take entries out (`entries`); `PATCH` and `DELETE` on `.../playlists/{playlist_id}` rename and delete. Smart playlists on Plex are refused. Needs the act permission. |
| `GET /api/v1/chronicle` | The chronicle, newest first: `days` (1, 7, 30 or 365), `group` (`all`, `cards`, `versions`, `nexdeck`), `q` for words, `before` with the id of the last line for the page after. Administrators get every line, everybody else the lines about boards they may open. |
| `GET /api/v1/settings/assistant` | The assistant's provider: `provider` (`off`, `anthropic`, `openai`), `base_url`, `model`, whether a key is set (`has_key`, never the key), `ready` and `leaves_the_house`. `PUT` sets it with an optional `key` (left out keeps it, empty removes it); `POST .../test` asks the provider one short question, `POST .../models` with `provider`, `base_url` and an optional `key` lists the models the service offers (a stored key goes only to the stored service). Administrators only. |
| `POST /api/v1/assistant/chat` | Ask the assistant `{"text": "...", "conversation_id": ...}`; `about` with a service's ref says the question comes from its diagnosis page. The answer comes with `citations` (cards and the chronicle it looked at), `proposals` (buttons with what they would hit; never pressed), `permissions` (a container log it wants to read) and `refused`. `GET /api/v1/assistant/conversations` lists the own conversations of the last 30 days, `GET`/`DELETE .../{id}` shows or deletes one, `DELETE` on the list deletes all, `POST .../{id}/allow` with `{"grant": "log:<connection>:<container>"}` allows a log in that conversation. Administrators only. |
| `GET /api/v1/inventory` | Every connection, app tile, container and guest as `nodes` (with `parent` where an engine or hypervisor said so, `down`, addresses), and every `relation` with its `origin` (`auto`, `manual`, `suggested`) and `state` (`on`, `suggested`, `rejected`). `POST /api/v1/inventory/refresh` asks the engines and hypervisors now. Administrators only. |
| `POST /api/v1/relations` | Say that `child` runs on or needs `parent`, both as refs from the inventory (`integration:3`, `widget:12`, `container:1:plex`, `guest:5:101`). A circle, the same ref twice or a relation that is there already is refused. `POST .../{id}/confirm` says yes to a proposed one, `DELETE .../{id}` removes one set by hand and says no to any other, which nexdeck then never proposes again. Administrators only. |
| `GET /api/v1/diagnosis?ref=...` | Why one service is in trouble, by its ref from the inventory: `state` (`now`, `past` or `ok`), `since` and `until`, `reason`, the `cause` it hangs on that is down, the chronicle `lines` of the two hours before (each with `via` when it is about something it runs on), `above` and `below` in the inventory, its `cards` and `checks`, whether its container's `log` can be read, the `buttons` of that container and its `runbook`. `at` (epoch seconds) asks for a trouble that has ended. `POST /api/v1/diagnosis/log` with `{"ref": ...}` reads the last 100 lines of its container's log with secrets masked; `PUT /api/v1/diagnosis/runbook` with `ref`, `text` and `link` keeps the runbook, an empty one removes it. Administrators only. |
| `GET /api/v1/settings/daily-report` | When the daily report goes out, as `{"time": "07:00"}`. `PUT` changes it; administrators only. |
| `GET /api/v1/adapters` | Every adapter with its fields and widgets. |
| `GET /go/{name}` | Opens the app tile with that short name, as a redirect: lower-case letters, digits and hyphens, taken from the tile's name unless the tile was given one (`alias` in its options, unique on its board). Only tiles on boards the caller may open count, a wall display's only on its own board; a tile that follows an app with an address for each network opens the same one the board shows. Signed out it goes to `/login?next=...` and back. A name that leads nowhere, or to two different addresses, opens the start board with the search bar holding the name (`/?find=...`). `GET /go?q=...` does the same for typed words; words that are exactly the name of a card open that card's board instead. |
| `GET /opensearch.xml` | The OpenSearch description (`application/opensearchdescription+xml`) every page links to with `<link rel="search">`: Chrome, Edge and Firefox can add nexdeck as a search engine under the installation's own name and logo. It searches with `/go?q={searchTerms}`. Safari reads no OpenSearch; a bookmark of `/go/{name}` does the same there. |
| `GET /api/v1/go/suggestions?q=...` | What the address bar offers while somebody types, as `application/x-suggestions+json`: `[words, [completions], [descriptions]]`, tiles by their short name first, then cards by their name, from boards the caller may open. Without a session the lists are empty; it never answers with an error. |
| `GET /api/v1/apps` | The app catalog: apps with their addresses (`label`, `url`), the labels for `home` and `away`, and how many `tiles` follow each. Every member may read it. |
| `POST /api/v1/apps` | Add an app. `PATCH /api/v1/apps/{id}` changes one, and every tile that follows it changes with it; `DELETE` turns its tiles into tiles of their own first. Administrators only. |
| `POST /api/v1/maintenance` | Put a connection (`integration_id`) or an app tile (`widget_id`) into maintenance, for `minutes` or until `ends_at`, a week at most. Again for the same one moves its end. Until then nothing about it is told except rejected credentials, no outage is opened, and the availability bars draw the time grey. `GET` lists the running and recent ones, `DELETE /api/v1/maintenance/{id}` ends one now. Administrators only. |
| `GET /api/v1/boards/{slug}/export` | The board as YAML. |
| `POST /api/v1/boards/import` | Create a board from YAML. |
| `POST /api/v1/auth/me/avatar` | Upload the own profile picture as `multipart/form-data` with the field `file`. |
| `DELETE /api/v1/auth/me/avatar` | Remove it again. |
| `GET /api/v1/settings/mail` | The installation's mail server; the password comes back masked. Administrators only. |
| `PUT /api/v1/settings/mail` | Change it. Sending the mask back keeps the stored password. |
| `POST /api/v1/settings/mail/test` | Send a test message, to the given address or to the administrator's own. |
| `GET /api/v1/settings/search` | The targets the bar may hand a typed word to. Every signed-in account may read them; the bar needs them on every page. |
| `PUT /api/v1/settings/search` | Change them. Administrators only. |
| `GET /api/v1/settings/search/suggestions` | Targets built out of the connected services. Administrators only. |
| `GET /api/v1/settings/appearance` | The look of the installation: colour theme, accent colour, style sheet, and how cards are drawn (`card_style` glass, flat, outline or neon, `radius` 0 to 28 and `gap` 4 to 28 pixels). Every signed-in account and every kiosk display may read it; every page is painted with it. |
| `PUT /api/v1/settings/appearance` | Change it. Administrators only. A field left out goes back to its default. |

Errors come as `{"detail": {"code": "...", "message": "..."}}` with an
English message; the interface translates known codes.

## Example: read a widget from a script

```bash
curl -H "Authorization: Bearer nd_your_token" https://deck.example.com/api/v1/widgets/12/data
```

## Example: follow the live stream

```bash
curl -N -H "Authorization: Bearer nd_your_token" "https://deck.example.com/api/v1/stream?board=home"
```
