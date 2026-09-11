"""wg-easy: which WireGuard clients are connected, and how much went through.

Measured against wg-easy 15.4.0 on 11.09.2026, with three clients (one
disabled) and a real WireGuard client in a second container that connected
with the configuration wg-easy handed out.

⚠️ Version 15 takes basic authentication on its API. The addresses of
version 14 are gone: ``/api/session`` and ``/api/wireguard/client`` both got
404, so a wg-easy 14 is not supported.

⚠️ Only the list ``/api/client`` carries ``latestHandshakeAt`` and the
transfer counters. ``/api/client/{id}`` has neither.

⚠️ A disabled client has ``null`` for its transfer, not 0. A client that
never connected has no handshake at all.

A WireGuard peer does not stay "connected"; it hands shakes. They are renewed
about every two minutes while traffic flows, so the card counts a client as
connected when its last handshake is at most three minutes old.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from .base import (
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
    ago,
    base_url,
    human_bytes,
)

#: WireGuard renews a handshake every two minutes while a tunnel carries traffic.
CONNECTED_SECONDS = 180


def _moment(raw: Any) -> float:
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp() if raw else 0.0
    except ValueError:
        return 0.0


class WgEasyAdapter(Adapter):
    kind = "wgeasy"
    label = "wg-easy"
    category = "network"
    description = "Which WireGuard clients are connected, and how much went through."
    icon = "wireguard"
    beta = False
    docs_url = "https://wg-easy.github.io/wg-easy/latest/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://wg-easy:51821"),
        Field("username", "User", required=True, default="admin"),
        Field("password", "Password", type="password", secret=True, required=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="clients", label="WireGuard clients", description="Every client, the connected ones first, with the traffic or when it was last seen.",
                   renderer="list", default_size=(3, 3), refresh_seconds=60, metrics=("connected",),
                   options=(Field("limit", "Entries", type="number", default=10),)),
        WidgetType(kind="summary", label="VPN", description="How many clients are connected, and the traffic of all of them.",
                   renderer="value", default_size=(3, 2), refresh_seconds=60, metrics=("connected",)),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 10) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api{path}", auth=(str(config.get("username") or ""), str(config.get("password") or "")),
            verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("wg-easy rejected the user or the password.")
        if response.status_code == 404:
            raise AdapterError("wg-easy has no such address.", code="http_error", hint="nexdeck speaks to wg-easy 15 and newer.")
        if response.status_code >= 400:
            raise AdapterError(f"wg-easy answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("wg-easy did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than wg-easy.") from error

    async def _clients(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        clients = await self._get(config, ctx, "/client")
        if not isinstance(clients, list):
            raise AdapterError("This address answers, but not the way wg-easy does.", code="not_wgeasy")
        return [one for one in clients if isinstance(one, dict)]

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        clients = await self._clients(config, ctx)
        info = await self._get(config, ctx, "/information", cache=0)
        version = str(info.get("currentRelease") or "?").lstrip("v") if isinstance(info, dict) else "?"
        return f"wg-easy {version} answers with {len(clients)} clients."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        rows = self._rows(await self._clients(config, ctx), time.time())
        if widget_kind == "summary":
            return self._summary(rows)
        return self._list(rows, options)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _rows(clients: list[dict[str, Any]], now: float) -> list[dict[str, Any]]:
        rows = []
        for client in clients:
            shaken = _moment(client.get("latestHandshakeAt"))
            expires = _moment(client.get("expiresAt"))
            traffic = int(client.get("transferRx") or 0) + int(client.get("transferTx") or 0)
            address = str(client.get("ipv4Address") or "")
            if not client.get("enabled"):
                state, rank, word, value = "unknown", 3, "Disabled", ""
            elif expires and expires < now:
                state, rank, word, value = "unknown", 3, "Expired", ""
            elif shaken and now - shaken <= CONNECTED_SECONDS:
                state, rank, word, value = "ok", 0, "Connected", human_bytes(traffic)
            elif shaken:
                state, rank, word, value = "unknown", 1, "Last seen", ago(shaken, now)
            else:
                state, rank, word, value = "unknown", 2, "Never connected", ""
            rows.append({"rank": rank, "traffic": traffic, "enabled": bool(client.get("enabled")), "row": {
                "title": str(client.get("name") or address or "?"),
                "subtitle": " · ".join(part for part in (word, address) if part),
                "status": state,
                "value": value,
            }})
        return rows

    @staticmethod
    def _list(rows: list[dict[str, Any]], options: dict[str, Any]) -> WidgetData:
        ranked = sorted(rows, key=lambda one: (one["rank"], one["row"]["title"].lower()))
        connected = sum(1 for one in rows if one["rank"] == 0)
        return WidgetData(
            status="ok",
            items=[one["row"] for one in ranked][: int(options.get("limit") or 10)],
            secondary=[{"label": "Connected", "value": connected}],
            meta={"empty": "No clients yet."},
            metrics={"connected": float(connected)},
        )

    @staticmethod
    def _summary(rows: list[dict[str, Any]]) -> WidgetData:
        connected = sum(1 for one in rows if one["rank"] == 0)
        enabled = sum(1 for one in rows if one["enabled"])
        disabled = len(rows) - enabled
        secondary: list[dict[str, Any]] = [{"label": "Traffic", "value": human_bytes(sum(one["traffic"] for one in rows))}]
        if disabled:
            secondary.append({"label": "Disabled", "value": disabled})
        return WidgetData(
            status="ok",
            primary={"label": "Connected", "value": connected, "unit": f"/ {enabled}"},
            secondary=secondary,
            metrics={"connected": float(connected)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = time.time()

        def stamp(seconds_ago: float) -> str:
            return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(now - seconds_ago))

        clients = [
            {"name": "phone", "enabled": True, "ipv4Address": "10.8.0.2", "latestHandshakeAt": stamp(40), "transferRx": 48_200_000 + tick * 9_000, "transferTx": 612_000_000},
            {"name": "laptop", "enabled": True, "ipv4Address": "10.8.0.3", "latestHandshakeAt": stamp(7_400), "transferRx": 3_100_000, "transferTx": 29_000_000},
            {"name": "tablet", "enabled": True, "ipv4Address": "10.8.0.4", "latestHandshakeAt": None, "transferRx": 0, "transferTx": 0},
            {"name": "old-phone", "enabled": False, "ipv4Address": "10.8.0.5", "latestHandshakeAt": None, "transferRx": None, "transferTx": None},
        ]
        rows = self._rows(clients, now)
        if widget_kind == "summary":
            return self._summary(rows)
        return self._list(rows, options)


ADAPTER = WgEasyAdapter()
