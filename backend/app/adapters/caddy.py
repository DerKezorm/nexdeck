"""Caddy: which sites it serves, where it sends them, and whether the upstreams answer.

Caddy's admin API is a configuration API, and the routes live in that
configuration: ``GET /config/apps/http/servers/`` returns every server with
its routes, and a route's ``match`` and ``handle`` say which host goes where.
Whether an upstream is up is not in the configuration. ``/reverse_proxy/upstreams``
lists them with the requests in flight and the failures counted so far, but
never the verdict of an active health check.

⚠️ The verdict is in ``/metrics`` on the same port, as
``caddy_reverse_proxy_upstreams_healthy{upstream="host:port"}`` (1 or 0).
Measured against Caddy 2.11.7 on 27.10.2026: an upstream whose active check
fails showed ``fails: 0`` in ``/reverse_proxy/upstreams`` for as long as it
was watched, and 0 in the gauge. An upstream without any check shows 1.

The admin API has no sign-in. It listens on localhost:2019 by default; to
reach it from another machine the global option ``admin`` names an address,
and that port then belongs inside the network.
"""

from __future__ import annotations

import re
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
)
from .uptimekuma import LABEL

#: A line of the metrics with or without labels. ⚠️ The reload gauges have
#: none, and the parser Uptime Kuma uses skips a line without braces.
SAMPLE = re.compile(r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(?P<labels>[^}]*)\})?\s+(?P<value>[-+0-9.eEnaN]+)\s*$")


def parse_metrics(text: str) -> list[tuple[str, dict[str, str], float]]:
    rows = []
    for line in text.splitlines():
        match = SAMPLE.match(line)
        if line.startswith("#") or not match:
            continue
        try:
            value = float(match.group("value"))
        except ValueError:
            continue
        rows.append((match.group("name"), dict(LABEL.findall(match.group("labels") or "")), value))
    return rows


def _auth(config: dict[str, Any]) -> tuple[str, str] | None:
    user = str(config.get("username") or "")
    return (user, str(config.get("password") or "")) if user else None


