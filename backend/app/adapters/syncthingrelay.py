"""Syncthing Relay (strelaysrv): sessions, connections, throughput and traffic of a relay you run for the Syncthing network.

Measured against strelaysrv v2.1.7 on 27.10.2026, an idle relay started with
``-status-srv=":22070" -pools=""``.

⚠️ The status address is its own port, 22070 by default, and only exists when
the relay was started with ``-status-srv``. The relay's own port (22067) speaks
the relay protocol and answers nothing to a browser. ``GET /status`` is JSON
without a sign-in: ``numActiveSessions``, ``numConnections``,
``numPendingSessionKeys``, ``numProxies``, ``bytesProxied``, ``uptimeSeconds``,
``version`` and ``options`` (``provided-by``, ``pools``, the rate limits, 0 for
none). ``kbps10s1m5m15m30m60m`` is six kilobits per second, averaged over the
last 10 seconds, 1, 5, 15, 30 and 60 minutes.

⚠️ Idle: all of those are 0 on a relay nobody has used, which is also what a
relay that no pool has listed looks like. The shape of one in use is from the
field names and the Syncthing documentation only.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    duration_short,
    human_bytes,
)


def _rate(kbps: float | None) -> str:
    if kbps is None:
        return "?"
    return f"{kbps / 1000:.1f} Mbit/s" if kbps >= 1000 else f"{kbps:.0f} kbit/s"


class SyncthingRelayAdapter(Adapter):
    kind = "syncthingrelay"
    label = "Syncthing Relay"
    category = "network"
    description = "Sessions, connections, throughput and traffic of a Syncthing relay server (strelaysrv)."
    icon = "syncthing"
    #: Measured on 2026-10-27 against strelaysrv 2.1.7, idle: nobody used the relay.
    beta = True
    docs_url = "https://docs.syncthing.net/users/strelaysrv.html"
    keywords = ("strelaysrv", "relaysrv", "relay")
    fields = (
        Field("url", "Status URL", type="url", required=True, placeholder="http://relay:22070",
              help="The status address of the relay, started with -status-srv; not the relay port 22067."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="relay", label="Relay", description="Active sessions, connections and the throughput of the last minute, with the traffic proxied so far.",
                   renderer="value", default_size=(3, 2), refresh_seconds=30, metrics=("sessions", "throughput")),
    )

    async def _status(self, config: dict[str, Any], ctx: Context) -> dict[str, Any]:
        response = await ctx.request("GET", f"{base_url(config)}/status", verify=not config.get("insecure"), cache_seconds=10, auth_errors=False)
        if response.status_code >= 400:
            raise AdapterError(f"The relay answered with HTTP {response.status_code}.", code="http_error",
                               hint="This is the status address (strelaysrv -status-srv, port 22070 by default), not the relay port 22067.")
        try:
            status = response.json()
        except ValueError as error:
            raise AdapterError("The relay did not answer with JSON.", code="not_json", hint="The URL is the status address, not the relay port 22067.") from error
        if not isinstance(status, dict) or "numActiveSessions" not in status:
            raise AdapterError("This address answers, but not the way strelaysrv does.", code="not_a_relay")
        return status

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        status = await self._status(config, ctx)
        version = str(status.get("version") or "").lstrip("v")
        return f"Syncthing Relay {version} answers." if version else "Syncthing Relay answers."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        return self._card(await self._status(config, ctx))

    @staticmethod
    def _card(status: dict[str, Any]) -> WidgetData:
        sessions, connections = int(status.get("numActiveSessions") or 0), int(status.get("numConnections") or 0)
        rates = status.get("kbps10s1m5m15m30m60m")
        minute = float(rates[1]) if isinstance(rates, list) and len(rates) > 1 and rates[1] is not None else None
        secondary = [{"label": "Connections", "value": connections}, {"label": "Throughput", "value": _rate(minute)},
                     {"label": "Proxied", "value": human_bytes(status.get("bytesProxied"))},
                     {"label": "Uptime", "value": duration_short(status.get("uptimeSeconds"))}]
        pools = [one for one in (status.get("options") or {}).get("pools") or [] if one]
        if not pools:
            secondary.append({"label": "Pool", "value": "None"})
        metrics = {"sessions": float(sessions), **({"throughput": minute} if minute is not None else {})}
        return WidgetData(primary={"label": "Sessions", "value": sessions, "unit": ""}, secondary=secondary, metrics=metrics)

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        return self._card({"numActiveSessions": int(fake.walk("relay-sessions", tick, 2, 18)), "numConnections": int(fake.walk("relay-conn", tick, 4, 40)),
                           "kbps10s1m5m15m30m60m": [fake.walk("relay-kbps", tick, 300, 4200), fake.walk("relay-kbps1", tick, 300, 3000), 900, 800, 700, 600],
                           "bytesProxied": fake.counter("relay-bytes", tick, 48_000_000_000, 90_000), "uptimeSeconds": 12 * 86400 + tick,
                           "options": {"pools": ["https://relays.syncthing.net/endpoint"]}})


ADAPTER = SyncthingRelayAdapter()
