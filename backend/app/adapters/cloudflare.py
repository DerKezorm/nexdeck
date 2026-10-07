"""Cloudflare: the tunnels, the zones, and a zone's traffic over the last day.

Built from Cloudflare's API reference without an account to measure against,
so it stays beta until somebody has watched the cards fill. What it relies
on, as documented in October 2026:

- An API token as a bearer. A token made under My Profile is checked at
  ``/user/tokens/verify``, one made under the account (it starts with
  ``cfat_``) at ``/accounts/{id}/tokens/verify``; the test tries both.
- ``GET /accounts/{id}/cfd_tunnel`` lists the cloudflared tunnels with a
  ``status`` of ``healthy``, ``degraded``, ``down`` or ``inactive`` (never
  run). ⚠️ The ``connections`` that list used to carry were removed on
  05.10.2026; the connections of a tunnel come from
  ``/cfd_tunnel/{id}/connections`` now, one client per cloudflared with its
  ``conns``, each naming the data centre (``colo_name``).
- ``GET /zones`` with ``status`` (``active``, ``pending``, ``initializing``,
  ``moved``) and ``paused``.
- The traffic from the GraphQL Analytics API, ``httpRequestsAdaptiveGroups``,
  which since 02.10.2026 keeps 31 days on every plan. It has no threat count;
  the cached share is read from ``cacheStatus``. GraphQL answers a fault
  with HTTP 200 and ``errors``.

The REST API allows 1,200 requests in five minutes for a user, GraphQL 300.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
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
    ago,
    human_bytes,
)

API = "https://api.cloudflare.com/client/v4"

#: A tunnel's status, as a colour and a word.
TUNNEL = {"healthy": ("ok", "Healthy"), "degraded": ("warn", "Degraded"), "down": ("bad", "Down"), "inactive": ("unknown", "Never run")}

#: A zone's status, where it is not simply active.
ZONE = {"pending": ("warn", "Waiting for the name servers"), "initializing": ("unknown", "Being set up"), "moved": ("bad", "Moved away")}

#: Cache states in which Cloudflare answered from its cache rather than from the origin.
CACHED = {"hit", "stale", "revalidated", "updating"}

#: The tunnels whose connections are asked for, one request each.
CONNECTIONS_FOR = 10

TRAFFIC = """query ($zone: string, $since: Time, $until: Time) {
  viewer { zones(filter: {zoneTag: $zone}) {
    httpRequestsAdaptiveGroups(limit: 50, filter: {datetime_geq: $since, datetime_lt: $until, requestSource: "eyeball"}) {
      count
      sum { edgeResponseBytes visits }
      dimensions { cacheStatus }
    }
  } }
}"""


class CloudflareAdapter(Adapter):
    kind = "cloudflare"
    label = "Cloudflare"
    category = "network"
    description = "Whether your Cloudflare Tunnels are up, how your zones stand, and a zone's requests, data and cache over the last day."
    icon = "cloudflare"
    docs_url = "https://developers.cloudflare.com/api/"
    keywords = ("cloudflared", "Zero Trust", "tunnel", "DNS")
    fields = (
        Field("token", "API token", type="password", secret=True, required=True,
              help="A token with Account > Cloudflare Tunnel > Read for the tunnels, Zone > Zone > Read for the zones, and Account > Account Analytics > Read for the traffic. Reading is all it needs."),
        Field("account_id", "Account ID",
              help="Shown on the right of an account's overview in the dashboard. Needed for the tunnels and for a token made under the account."),
    )
    widgets = (
        WidgetType(
            kind="tunnels",
            label="Tunnels",
            description="Every Cloudflare Tunnel with its state, its connections and the data centres they reach, the ones that are down first.",
            renderer="list",
            default_size=(4, 3),
            min_size=(3, 2),
            refresh_seconds=120,
            metrics=("down",),
            options=(Field("limit", "Entries", type="number", default=10),),
        ),
        WidgetType(
            kind="zones",
            label="Zones",
            description="Your domains on Cloudflare: active, waiting for the name servers, or paused.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=1800,
            options=(Field("limit", "Entries", type="number", default=10),),
        ),
        WidgetType(
            kind="traffic",
            label="Traffic",
            description="A zone's requests, visits and data over the last 24 hours, and the share Cloudflare answered from its cache.",
            renderer="value",
            default_size=(3, 2),
            refresh_seconds=900,
            metrics=("requests",),
            options=(Field("zone", "Zone", required=True, placeholder="example.com", help="The domain as it stands in Cloudflare."),),
        ),
    )

    def default_link(self, config: dict[str, Any]) -> str:
        return "https://dash.cloudflare.com/"

    # -- asking Cloudflare -----------------------------------------------------

    @staticmethod
    def _headers(config: dict[str, Any]) -> dict[str, str]:
        token = str(config.get("token") or "").strip()
        if not token:
            raise AuthFailed("No API token is set.")
        return {"Authorization": f"Bearer {token}"}

    @staticmethod
    def _account(config: dict[str, Any]) -> str:
        account = str(config.get("account_id") or "").strip()
        if not account:
            raise AdapterError("No account ID is set.", code="missing_account",
                               hint="The tunnels belong to an account; its ID stands on the right of the account's overview in the dashboard.")
        return account

    async def _rest(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 30,
                    permission: str = "") -> Any:
        response = await ctx.request("GET", f"{API}{path}", headers=self._headers(config), params=params, timeout=20,
                                     cache_seconds=cache, auth_errors=False)
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code == 429:
            raise AdapterError("Cloudflare's rate limit is used up for five minutes.", code="rate_limited",
                               hint="1,200 requests in five minutes are shared by everything that uses this account's tokens.")
        if response.status_code in (401, 403) or (isinstance(payload, dict) and payload.get("success") is False and response.status_code >= 400):
            said = "; ".join(str(one.get("message")) for one in (payload.get("errors") or []) if isinstance(one, dict)) if isinstance(payload, dict) else ""
            if response.status_code == 401 or "Invalid" in said:
                failure = AuthFailed("Cloudflare rejected the token.")
                failure.hint = "Check that it is the token itself, not its ID, and that it has not expired."
                raise failure
            if response.status_code == 403:
                raise AdapterError("The token may not read this.", code="missing_permission",
                                   hint=f"Give the token {permission}." if permission else "Check the token's permissions.")
            raise AdapterError(f"Cloudflare refused the request: {said or response.status_code}.", code="http_error")
        if response.status_code >= 400:
            raise AdapterError(f"Cloudflare answered with HTTP {response.status_code}.", code="http_error")
        return payload.get("result") if isinstance(payload, dict) else None

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        account = str(config.get("account_id") or "").strip()
        checked = None
        try:
            checked = await self._rest(config, ctx, "/user/tokens/verify", cache=0)
        except AuthFailed:
            # A token made under the account is not a user's and is checked there.
            if not account:
                raise
            checked = await self._rest(config, ctx, f"/accounts/{account}/tokens/verify", cache=0)
        state = str((checked or {}).get("status") or "?")
        if state != "active":
            raise AuthFailed(f"Cloudflare knows the token, but it is {state}.")
        until = (checked or {}).get("expires_on")
        return "Cloudflare accepts the token" + (f"; it expires on {str(until)[:10]}." if until else ".")

    # -- the cards -------------------------------------------------------------

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        limit = max(1, min(30, int(options.get("limit") or 10)))
        if widget_kind == "zones":
            zones = await self._rest(config, ctx, "/zones", {"per_page": 50}, cache=300, permission="Zone > Zone > Read")
            return self.zone_rows(zones if isinstance(zones, list) else [], limit)
        if widget_kind == "traffic":
            return await self._traffic(config, ctx, str(options.get("zone") or "").strip().lower())
        account = self._account(config)
        tunnels = await self._rest(config, ctx, f"/accounts/{account}/cfd_tunnel", {"is_deleted": "false", "per_page": 100},
                                   permission="Account > Cloudflare Tunnel > Read")
        tunnels = [one for one in tunnels or [] if isinstance(one, dict)]
        tunnels.sort(key=lambda one: RANK.get(str(one.get("status") or ""), 9))
        clients: dict[str, list[dict[str, Any]]] = {}
        for tunnel in [one for one in tunnels if one.get("status") in ("healthy", "degraded")][:CONNECTIONS_FOR]:
            answer = await self._rest(config, ctx, f"/accounts/{account}/cfd_tunnel/{tunnel.get('id')}/connections", cache=60,
                                      permission="Account > Cloudflare Tunnel > Read")
            clients[str(tunnel.get("id"))] = [one for one in answer or [] if isinstance(one, dict)]
        return self.tunnel_rows(tunnels, clients, limit)

    async def _traffic(self, config: dict[str, Any], ctx: Context, name: str) -> WidgetData:
        if not name:
            raise AdapterError("No zone is set.", code="missing_zone")
        zones = await self._rest(config, ctx, "/zones", {"name": name}, cache=3600, permission="Zone > Zone > Read")
        zone = next((one for one in zones or [] if isinstance(one, dict) and str(one.get("name") or "").lower() == name), None)
        if zone is None:
            raise AdapterError(f"The token sees no zone called {name}.", code="unknown_zone",
                               hint="Write the domain as it stands in Cloudflare, and give the token Zone > Zone > Read for it.")
        until = datetime.now(UTC).replace(second=0, microsecond=0)
        since = until - timedelta(hours=24)
        stamp = lambda moment: moment.isoformat().replace("+00:00", "Z")  # noqa: E731
        response = await ctx.request("POST", f"{API}/graphql", headers=self._headers(config), timeout=30, auth_errors=False,
                                     json_body={"query": TRAFFIC, "variables": {"zone": zone.get("id"), "since": stamp(since), "until": stamp(until)}})
        if response.status_code == 401:
            raise AuthFailed("Cloudflare rejected the token.")
        if response.status_code == 429:
            raise AdapterError("Cloudflare's analytics limit is used up for five minutes.", code="rate_limited")
        try:
            payload = response.json()
        except ValueError as error:
            raise AdapterError(f"Cloudflare's analytics answered with HTTP {response.status_code}.", code="http_error") from error
        errors = [str(one.get("message") or "") for one in (payload.get("errors") or []) if isinstance(one, dict)] if isinstance(payload, dict) else []
        if errors or response.status_code >= 400:
            if any("authoriz" in one.lower() for one in errors) or response.status_code == 403:
                raise AdapterError("The token may not read this zone's analytics.", code="missing_permission",
                                   hint="Give the token Account > Account Analytics > Read.")
            raise AdapterError(f"Cloudflare's analytics refused the query: {errors[0] if errors else response.status_code}.", code="query_error")
        found = (((payload.get("data") or {}).get("viewer") or {}).get("zones") or [{}])
        return self.traffic(((found[0] if found else {}) or {}).get("httpRequestsAdaptiveGroups") or [])

    @staticmethod
    def tunnel_rows(tunnels: list[dict[str, Any]], clients: dict[str, list[dict[str, Any]]], limit: int) -> WidgetData:
        rows = []
        for tunnel in tunnels:
            state = str(tunnel.get("status") or "")
            colour, word = TUNNEL.get(state, ("unknown", state.capitalize() or "?"))
            conns = [conn for client in clients.get(str(tunnel.get("id")), []) for conn in client.get("conns") or [] if isinstance(conn, dict)]
            colos = sorted({str(conn.get("colo_name") or "") for conn in conns} - {""})
            parts = [word]
            if conns:
                parts.append(f"{len(conns)} connection(s)")
            if colos:
                parts.append(", ".join(colos[:4]))
            since = tunnel.get("conns_inactive_at") if state == "down" else tunnel.get("conns_active_at")
            rows.append({
                "title": str(tunnel.get("name") or tunnel.get("id") or "?"),
                "subtitle": " · ".join(parts),
                "status": colour,
                "value": ago(since) if state in ("healthy", "degraded", "down") else "",
            })
        down = sum(1 for one in tunnels if one.get("status") == "down")
        degraded = sum(1 for one in tunnels if one.get("status") == "degraded")
        healthy = sum(1 for one in tunnels if one.get("status") == "healthy")
        return WidgetData(
            status="bad" if down else "warn" if degraded else "ok",
            items=rows[:limit],
            secondary=[{"label": "Healthy", "value": healthy}, {"label": "Down", "value": down}],
            meta={"empty": "No tunnel in this account."},
            metrics={"down": float(down)},
        )

    @staticmethod
    def zone_rows(zones: list[dict[str, Any]], limit: int) -> WidgetData:
        rows = []
        for zone in zones:
            if not isinstance(zone, dict):
                continue
            colour, word = ZONE.get(str(zone.get("status") or ""), ("ok", ""))
            if zone.get("paused") and colour == "ok":
                # Paused: Cloudflare answers DNS but passes the traffic through, unprotected.
                colour, word = "warn", "Paused"
            rows.append({
                "title": str(zone.get("name") or "?"),
                "subtitle": " · ".join(part for part in (word, "Partial setup" if zone.get("type") == "partial" else "") if part),
                "status": colour,
                "value": ago(zone.get("activated_on")) if zone.get("status") == "active" else "",
            })
        rows.sort(key=lambda row: (row["status"] == "ok", row["title"]))
        waiting = sum(1 for row in rows if row["status"] != "ok")
        return WidgetData(
            status="warn" if waiting else "ok",
            items=rows[:limit],
            secondary=[{"label": "Zones", "value": len(rows)}, {"label": "Need attention", "value": waiting}],
            meta={"empty": "The token sees no zone."},
        )

    @staticmethod
    def traffic(groups: list[dict[str, Any]]) -> WidgetData:
        requests = sum(int(one.get("count") or 0) for one in groups if isinstance(one, dict))
        cached = sum(int(one.get("count") or 0) for one in groups
                     if isinstance(one, dict) and str((one.get("dimensions") or {}).get("cacheStatus") or "") in CACHED)
        data = sum(int((one.get("sum") or {}).get("edgeResponseBytes") or 0) for one in groups if isinstance(one, dict))
        visits = sum(int((one.get("sum") or {}).get("visits") or 0) for one in groups if isinstance(one, dict))
        return WidgetData(
            status="ok",
            primary={"label": "Requests", "value": requests, "metric": "requests"},
            secondary=[
                {"label": "Visits", "value": visits},
                {"label": "Data", "value": human_bytes(data)},
                {"label": "Cached", "value": round(cached * 100 / requests) if requests else 0, "unit": "%"},
            ],
            metrics={"requests": float(requests)},
        )

    # -- demo ------------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = time.time()
        stamp = lambda seconds: datetime.fromtimestamp(now - seconds, UTC).isoformat().replace("+00:00", "Z")  # noqa: E731
        if widget_kind == "zones":
            return self.zone_rows([
                {"name": "example.com", "status": "active", "activated_on": stamp(86400 * 400)},
                {"name": "example.net", "status": "active", "paused": (tick // 600) % 3 == 0, "activated_on": stamp(86400 * 90)},
                {"name": "example.org", "status": "pending"},
            ], int(options.get("limit") or 10))
        if widget_kind == "traffic":
            total = int(fake.walk("cf-requests", tick, 38_000, 52_000))
            return self.traffic([
                {"count": int(total * 0.62), "sum": {"edgeResponseBytes": 2_900_000_000, "visits": 2100}, "dimensions": {"cacheStatus": "hit"}},
                {"count": int(total * 0.38), "sum": {"edgeResponseBytes": 900_000_000, "visits": 1300}, "dimensions": {"cacheStatus": "dynamic"}},
            ])
        down = (tick // 240) % 4 == 0
        tunnels = [
            {"id": "t1", "name": "home", "status": "healthy", "conns_active_at": stamp(86400 * 6)},
            {"id": "t2", "name": "office", "status": "down" if down else "healthy", "conns_active_at": stamp(86400 * 2),
             "conns_inactive_at": stamp(900)},
            {"id": "t3", "name": "test", "status": "inactive"},
        ]
        clients = {
            "t1": [{"conns": [{"colo_name": "fra06"}, {"colo_name": "fra08"}, {"colo_name": "ams01"}, {"colo_name": "fra06"}]}],
            "t2": [] if down else [{"conns": [{"colo_name": "dus01"}, {"colo_name": "fra10"}]}],
        }
        tunnels.sort(key=lambda one: RANK.get(str(one.get("status") or ""), 9))
        return self.tunnel_rows(tunnels, clients, int(options.get("limit") or 10))


#: Down first, then degraded, then the healthy ones, and the ones never run last.
RANK = {"down": 0, "degraded": 1, "healthy": 2, "inactive": 3}

ADAPTER = CloudflareAdapter()
