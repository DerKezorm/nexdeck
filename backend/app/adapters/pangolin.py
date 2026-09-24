"""Pangolin: the sites a reverse proxy tunnels to, and what it serves from them.

Read through Pangolin's Integration API, which a self-hosted Pangolin only
runs with ``flags.enable_integration_api: true`` in its config.yml, on its own
port (3003) with the prefix ``/v1``. The default install does not route it
through Traefik; that is one router the operator adds. Pangolin Cloud serves
it at ``https://api.pangolin.net/v1``.

The key is ``<id>.<secret>`` as a bearer token, scoped to one organisation,
and it carries each permission on its own: listing sites, resources and
private resources are three separate ones. A key without one of them is told
403 "Key does not have permission perform this action", and that sentence is
passed on as it is, with the permission that was missing.

Written against Pangolin 1.23 from its source (September 2026): every answer
comes as ``{data, success, error, message, status}``, lists are paged, and a
public resource lists its sites (older versions named one site on the
resource itself; both are read). A local site has no ``online`` at all.
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
)

CLOUD = "https://api.pangolin.net"
#: As many as one page may hold; Pangolin sets no upper bound, the pages stop at the total.
PAGE_SIZE = 200
MAX_PAGES = 20

#: The permission each list needs, as Pangolin's key dialog names it.
PERMISSION = {"sites": "List Sites", "resources": "List Resources", "site-resources": "List Site Resources"}


class PangolinAdapter(Adapter):
    kind = "pangolin"
    label = "Pangolin"
    category = "network"
    description = "Sites of a Pangolin reverse proxy, whether they are online, and the resources it serves with their health."
    icon = "pangolin"
    docs_url = "https://docs.pangolin.net/manage/integration-api"
    fields = (
        Field("url", "Integration API URL", type="url", default=CLOUD, placeholder="https://api.pangolin.example.com", help="Where Pangolin's Integration API answers, without /v1. Self-hosted it needs enable_integration_api in config.yml and a route to port 3003."),
        Field("api_key", "API key", type="password", secret=True, required=True, help="Organization > API keys. Grant List Sites, List Resources and List Site Resources; nothing else is read."),
        Field("org_id", "Organization ID", required=True, placeholder="home", help="The ID in the address of the organization, not its name."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="status",
            label="Status",
            description="Sites online and offline, public and private resources, and how many are unhealthy.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=120,
            metrics=("sites", "online"),
        ),
        WidgetType(
            kind="sites",
            label="Sites",
            description="One line per site with its type and address, and whether it is online.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=60,
            metrics=("sites", "online"),
            options=(Field("limit", "Entries", type="number", default=10), Field("only_offline", "Only offline", type="bool", default=False)),
        ),
        WidgetType(
            kind="resources",
            label="Resources",
            description="Public resources with their address and health, private ones with their destination.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=120,
            options=(
                Field("show", "Show", type="select", default="public", options=(("public", "Public resources"), ("private", "Private resources"), ("both", "Both"))),
                Field("limit", "Entries", type="number", default=10),
                Field("only_problems", "Only problems", type="bool", default=False),
            ),
        ),
    )

    def default_link(self, config: dict[str, Any]) -> str:
        return "https://app.pangolin.net" if self._root(config) == CLOUD else ""

    @staticmethod
    def _root(config: dict[str, Any]) -> str:
        """The API's address without ``/v1``, which people paste along with it."""
        address = base_url(config) or CLOUD
        return address[: -len("/v1")] if address.endswith("/v1") else address

    async def _list(self, config: dict[str, Any], ctx: Context, what: str, cache: float = 60) -> list[dict[str, Any]]:
        org = str(config.get("org_id") or "").strip()
        if not org:
            raise AdapterError("The organization ID is missing.", code="missing_fields", hint="It is the ID in the address of the organization.")
        key = {"sites": "sites", "resources": "resources", "site-resources": "siteResources"}[what]
        rows: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            response = await ctx.request(
                "GET",
                f"{self._root(config)}/v1/org/{org}/{what}",
                headers={"Authorization": f"Bearer {config.get('api_key') or ''}", "Accept": "application/json"},
                params={"pageSize": PAGE_SIZE, "page": page},
                verify=not config.get("insecure"),
                cache_seconds=cache,
                auth_errors=False,
            )
            body = self._body(response, what, org)
            data = body.get("data") or {}
            found = [row for row in data.get(key) or [] if isinstance(row, dict)]
            rows += found
            total = int((data.get("pagination") or {}).get("total") or 0)
            if not found or len(rows) >= total:
                break
        return rows

    @staticmethod
    def _body(response: Any, what: str, org: str) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError:
            body = None
        said = str(body.get("message") or "") if isinstance(body, dict) else ""
        if response.status_code == 401:
            raise AuthFailed(f"Pangolin did not accept the API key: {said or 'HTTP 401'}.")
        if response.status_code == 403:
            if "organization" in said:
                raise AdapterError(f"The key does not belong to the organization {org}.", code="auth_failed", hint="Check the organization ID, or make the key in that organization.")
            raise AdapterError(
                f"The key lacks the permission {PERMISSION[what]}. Pangolin said: {said or 'HTTP 403'}.",
                code="auth_failed",
                hint="Edit the key under Organization > API keys and grant List Sites, List Resources and List Site Resources.",
            )
        if response.status_code == 404:
            raise AdapterError(
                "There is no Integration API at this address.",
                code="http_error",
                hint="Self-hosted, it needs enable_integration_api in config.yml and a route to port 3003.",
            )
        if response.status_code >= 400:
            raise AdapterError(f"Pangolin answered with HTTP {response.status_code}{': ' + said if said else ''}.", code="http_error")
        if not isinstance(body, dict) or "data" not in body:
            raise AdapterError("The address did not answer like Pangolin's Integration API.", code="not_json", hint="The URL probably points at the dashboard rather than the Integration API.")
        return body

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        sites = await self._list(config, ctx, "sites", cache=0)
        # The two other lists as well: each needs its own permission, and a
        # key missing one should fail here, not on the card later.
        resources = await self._list(config, ctx, "resources", cache=0)
        private = await self._list(config, ctx, "site-resources", cache=0)
        return f"Pangolin answers with {len(sites)} sites, {len(resources)} public and {len(private)} private resources."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "sites":
            return self._sites(await self._list(config, ctx, "sites"), options)
        if widget_kind == "resources":
            show = str(options.get("show") or "public")
            public = await self._list(config, ctx, "resources") if show in ("public", "both") else []
            private = await self._list(config, ctx, "site-resources") if show in ("private", "both") else []
            return self._resources(public, private, options)
        return self._status(
            await self._list(config, ctx, "sites"),
            await self._list(config, ctx, "resources"),
            await self._list(config, ctx, "site-resources"),
        )

    # -- shaping ---------------------------------------------------------------

    @staticmethod
    def _site_state(site: dict[str, Any]) -> tuple[str, str]:
        """What a site's line says, and its colour."""
        if site.get("status") == "pending":
            return "Pending", "warn"
        if site.get("type") == "local" or site.get("online") is None:
            # A local site is Pangolin's own host; there is nothing to be online.
            return "Local", "ok"
        return ("Online", "ok") if site.get("online") else ("Offline", "bad")

    @staticmethod
    def _health(resource: dict[str, Any]) -> tuple[str, str]:
        if not resource.get("enabled", True):
            return "Disabled", "unknown"
        health = str(resource.get("health") or "")
        if not health:
            # Before resource health existed: the worst of the targets.
            states = {str(target.get("healthStatus") or "") for target in resource.get("targets") or [] if target.get("enabled", True)}
            health = "unhealthy" if "unhealthy" in states else "healthy" if "healthy" in states else "unknown"
        return {"healthy": ("Healthy", "ok"), "unhealthy": ("Unhealthy", "bad"), "degraded": ("Degraded", "warn")}.get(health, ("Unknown", "unknown"))

    @staticmethod
    def _site_names(resource: dict[str, Any]) -> str:
        names = [str(site.get("siteName") or "") for site in resource.get("sites") or []]
        names += [str(name) for name in resource.get("siteNames") or []]
        if resource.get("siteName"):
            names.append(str(resource["siteName"]))
        return ", ".join(dict.fromkeys(name for name in names if name))

    def _status(self, sites: list[dict[str, Any]], public: list[dict[str, Any]], private: list[dict[str, Any]]) -> WidgetData:
        states = [self._site_state(site)[1] for site in sites]
        offline = states.count("bad")
        online = len(sites) - offline - states.count("warn")
        unhealthy = sum(1 for resource in public if self._health(resource)[1] == "bad")
        return WidgetData(
            status="bad" if offline or unhealthy else "warn" if "warn" in states else "ok",
            primary={"label": "Sites online", "value": f"{online}/{len(sites)}"},
            secondary=[
                {"label": "Offline", "value": offline},
                {"label": "Public resources", "value": len(public)},
                {"label": "Private resources", "value": len(private)},
                {"label": "Unhealthy", "value": unhealthy},
            ],
            metrics={"sites": float(len(sites)), "online": float(online)},
        )

    def _sites(self, sites: list[dict[str, Any]], options: dict[str, Any]) -> WidgetData:
        rows = []
        for site in sites:
            value, status = self._site_state(site)
            if options.get("only_offline") and status == "ok":
                continue
            parts = [str(site.get("type") or ""), str(site.get("address") or "")]
            rows.append({"title": site.get("name") or site.get("niceId") or "?", "subtitle": " · ".join(part for part in parts if part), "value": value, "status": status})
        order = {"bad": 0, "warn": 1, "ok": 2}
        rows.sort(key=lambda row: (order[row["status"]], str(row["title"]).lower()))
        online = sum(1 for site in sites if self._site_state(site)[1] == "ok")
        return WidgetData(
            items=rows[: int(options.get("limit") or 10)],
            secondary=[{"label": "Online", "value": online}, {"label": "Sites", "value": len(sites)}],
            metrics={"sites": float(len(sites)), "online": float(online)},
        )

    def _resources(self, public: list[dict[str, Any]], private: list[dict[str, Any]], options: dict[str, Any]) -> WidgetData:
        rows = []
        for resource in public:
            value, status = self._health(resource)
            address = resource.get("fullDomain") or (f"port {resource['proxyPort']}" if resource.get("proxyPort") else "")
            rows.append({"title": resource.get("name") or "?", "subtitle": " · ".join(part for part in (str(address), self._site_names(resource)) if part), "value": value, "status": status})
        for resource in private:
            enabled = resource.get("enabled", True)
            onlines = [bool(flag) for flag in resource.get("siteOnlines") or []]
            # A private resource has no health check; it is reachable while a site that carries it is online.
            if not enabled:
                value, status = "Disabled", "unknown"
            elif onlines and not any(onlines):
                value, status = "Offline", "bad"
            else:
                value, status = "Private", "ok"
            rows.append({"title": resource.get("name") or "?", "subtitle": " · ".join(part for part in (str(resource.get("destination") or ""), self._site_names(resource)) if part), "value": value, "status": status})
        if options.get("only_problems"):
            rows = [row for row in rows if row["status"] in ("bad", "warn")]
        order = {"bad": 0, "warn": 1, "ok": 2, "unknown": 3}
        rows.sort(key=lambda row: (order[row["status"]], str(row["title"]).lower()))
        problems = sum(1 for row in rows if row["status"] in ("bad", "warn"))
        return WidgetData(items=rows[: int(options.get("limit") or 10)], secondary=[{"label": "Resources", "value": len(public) + len(private)}, {"label": "Problems", "value": problems}])

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        cabin_online = not fake.flicker("pangolin-cabin", tick, 0.3)
        sites = [
            {"name": "Home lab", "type": "newt", "address": "100.89.128.4", "online": True, "resourceCount": 6},
            {"name": "Parents' house", "type": "newt", "address": "100.89.128.8", "online": True, "resourceCount": 2},
            {"name": "Cabin", "type": "wireguard", "address": "100.89.128.12", "online": cabin_online, "resourceCount": 1},
            {"name": "VPS", "type": "local", "online": None, "resourceCount": 1},
        ]
        public = [
            {"name": "Jellyfin", "fullDomain": "media.example.com", "enabled": True, "health": "healthy", "sites": [{"siteName": "Home lab"}]},
            {"name": "Nextcloud", "fullDomain": "cloud.example.com", "enabled": True, "health": "healthy", "sites": [{"siteName": "Home lab"}]},
            {"name": "Home Assistant", "fullDomain": "ha.example.com", "enabled": True, "health": "healthy", "sites": [{"siteName": "Home lab"}]},
            {"name": "Weather station", "fullDomain": "weather.example.com", "enabled": True, "health": "healthy" if cabin_online else "unhealthy", "sites": [{"siteName": "Cabin"}]},
            {"name": "Minecraft", "proxyPort": 25565, "enabled": False, "health": "unknown", "sites": [{"siteName": "Home lab"}]},
        ]
        private = [
            {"name": "NAS shares", "destination": "192.168.1.20", "enabled": True, "siteNames": ["Home lab"], "siteOnlines": [True]},
            {"name": "Parents' printer", "destination": "192.168.2.40", "enabled": True, "siteNames": ["Parents' house"], "siteOnlines": [True]},
        ]
        if widget_kind == "sites":
            return self._sites(sites, options)
        if widget_kind == "resources":
            show = str(options.get("show") or "public")
            return self._resources(public if show in ("public", "both") else [], private if show in ("private", "both") else [], options)
        return self._status(sites, public, private)


ADAPTER = PangolinAdapter()
