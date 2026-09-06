"""Nginx Proxy Manager: the hosts it serves and the certificates that run out.

An expiring certificate is the one thing a proxy widget must catch: nothing
looks wrong until the day nothing works. NPM has no API key; it hands out a
token for an account, which nexdeck keeps until it expires.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Detected,
    Field,
    WidgetData,
    WidgetType,
    base_url,
)

#: A certificate this close to its end is a finding, not a note.
WARN_DAYS = 21
BAD_DAYS = 7


class NpmAdapter(Adapter):
    kind = "npm"
    #: Confirmed against a live instance on 2026-09-05: 16 proxy hosts, two
    #: certificates, the nearer one 61 days out.
    beta = False
    label = "Nginx Proxy Manager"
    category = "network"
    description = "Proxy hosts with their state, and certificates with the days they have left."
    icon = "nginx-proxy-manager"
    docs_url = "https://nginxproxymanager.com/api/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://npm:81"),
        Field("email", "E-mail address", required=True, help="The account nexdeck signs in with; a read-only one is enough."),
        Field("password", "Password", type="password", secret=True, required=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="hosts",
            label="Proxy hosts",
            description="Every host with its target, disabled ones marked.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=300,
            metrics=("hosts",),
            options=(Field("limit", "Entries", type="number", default=10),),
        ),
        WidgetType(
            kind="certificates",
            label="Certificates",
            description="What runs out when, the soonest first.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=3600,
            metrics=("days_left",),
            options=(Field("limit", "Entries", type="number", default=8),),
        ),
        WidgetType(
            kind="status",
            label="Status",
            description="Hosts, disabled ones and the certificate that expires next.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=600,
            metrics=("hosts", "days_left"),
        ),
    )

    async def _token(self, config: dict[str, Any], ctx: Context, force: bool = False) -> str:
        cached = ctx.cache.get("npm_token")
        if cached and not force and cached[0] > time.time():
            return cached[1]
        response = await ctx.request(
            "POST",
            f"{base_url(config)}/api/tokens",
            json_body={"identity": str(config.get("email") or ""), "secret": str(config.get("password") or "")},
            verify=not config.get("insecure"),
        )
        if response.status_code >= 400:
            raise AuthFailed("Nginx Proxy Manager rejected the account.")
        payload = response.json()
        token = str(payload.get("token") or "")
        if not token:
            raise AuthFailed("Nginx Proxy Manager did not hand out a token.")
        # Its tokens last a day; ask again well before that.
        ctx.cache["npm_token"] = (time.time() + 3600, token)
        return token

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 60, retry: bool = True) -> Any:
        token = await self._token(config, ctx)
        response = await ctx.request(
            "GET",
            f"{base_url(config)}/api{path}",
            headers={"Authorization": f"Bearer {token}"},
            verify=not config.get("insecure"),
            cache_seconds=cache,
        )
        if response.status_code in (401, 403) and retry:
            await self._token(config, ctx, force=True)
            return await self._get(config, ctx, path, cache, retry=False)
        if response.status_code >= 400:
            raise AdapterError(f"Nginx Proxy Manager answered with HTTP {response.status_code}.", code="http_error")
        return response.json()

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        hosts = await self._get(config, ctx, "/nginx/proxy-hosts", cache=0)
        return f"Nginx Proxy Manager answers with {len(hosts) if isinstance(hosts, list) else 0} proxy hosts."

    @staticmethod
    def _days_left(expires: str) -> int | None:
        if not expires:
            return None
        try:
            moment = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
        except ValueError:
            return None
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        return int((moment - datetime.now(UTC)).total_seconds() // 86400)

    def _certificate_items(self, certificates: Any) -> list[dict[str, Any]]:
        items = []
        for certificate in certificates if isinstance(certificates, list) else []:
            days = self._days_left(certificate.get("expires_on") or "")
            status = "ok"
            if days is not None and days <= BAD_DAYS:
                status = "bad"
            elif days is not None and days <= WARN_DAYS:
                status = "warn"
            names = certificate.get("domain_names") or []
            items.append({
                "title": certificate.get("nice_name") or (names[0] if names else "?"),
                "subtitle": ", ".join(names[:3]),
                "value": f"{days} d" if days is not None else "?",
                "status": status,
                "days": days if days is not None else 9999,
            })
        items.sort(key=lambda entry: entry["days"])
        return items

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "hosts":
            hosts = await self._get(config, ctx, "/nginx/proxy-hosts", cache=300)
            limit = int(options.get("limit") or 10)
            items = []
            for host in hosts if isinstance(hosts, list) else []:
                names = host.get("domain_names") or []
                enabled = bool(host.get("enabled", 1))
                items.append({
                    "title": names[0] if names else "?",
                    "subtitle": f"{host.get('forward_scheme', 'http')}://{host.get('forward_host', '?')}:{host.get('forward_port', '')}",
                    "value": "SSL" if host.get("certificate_id") else "",
                    "status": "ok" if enabled else "unknown",
                })
            return WidgetData(
                items=items[:limit],
                secondary=[{"label": "Hosts", "value": len(items)}],
                metrics={"hosts": float(len(items))},
            )

        certificates = await self._get(config, ctx, "/nginx/certificates", cache=3600)
        items = self._certificate_items(certificates)
        soonest = items[0]["days"] if items else None

        if widget_kind == "certificates":
            limit = int(options.get("limit") or 8)
            worst = "bad" if any(entry["status"] == "bad" for entry in items) else ("warn" if any(entry["status"] == "warn" for entry in items) else "ok")
            return WidgetData(
                status=worst,
                items=[{k: v for k, v in entry.items() if k != "days"} for entry in items[:limit]],
                secondary=[{"label": "Certificates", "value": len(items)}],
                metrics={"days_left": float(soonest)} if soonest is not None else {},
            )

        hosts = await self._get(config, ctx, "/nginx/proxy-hosts", cache=300)
        host_list = hosts if isinstance(hosts, list) else []
        disabled = sum(1 for host in host_list if not host.get("enabled", 1))
        status = "ok"
        if soonest is not None and soonest <= BAD_DAYS:
            status = "bad"
        elif (soonest is not None and soonest <= WARN_DAYS) or disabled:
            status = "warn"
        return WidgetData(
            status=status,
            primary={"label": "Hosts", "value": len(host_list)},
            secondary=[
                {"label": "Disabled", "value": disabled},
                {"label": "Certificates", "value": len(items)},
                {"label": "Expires in", "value": f"{soonest} d" if soonest is not None else "?"},
            ],
            metrics={"hosts": float(len(host_list)), **({"days_left": float(soonest)} if soonest is not None else {})},
        )

    #: A certificate with fewer days than this is worth waking somebody for.
    CERT_WARN_DAYS = 14

    def detect(self, widget_kind: str, before: WidgetData | None, after: WidgetData,
               options: dict[str, Any]) -> list[Detected]:
        """A certificate that is running out.

        ⚠️ Said once a day per certificate, not once per refresh. This card
        reads every few minutes, and a renewal that needs a human takes days.
        """
        if widget_kind != "certificates":
            return []
        found = []
        for item in after.items:
            days = item.get("days_left")
            if days is None:
                # The list carries the number in its value as "12 d".
                raw = str(item.get("value") or "").split()
                days = int(raw[0]) if raw and raw[0].lstrip("-").isdigit() else None
            if days is None or days > self.CERT_WARN_DAYS:
                continue
            name = str(item.get("title") or "A certificate")
            found.append(Detected(
                event="cert_expiring",
                title=f"{name} runs out in {days} days" if days > 0 else f"{name} has run out",
                body="Renew it, or check that whatever renews it still can.",
                level="warn",
                key=f"cert_expiring:{name}",
                quiet_seconds=86400,
            ))
        return found[:5]

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        soonest = int(fake.walk("npm-cert", tick, 4, 70, period=600))
        if widget_kind == "hosts":
            rows = [
                ("deck.example.com", "http://nexdeck:8000", True),
                ("photos.example.com", "http://immich:2283", True),
                ("plex.example.com", "http://plex:32400", True),
                ("old.example.com", "http://retired:8080", False),
            ]
            items = [
                {"title": name, "subtitle": target, "value": "SSL" if enabled else "", "status": "ok" if enabled else "unknown"}
                for name, target, enabled in rows
            ]
            return WidgetData(items=items, secondary=[{"label": "Hosts", "value": len(items)}], metrics={"hosts": float(len(items))})
        certificates = [("example.com", "example.com, *.example.com", soonest), ("intern.example.org", "intern.example.org", soonest + 32)]
        items = [
            {
                "title": name,
                "subtitle": names,
                "value": f"{days} d",
                "status": "bad" if days <= BAD_DAYS else ("warn" if days <= WARN_DAYS else "ok"),
            }
            for name, names, days in certificates
        ]
        if widget_kind == "certificates":
            return WidgetData(
                status=items[0]["status"],
                items=items,
                secondary=[{"label": "Certificates", "value": len(items)}],
                metrics={"days_left": float(soonest)},
            )
        return WidgetData(
            status=items[0]["status"],
            primary={"label": "Hosts", "value": 12},
            secondary=[
                {"label": "Disabled", "value": 1},
                {"label": "Certificates", "value": len(items)},
                {"label": "Expires in", "value": f"{soonest} d"},
            ],
            metrics={"hosts": 12.0, "days_left": float(soonest)},
        )


ADAPTER = NpmAdapter()
