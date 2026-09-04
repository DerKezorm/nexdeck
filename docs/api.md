# API

nexdeck's own interface uses the same API that is open to you. The
interactive documentation lives at `/api/docs` on every installation.

## Authentication

- **Browser session:** a cookie, set by `POST /api/v1/auth/login`. Unsafe methods need the header `X-Nexdeck-Request: 1`, which a cross-site form cannot send.
- **API token:** `Authorization: Bearer nd_…`. Create one under Settings > API tokens. A token has the rights of its account.
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
| `GET /api/v1/adapters` | Every adapter with its fields and widgets. |
| `GET /api/v1/boards/{slug}/export` | The board as YAML. |
| `POST /api/v1/boards/import` | Create a board from YAML. |

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