def _dial(address: str) -> str:
    """An upstream as the metrics name it: ``host:port`` without a scheme."""
    text = str(address or "").strip()
    for prefix in ("tcp/", "http://", "https://"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text


def _kind_of(handler: dict[str, Any]) -> str | None:
    """What one handler of a route does, in a word, or ``None`` for plumbing."""
    name = handler.get("handler")
    if name == "reverse_proxy":
        return "Proxy"
    if name == "file_server":
        return "Files"
    if name == "static_response":
        status = str(handler.get("status_code") or "")
        return "Redirect" if status.startswith("3") or (handler.get("headers") or {}).get("Location") else "Response"
    if name in ("php_fastcgi", "fastcgi"):
        return "PHP"
    return None


def _walk(handlers: list[Any], found: dict[str, Any]) -> None:
    """Collect what a route does, through nested subroutes."""
    for handler in handlers or []:
        if not isinstance(handler, dict):
            continue
        kind = _kind_of(handler)
        if kind:
            found["kinds"].append(kind)
        if handler.get("handler") == "reverse_proxy":
            for upstream in handler.get("upstreams") or []:
                if isinstance(upstream, dict) and upstream.get("dial"):
                    found["upstreams"].append(_dial(upstream["dial"]))
        for route in handler.get("routes") or []:
            if isinstance(route, dict):
                _walk(route.get("handle") or [], found)


def sites_of(servers: dict[str, Any]) -> list[dict[str, Any]]:
    """One entry per host name Caddy answers for.

    A route without a host matcher answers for everything on its server's
    port, and is named by that port. ``upstreams`` keeps the order Caddy has.
    """
    sites: list[dict[str, Any]] = []
    for server in (servers or {}).values():
        if not isinstance(server, dict):
            continue
        listen = ", ".join(str(one) for one in server.get("listen") or [])
        for route in server.get("routes") or []:
            if not isinstance(route, dict):
                continue
            found: dict[str, Any] = {"kinds": [], "upstreams": []}
            _walk(route.get("handle") or [], found)
            hosts: list[str] = []
            for match in route.get("match") or []:
                hosts += [str(host) for host in (match or {}).get("host") or []]
            names = hosts or [listen or "?"]
            for name in names:
                sites.append({
                    "host": name,
                    "listen": listen,
                    "kind": found["kinds"][0] if found["kinds"] else "Other",
                    "upstreams": list(dict.fromkeys(found["upstreams"])),
                })
    return sites


def health_of(rows: list[tuple[str, dict[str, str], float]]) -> tuple[dict[str, bool], bool | None]:
    """The verdict per upstream, and whether the last reload worked (None: not said)."""
    health: dict[str, bool] = {}
    reload_ok: bool | None = None
    for name, labels, value in rows:
        if name == "caddy_reverse_proxy_upstreams_healthy" and labels.get("upstream"):
            health[_dial(labels["upstream"])] = value >= 1
        elif name == "caddy_config_last_reload_successful":
            reload_ok = value >= 1
    return health, reload_ok


class CaddyAdapter(Adapter):
    kind = "caddy"
    label = "Caddy"
    category = "network"
    description = "The sites Caddy serves, where it sends them, and which upstreams are down."
    icon = "caddy"
    docs_url = "https://caddyserver.com/docs/api"
    #: Measured against Caddy 2.11.7 on 27.10.2026, every card; it stays beta until somebody confirms it on an instance in use.
    beta = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://caddy:2019",
              help="The address of the admin API, not of a site Caddy serves."),
        Field("username", "User name", help="Only if a proxy in front of the admin API asks for basic authentication."),
        Field("password", "Password", type="password", secret=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    guide = (
        "Caddy's admin API listens on localhost:2019 and has no sign-in. To reach it from nexdeck, name an address in the global options: { admin 0.0.0.0:2019 }.",
        "Publish that port to your own network only, never to the internet.",
        "The state of the upstreams comes from the metrics on the same port, which Caddy serves by default.",
    )
    widgets = (
        WidgetType(
            kind="overview",
            label="Overview",
            description="How many sites Caddy serves, how many upstreams are down, and whether the last reload worked.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=60,
            metrics=("sites", "upstreams_down"),
        ),
        WidgetType(
            kind="sites",
            label="Sites",
            description="One line per host name: what it does and how many of its upstreams answer, the broken ones first.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=120,
            options=(
                Field("limit", "Entries", type="number", default=12),
                Field("only_problems", "Only problems", type="bool", default=False),
            ),
        ),
        WidgetType(
            kind="upstreams",
            label="Upstreams",
            description="Every upstream behind a reverse proxy with its state, the requests in flight and the failures counted.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=60,
            options=(Field("limit", "Entries", type="number", default=12),),
        ),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 20) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}{path}", auth=_auth(config),
            verify=not config.get("insecure"), cache_seconds=cache,
        )
        if response.status_code >= 400:
            raise AdapterError(
                f"Caddy answered with HTTP {response.status_code}.", code="http_error",
                hint="Check the URL; it is the address of the admin API, port 2019 unless you changed it.")
        return response

    async def _json(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 20) -> Any:
        response = await self._get(config, ctx, path, cache)
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Caddy did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a site Caddy serves, not at the admin API.") from error

    async def _health(self, config: dict[str, Any], ctx: Context) -> tuple[dict[str, bool], bool | None]:
        """The upstreams' verdicts, or nothing when the metrics are not served.

        ⚠️ Not an error. ``metrics`` can be switched off in the admin
        configuration, and the sites and the upstreams are still worth showing.
        """
        try:
            response = await self._get(config, ctx, "/metrics", 20)
        except AdapterError as error:
            if error.code == "http_error":
                return {}, None
            raise
        return health_of(parse_metrics(response.text))

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        servers = await self._json(config, ctx, "/config/apps/http/servers/", cache=0)
        if servers is not None and not isinstance(servers, dict):
            raise AdapterError("Caddy answered with something unexpected.", code="unexpected")
        sites = sites_of(servers or {})
        return f"Caddy answers, {len(sites)} site(s)."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        servers = await self._json(config, ctx, "/config/apps/http/servers/")
        health, reload_ok = await self._health(config, ctx)
        sites = sites_of(servers if isinstance(servers, dict) else {})
        if widget_kind == "upstreams":
            listed = await self._json(config, ctx, "/reverse_proxy/upstreams")
            return self._upstreams(listed if isinstance(listed, list) else [], health, options)
        if widget_kind == "sites":
            return self._sites(sites, health, options)
        upstreams = {dial for site in sites for dial in site["upstreams"]}
        down = sorted(dial for dial in upstreams if health.get(dial) is False)
        secondary = [
            {"label": "Upstreams", "value": len(upstreams)},
            {"label": "Down", "value": len(down)},
        ]
        if reload_ok is not None:
            secondary.append({"label": "Last reload", "value": "Worked" if reload_ok else "Failed"})
        return WidgetData(
            status="bad" if down or reload_ok is False else "ok",
            primary={"label": "Sites", "value": len(sites)},
            secondary=secondary,
            metrics={"sites": float(len(sites)), "upstreams_down": float(len(down))},
        )

    def _sites(self, sites: list[dict[str, Any]], health: dict[str, bool], options: dict[str, Any]) -> WidgetData:
        limit = int(options.get("limit") or 12)
        items = []
        for site in sites:
            ups = site["upstreams"]
            known = [health[dial] for dial in ups if dial in health]
            up = sum(1 for one in known if one)
            if not ups:
                state, value = "ok", ""
            elif known and up == 0:
                state, value = "bad", "Down"
            elif known and up < len(ups):
                state, value = "warn", f"{up} of {len(ups)} up"
            else:
                state, value = "ok", "Up" if known else ""
            if options.get("only_problems") and state == "ok":
                continue
            items.append({
                "title": site["host"],
                "subtitle": " · ".join(part for part in (site["kind"], ", ".join(ups)) if part),
                "status": state,
                "value": value,
            })
        order = {"bad": 0, "warn": 1, "ok": 2}
        items.sort(key=lambda entry: order[entry["status"]])
        states = {entry["status"] for entry in items}
        return WidgetData(
            status="bad" if "bad" in states else "warn" if "warn" in states else "ok",
            items=items[:limit],
            secondary=[{"label": "Sites", "value": len(sites)}],
        )

    def _upstreams(self, listed: list[Any], health: dict[str, bool], options: dict[str, Any]) -> WidgetData:
        limit = int(options.get("limit") or 12)
        items = []
        for row in listed:
            if not isinstance(row, dict) or not row.get("address"):
                continue
            address = _dial(row["address"])
            alive = health.get(address)
            fails = int(row.get("fails") or 0)
            busy = int(row.get("num_requests") or 0)
            items.append({
                "title": address,
                "subtitle": " · ".join(part for part in (f"{busy} in flight" if busy else "", f"{fails} failed" if fails else "") if part),
                "status": "bad" if alive is False else "warn" if fails else "ok",
                "value": "Down" if alive is False else "Up" if alive else "",
            })
        order = {"bad": 0, "warn": 1, "ok": 2}
        items.sort(key=lambda entry: order[entry["status"]])
        down = sum(1 for entry in items if entry["status"] == "bad")
        return WidgetData(
            status="bad" if down else "warn" if any(entry["status"] == "warn" for entry in items) else "ok",
            items=items[:limit],
            secondary=[{"label": "Upstreams", "value": len(items)}, {"label": "Down", "value": down}],
            metrics={"upstreams_down": float(down)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        broken = fake.flicker("caddy-upstream", tick, 0.12)
        sites = [
            {"host": "deck.example.com", "kind": "Proxy", "upstreams": ["nexdeck:8000"]},
            {"host": "photos.example.com", "kind": "Proxy", "upstreams": ["immich:2283", "immich-b:2283"]},
            {"host": "git.example.com", "kind": "Proxy", "upstreams": ["forgejo:3000"]},
            {"host": "files.example.com", "kind": "Files", "upstreams": []},
            {"host": "old.example.com", "kind": "Redirect", "upstreams": []},
        ]
        health = {"nexdeck:8000": True, "immich:2283": not broken, "immich-b:2283": True, "forgejo:3000": True}
        if widget_kind == "upstreams":
            rows = [{"address": dial, "num_requests": int(fake.walk(f"caddy-{dial}", tick, 0, 6)), "fails": 0 if up else 3}
                    for dial, up in health.items()]
            return self._upstreams(rows, health, options)
        if widget_kind == "sites":
            return self._sites(sites, health, options)
        down = 0 if not broken else 1
        return WidgetData(
            status="bad" if down else "ok",
            primary={"label": "Sites", "value": len(sites)},
            secondary=[{"label": "Upstreams", "value": len(health)}, {"label": "Down", "value": down},
                       {"label": "Last reload", "value": "Worked"}],
            metrics={"sites": float(len(sites)), "upstreams_down": float(down)},
        )


ADAPTER = CaddyAdapter()
