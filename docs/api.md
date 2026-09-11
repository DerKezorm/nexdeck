# API

nexdeck's own interface uses the same API that is open to you. The
interactive documentation lives at `/api/docs` on every installation.

## Authentication

- **Browser session:** a cookie, set by `POST /api/v1/auth/login`. Unsafe methods need the header `X-Nexdeck-Request: 1`, which a cross-site form cannot send.
- **API token:** `Authorization: Bearer nd_…`. Create one under My settings > API tokens. A token has the rights of its account.
- **Kiosk token:** `X-Kiosk-Token: nk_…` or `?kiosk=nk_…`. Reads one board, nothing else.

## Useful addresses

| Address | Purpose |
|---|---|
| `GET /api/v1/boards` | Boards the caller may open. |
| `GET /api/v1/boards/{slug}` | A board with pages, widgets and the latest live data. |
| `GET /api/v1/boards/{slug}/history` | Metric history of every widget for sparklines. |
| `GET /api/v1/stream?board={slug}` | Server-Sent Events: `widget`, `health`, `board`, `layout`, `log`, `notice`. |
| `POST /api/v1/widgets/{id}/actions/{action}` | Run a widget action with `{"params": {...}}`. Needs the act permission. |
| `GET /api/v1/widgets/{id}/data` | The latest data of one widget. |
| `POST /api/v1/widgets/{id}/refresh` | Fetch right now. |
| `GET /api/v1/widgets/{id}/music/{view}` | The library of a music player card: `albums`, `artists`, `artist`, `album`, `playlists`, `playlist`, `search`, `shuffle`, and `mix` on Jellyfin and Emby. `id`, `q`, `sort` and `offset` narrow it down. Needs the act permission. |
| `GET /api/v1/widgets/{id}/audio/{track_id}` | The sound of one track, relayed by nexdeck with `Range` passed through. `quality` is `original`, `high` or `low`, `formats` lists what the browser plays, `start` is where converted sound begins. Needs the act permission. |
| `POST /api/v1/widgets/{id}/music/playlists` | Create a playlist on the media server with `{"name": "...", "track_ids": [...]}`. `POST` and `DELETE` on `.../playlists/{playlist_id}/tracks` add tracks (`track_ids`) and take entries out (`entries`); `PATCH` and `DELETE` on `.../playlists/{playlist_id}` rename and delete. Smart playlists on Plex are refused. Needs the act permission. |
| `GET /api/v1/adapters` | Every adapter with its fields and widgets. |
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
| `GET /api/v1/settings/appearance` | The accent colour and the style sheet of the installation. Every signed-in account may read them; every page is painted with them. |
| `PUT /api/v1/settings/appearance` | Change them. Administrators only. |

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
