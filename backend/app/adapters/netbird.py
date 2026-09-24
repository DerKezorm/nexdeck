"""NetBird: the peers of a WireGuard network whose control server may be yours.

Self-hosted or NetBird Cloud, the management API is the same: ``/api`` under
the address the dashboard runs on, or ``https://api.netbird.io`` for the
cloud. It takes a personal access token as ``Authorization: Token <PAT>``.

Measured against a live netbird-server 0.79.0 with two clients (24.09.2026):
``connected`` is whether the peer holds its line to the management server
open, which is what the dashboard shows as online. ``last_seen`` is set when
a peer connects and when it goes, not while it stays, so for a connected
peer it says nothing and the card says "now". A service user with the plain
User role reads every peer, also with "regular users view blocked" on,
which is how a fresh installation starts. Without a token and with a wrong
one the answer is 401 with ``{"message": ..., "code": 401}``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from . import demo as fake
from .base import Adapter, Context, Field, WidgetData, WidgetType, base_url

CLOUD = "https://api.netbird.io"


class NetbirdAdapter(Adapter):
    kind = "netbird"
    label = "NetBird"
    category = "network"
    description = "Peers of a NetBird network, which are connected and which need to sign in again."
    icon = "netbird"
    docs_url = "https://docs.netbird.io/api"
    #: Both cards seen against a live netbird-server 0.79.0 with two clients (24.09.2026).
    beta = False
    fields = (
        Field("url", "URL", type="url", default=CLOUD, placeholder="https://netbird.example.com", help="The address of your NetBird dashboard, or https://api.netbird.io for NetBird Cloud."),
        Field("token", "Access token", type="password", secret=True, required=True, help="Team > Service users > a user > Access tokens. A service user with the User role reads every peer and can change nothing."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="peers",
            label="Peers",
            description="One line per peer with its address and system, and when it was last seen.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=120,
            metrics=("peers", "connected"),
            options=(Field("limit", "Entries", type="number", default=10), Field("only_offline", "Only away", type="bool", default=False)),
        ),
        WidgetType(
            kind="status",
            label="Status",
            description="How many peers there are, how many are connected, and whose login has expired.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=300,
            metrics=("peers", "connected"),
        ),
    )

    def default_link(self, config: dict[str, Any]) -> str:
        address = self._root(config)
        return "https://app.netbird.io" if address == CLOUD else address

    @staticmethod
    def _root(config: dict[str, Any]) -> str:
        """The address without ``/api``, which people paste along with it; with it, the answer was a bare 404."""
        address = base_url(config) or CLOUD
        return address[: -len("/api")] if address.endswith("/api") else address

    async def _peers(self, config: dict[str, Any], ctx: Context, cache: float = 60) -> list[dict[str, Any]]:
        payload = await ctx.get_json(
            f"{self._root(config)}/api/peers",
            headers={"Authorization": f"Token {config.get('token') or ''}", "Accept": "application/json"},
            verify=not config.get("insecure"),
            cache_seconds=cache,
        )
        return [peer for peer in payload if isinstance(peer, dict)] if isinstance(payload, list) else []

    @staticmethod
    def _ago(raw: str) -> str:
        if not raw:
            return "?"
        try:
            moment = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return str(raw)
        seconds = max(0.0, (datetime.now(UTC) - moment).total_seconds())
        if seconds < 3600:
            return f"{int(seconds // 60)} min"
        if seconds < 86400:
            return f"{int(seconds // 3600)} h"
        return f"{int(seconds // 86400)} d"

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        peers = await self._peers(config, ctx, cache=0)
        connected = sum(1 for peer in peers if peer.get("connected"))
        return f"NetBird answers with {len(peers)} peers, {connected} connected."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        return self._shape(widget_kind, await self._peers(config, ctx), options)

    def _shape(self, widget_kind: str, peers: list[dict[str, Any]], options: dict[str, Any]) -> WidgetData:
        connected = sum(1 for peer in peers if peer.get("connected"))
        expired = sum(1 for peer in peers if peer.get("login_expired"))
        metrics = {"peers": float(len(peers)), "connected": float(connected)}

        if widget_kind == "status":
            return WidgetData(
                status="warn" if expired else "ok",
                primary={"label": "Peers", "value": len(peers)},
                secondary=[
                    {"label": "Connected", "value": connected},
                    {"label": "Away", "value": len(peers) - connected},
                    {"label": "Login expired", "value": expired},
                ],
                metrics=metrics,
            )

        rows = []
        for peer in peers:
            online = bool(peer.get("connected"))
            if options.get("only_offline") and online:
                continue
            # ⚠️ An expired login is not the same as away: the peer is cut off
            # until somebody signs it in again, and nothing on its side says so.
            if peer.get("login_expired"):
                value, status = "Login expired", "warn"
            else:
                value, status = ("now", "ok") if online else (self._ago(str(peer.get("last_seen") or "")), "unknown")
            rows.append({
                "title": peer.get("name") or peer.get("hostname") or "?",
                "subtitle": " · ".join(part for part in (str(peer.get("ip") or ""), str(peer.get("os") or "")) if part),
                "value": value,
                "status": status,
            })
        order = {"warn": 0, "ok": 1, "unknown": 2}
        rows.sort(key=lambda row: (order[row["status"]], str(row["title"]).lower()))
        return WidgetData(
            items=rows[: int(options.get("limit") or 10)],
            secondary=[{"label": "Connected", "value": connected}, {"label": "Peers", "value": len(peers)}],
            metrics=metrics,
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = datetime.now(UTC)

        def seen(hours: float) -> str:
            return datetime.fromtimestamp(now.timestamp() - hours * 3600, UTC).isoformat()

        peers = [
            {"name": "nas", "ip": "100.92.0.3", "os": "Linux 6.12", "connected": True, "last_seen": seen(0)},
            {"name": "gateway", "ip": "100.92.0.1", "os": "Linux 6.12", "connected": True, "last_seen": seen(0)},
            {"name": "laptop", "ip": "100.92.0.9", "os": "Darwin 15.6", "connected": not fake.flicker("netbird-laptop", tick, 0.3), "last_seen": seen(3)},
            {"name": "phone", "ip": "100.92.0.7", "os": "iOS 19.2", "connected": False, "last_seen": seen(26)},
            {"name": "old-desktop", "ip": "100.92.0.12", "os": "Windows 11", "connected": False, "last_seen": seen(240), "login_expired": True},
        ]
        return self._shape(widget_kind, peers, options)


ADAPTER = NetbirdAdapter()
