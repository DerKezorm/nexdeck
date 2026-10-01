"""Qui: the web interface for one or many qBittorrent, by the autobrr team.

Measured on 01.10.2026 against ghcr.io/autobrr/qui 1.30.0 with one
linuxserver qBittorrent 5.2.3 behind it, one torrent added stopped, with a
right, a wrong and no API key.

One key, made under Settings > API keys, reads everything, sent as the
header ``X-API-Key``. Without a key Qui answers 403, with a wrong one 401.

⚠️ There is no summary of all instances. ``/api/instances`` lists them, and
each one's torrent list, asked for a single row, carries what a card needs:
``stats`` with the totals, ``counts.status`` with how many are active,
seeding, errored and so on, and ``serverState`` with qBittorrent's own
transfer rates in bytes per second. That is one request per instance.

⚠️ ``serverState`` also carries ``last_external_address_v4``, the public
address of the line. It is never read here and never shown.

⚠️ ``connected`` on an instance stayed false while its torrents were served:
Qui had failed one sign-in earlier and kept the error in ``recentErrors``.
The card goes by whether the torrent list answered, and shows the last error
only when it did not.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    human_bytes,
)


def _speed(value: Any) -> str:
    return f"{human_bytes(float(value or 0))}/s"


class QuiAdapter(Adapter):
    kind = "qui"
    label = "Qui"
    category = "downloads"
    description = "One or many qBittorrent through Qui: speeds, torrents that run, seed or fail, and each instance."
    icon = "qui"
    beta = True
    docs_url = "https://getqui.com/docs/api/overview"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://qui:7476"),
        Field("api_key", "API key", type="password", secret=True, required=True, help="Settings > API keys"),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="overview",
            label="Qui overview",
            description="Download and upload across every instance, and how many torrents run, seed or fail.",
            renderer="stats",
            default_size=(3, 2),
            refresh_seconds=10,
            metrics=("download", "upload"),
        ),
        WidgetType(
            kind="instances",
            label="Instances",
            description="One row per qBittorrent: whether it answers, its speeds and its torrents.",
            renderer="list",
            default_size=(4, 2),
            refresh_seconds=15,
        ),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}{path}", params=params, cache_seconds=5,
            headers={"X-API-Key": str(config.get("api_key") or ""), "Accept": "application/json"},
            verify=not config.get("insecure"),
        )
        # A wrong key (401) and none at all (403) are turned into a refusal by
        # ``ctx.request`` already, before this line is reached.
        if response.status_code >= 400:
            raise AdapterError(f"Qui answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError:
            raise AdapterError("Qui did not answer with JSON; is this the address of Qui?", code="bad_answer") from None

    async def _instances(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        """Every active instance with the totals of its torrent list, or the reason it has none."""
        listed = await self._get(config, ctx, "/api/instances")
        rows: list[dict[str, Any]] = []
        for instance in listed if isinstance(listed, list) else []:
            if not isinstance(instance, dict) or instance.get("isActive") is False:
                continue
            row: dict[str, Any] = {"id": instance.get("id"), "name": str(instance.get("name") or "qBittorrent")}
            try:
                torrents = await self._get(config, ctx, f"/api/instances/{instance.get('id')}/torrents", {"limit": 1})
                row.update(stats=torrents.get("stats") or {}, status=(torrents.get("counts") or {}).get("status") or {},
                           state=torrents.get("serverState") or {}, answered=True)
            except AuthFailed:
                raise
            except AdapterError as failure:
                errors = instance.get("recentErrors") or []
                said = str(errors[0].get("errorMessage")) if errors and isinstance(errors[0], dict) else failure.message
                row.update(answered=False, error=said)
            rows.append(row)
        return rows

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        rows = await self._instances(config, ctx)
        answering = sum(1 for row in rows if row["answered"])
        return f"Qui answers with {len(rows)} instance(s), {answering} of them reachable."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        return shape(widget_kind, await self._instances(config, ctx))

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        down = fake.walk("qui-down", tick, 0, 48_000_000, period=180)
        up = fake.walk("qui-up", tick, 200_000, 6_000_000, period=240)
        rows = [
            {"id": 1, "name": "Seedbox", "answered": True,
             "stats": {"total": 412}, "status": {"active": 6, "seeding": 398, "errored": 0, "downloading": 2},
             "state": {"dl_info_speed": down * 0.8, "up_info_speed": up * 0.9}},
            {"id": 2, "name": "Home", "answered": True,
             "stats": {"total": 96}, "status": {"active": 2, "seeding": 91, "errored": 1 if fake.flicker("qui-err", tick, 0.2) else 0, "downloading": 1},
             "state": {"dl_info_speed": down * 0.2, "up_info_speed": up * 0.1}},
        ]
        return shape(widget_kind, rows)


def shape(widget_kind: str, rows: list[dict[str, Any]]) -> WidgetData:
    """The cards from the instances as read: the overview adds them up, the list shows each."""
    down = sum(float(row.get("state", {}).get("dl_info_speed") or 0) for row in rows if row.get("answered"))
    up = sum(float(row.get("state", {}).get("up_info_speed") or 0) for row in rows if row.get("answered"))
    count = lambda key: sum(int(row.get("status", {}).get(key) or 0) for row in rows if row.get("answered"))  # noqa: E731
    total = sum(int(row.get("stats", {}).get("total") or 0) for row in rows if row.get("answered"))
    unreachable = [row for row in rows if not row.get("answered")]
    errored = count("errored")
    status = "bad" if rows and len(unreachable) == len(rows) else "warn" if unreachable or errored else "ok"
    if widget_kind == "instances":
        items = []
        for row in rows:
            if row.get("answered"):
                state = row.get("state", {})
                bad = int(row.get("status", {}).get("errored") or 0)
                items.append({
                    "id": row.get("id"), "title": row["name"],
                    "subtitle": f"↓ {_speed(state.get('dl_info_speed'))} · ↑ {_speed(state.get('up_info_speed'))}",
                    "value": f"{int(row.get('stats', {}).get('total') or 0)}",
                    "status": "warn" if bad else "ok",
                })
            else:
                items.append({"id": row.get("id"), "title": row["name"], "subtitle": str(row.get("error") or "Not reachable"), "status": "bad"})
        return WidgetData(status=status, items=items, meta={"empty": "Qui has no instance yet."},
                          secondary=[{"label": "Instances", "value": len(rows)}, {"label": "Unreachable", "value": len(unreachable)}])
    return WidgetData(
        status=status,
        primary={"label": "Download", "value": _speed(down), "metric": "download"},
        secondary=[
            {"label": "Upload", "value": _speed(up), "metric": "upload"},
            {"label": "Torrents", "value": total},
            {"label": "Active", "value": count("active")},
            {"label": "Seeding", "value": count("seeding")},
            {"label": "Errored", "value": errored},
        ],
        metrics={"download": round(down, 1), "upload": round(up, 1)},
    )


ADAPTER = QuiAdapter()
