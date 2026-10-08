"""nginx ignition: whether nginx runs, what it is carrying, and what runs out.

A user interface for the nginx web server that can also run nginx for you.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from . import demo as fake
from .base import (
    Action,
    Adapter,
    AdapterError,
    Ask,
    Choice,
    Context,
    Detected,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    duration_short,
    human_bytes,
    measured,
    path_segment,
    percent,
    status_from_percent,
)

CERTIFICATE_WARN_DAYS = 30
CERTIFICATE_URGENT_DAYS = 7
CERTIFICATE_BAD_DAYS = 14
ERROR_WARN_SHARE = 1.0
ERROR_BAD_SHARE = 5.0
PAGE_SIZE_DEFAULT = 1000
PAGE_SIZE_COUNT_ONLY = 1
CACHE_TTL_SECONDS = 300
NO_TRAFFIC = "No traffic data recorded yet."
TOKEN_HINT = "Make an API token under the user menu in nginx ignition, and enter it in this connection."
PERMISSION_HINT = "Give the token's user this access under Users and Permissions in nginx ignition."
COMMANDS = {"reload": "nginx reloaded.", "start": "nginx started.", "stop": "nginx stopped."}


def _said(answer: Any) -> str:
    """What nginx ignition wrote about a refusal: ``{"message": ...}``."""
    if not isinstance(answer, dict):
        return ""
    return " ".join(str(answer.get("message") or "").split())[:240]


def _days_left(expires: Any) -> int | None:
    """The whole days a certificate has left, or None when it has no date.

    validUntil is a plain timestamp and not a pointer, so a certificate that
    never got one arrives as the zero time of year one. Read as a number that
    is 739000 days into the past.
    """
    if not expires:
        return None
    try:
        moment = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    if moment.year < 2000:
        return None
    return int((moment - datetime.now(UTC)).total_seconds() // 86400)


def _nearest(entries: list[dict[str, Any]]) -> tuple[str, int | None]:
    """The certificate running out soonest. ("", None) when none has a date.

    0 is a real answer: a certificate that runs out today is not the same as
    one with no date, and only the first is a fault.
    """
    for entry in entries:
        if entry.get("days") is not None:
            return str(entry.get("name") or "?"), int(entry["days"])
    return "", None


def _may(permissions: dict[str, str], resource: str) -> bool:
    """READ_WRITE writes, READ_ONLY does not."""
    return permissions.get(resource) == "READ_WRITE"


class NginxIgnitionAdapter(Adapter):
    kind = "nginxignition"
    label = "nginx ignition"
    category = "network"
    description = "Whether nginx runs, the traffic it carries, and the certificates that run out."
    icon = "nginx-ignition"
    docs_url = "https://github.com/lucasdillmann/nginx-ignition"
    #: Tested against a production nginx ignition 2.47.0 (08.10.2026).
    beta = False
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://nginx-ignition:8090"),
        Field("token", "API token", type="password", secret=True, required=True,
              help="Made in nginx ignition under the user menu. It carries the permissions of the user who "
                   "made it: one that may only read fills every card, one that may write adds the buttons."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="status",
            label="Status",
            description="Whether nginx runs and since when, how many hosts, streams and certificates there "
                        "are, and which nginx answers.",
            renderer="value",
            default_size=(3, 2),
            refresh_seconds=30,
            metrics=("hosts",),
        ),
        WidgetType(
            kind="traffic",
            label="Traffic",
            description="What nginx is carrying: requests, bytes and response time since it started, and the "
                        "connections it has right now.",
            renderer="stats",
            default_size=(3, 3),
            refresh_seconds=10,
            metrics=("requests", "received", "sent", "avg_time", "active", "reading", "writing", "waiting"),
        ),
        WidgetType(
            kind="certificates",
            label="Certificates",
            description="How many certificates there are, how many run out within thirty days, and the days "
                        "the nearest one has left.",
            renderer="value",
            default_size=(3, 2),
            refresh_seconds=30,
            metrics=("certificates", "expiring_soon", "days_left"),
        ),
    )

    @staticmethod
    def _headers(config: dict[str, Any]) -> dict[str, str]:
        return {"Authorization": f"Bearer {str(config.get('token') or '').strip()}"}

    async def _call(self, method: str, path: str, config: dict[str, Any], ctx: Context, *,
                    params: dict[str, Any] | None = None, cache: float = 30) -> httpx.Response:
        response = await ctx.request(
            method,
            f"{base_url(config)}/api{path}",
            headers=self._headers(config),
            params=params,
            verify=not config.get("insecure"),
            cache_seconds=cache if method.upper() == "GET" else 0,
            auth_errors=False,
        )
        if response.status_code >= 400:
            self._refused(response)
        return response

    @staticmethod
    def _refused(response: httpx.Response) -> None:
        """A 401 is a token nginx ignition does not know. A 403 is a token it
        knows that may not do this one thing, which is the ordinary shape of a
        read-only token."""
        try:
            answer: Any = response.json()
        except ValueError:
            answer = None
        said = _said(answer)
        if response.status_code == 401:
            raise AdapterError("nginx ignition turned the API token away.", code="auth_failed", hint=TOKEN_HINT)
        if response.status_code == 403:
            raise AdapterError("This API token may not do this in nginx ignition.",
                               code="forbidden_permission", hint=PERMISSION_HINT)
        if response.status_code == 424:
            raise AdapterError("nginx ignition could not act on nginx: " + (said or "no reason given"),
                               code="action_failed", hint="The error log of nginx ignition says more.")
        raise AdapterError(f"nginx ignition answered with HTTP {response.status_code}"
                           + (f": {said}" if said else "."), code="http_error")

    async def _json(self, path: str, config: dict[str, Any], ctx: Context, *,
                    params: dict[str, Any] | None = None, cache: float = 30) -> Any:
        try:
            return (await self._call("GET", path, config, ctx, params=params, cache=cache)).json()
        except ValueError as error:
            raise AdapterError("This address answers, but not the way nginx ignition does.",
                               code="not_json",
                               hint="Check the URL; it is nginx ignition itself, port 8090 by default."
                               ) from error

    def _not_nginx_ignition(self) -> AdapterError:
        return AdapterError("This address answers, but not the way nginx ignition does.",
                            code="not_json",
                            hint="Check the URL; it is nginx ignition itself, port 8090 by default.")

    async def _page(self, path: str, config: dict[str, Any], ctx: Context, *,
                    size: int = PAGE_SIZE_DEFAULT, cache: float = CACHE_TTL_SECONDS) -> list[dict[str, Any]]:
        answer = await self._json(path, config, ctx, params={"pageSize": size, "pageNumber": 0}, cache=cache)
        if not isinstance(answer, dict) or not isinstance(answer.get("contents"), list):
            raise self._not_nginx_ignition()
        return answer["contents"]

    async def _count(self, path: str, config: dict[str, Any], ctx: Context) -> int:
        """How many there are, without fetching any of them.

        The repositories run their COUNT before LIMIT and OFFSET, so a card that
        only wants a number pays for a number instead of every record.
        """
        answer = await self._json(path, config, ctx, params={"pageSize": PAGE_SIZE_COUNT_ONLY, "pageNumber": 0},
                                  cache=CACHE_TTL_SECONDS)
        try:
            return max(0, int(answer.get("totalItems") or 0)) if isinstance(answer, dict) else 0
        except (TypeError, ValueError):
            return 0

    async def _certificates(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        """Every certificate, the ones running out soonest first.

        The whole list, unlike the counts: which of them run out within thirty
        days cannot be answered from the first page.
        """
        rows = []
        for entry in await self._page("/certificates", config, ctx, cache=60):
            if not isinstance(entry, dict):
                continue
            names = entry.get("domainNames") or []
            rows.append({"id": str(entry.get("id") or ""),
                         "name": str(names[0]) if names else "?",
                         "days": _days_left(entry.get("validUntil"))})
        return sorted(rows, key=lambda row: (row["days"] is None, row["days"] or 0))

    async def _permissions(self, config: dict[str, Any], ctx: Context) -> dict[str, str]:
        """What this token may do. The only route open to any signed-in user, so
        an API token may read it, and the one place the answer is written down."""
        me = await self._json("/users/current", config, ctx, cache=CACHE_TTL_SECONDS)
        granted = me.get("permissions") if isinstance(me, dict) else None
        return {str(key): str(value) for key, value in granted.items()} if isinstance(granted, dict) else {}

    async def _statistics(self, config: dict[str, Any], ctx: Context) -> dict[str, Any]:
        """nginx ignition's home page checks all three of these before it asks,
        and a missing switch or a stopped server is an empty 500 and nothing
        else."""
        metadata = await self._json("/nginx/metadata", config, ctx, cache=60)
        if not isinstance(metadata, dict):
            raise self._not_nginx_ignition()
        if (metadata.get("availableSupport") or {}).get("stats") == "NONE":
            raise AdapterError("This nginx build does not support traffic statistics.",
                               code="nginxignition_stats_unsupported",
                               hint="nginx ignition reads them from a module inside nginx, and this one "
                                    "was built without it.")
        if not (metadata.get("stats") or {}).get("enabled"):
            raise AdapterError("Traffic statistics are disabled in settings.", code="nginxignition_stats_disabled",
                               hint="Turn them on in nginx ignition under Settings, nginx, statistics, "
                                    "then reload nginx.")
        status = await self._json("/nginx/status", config, ctx, cache=60)
        if not (isinstance(status, dict) and status.get("running")):
            raise AdapterError("Traffic statistics require nginx to be running.", code="nginxignition_stats_stopped",
                               hint="Start nginx from the Status card, or from the home page of nginx ignition.")
        try:
            answer = await self._json("/nginx/traffic-stats", config, ctx, cache=0)
        except AdapterError as failure:
            if failure.code != "http_error":
                raise
            raise AdapterError("nginx ignition could not read the traffic statistics of nginx.",
                               code="nginxignition_stats_unavailable",
                               hint="The statistics module hands them over over a socket of its own. "
                                    "Reload nginx, and read the error log of nginx ignition.") from failure
        if not isinstance(answer, dict):
            raise self._not_nginx_ignition()
        return answer

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        metadata = await self._json("/nginx/metadata", config, ctx, cache=0)
        frontend = await self._json("/frontend/configuration", config, ctx, cache=0)
        nginx = metadata.get("version") if isinstance(metadata, dict) else None
        reported = (frontend.get("version") or {}) if isinstance(frontend, dict) else {}
        # current is null on a development build
        ignition = f"version {reported['current']}" if reported.get("current") else "development version"
        return f"Connected successfully to nginx ignition {ignition} with nginx version {nginx or '?'}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "status":
            return self._status_card(
                await self._json("/nginx/status", config, ctx, cache=0),
                await self._json("/nginx/metadata", config, ctx, cache=CACHE_TTL_SECONDS),
                await self._count("/hosts", config, ctx),
                await self._count("/streams", config, ctx),
                await self._certificates(config, ctx),
                _may(await self._permissions(config, ctx), "nginxServer"),
            )
        if widget_kind == "traffic":
            return self._traffic_card(await self._statistics(config, ctx))
        return self._certificates_card(
            await self._certificates(config, ctx),
            _may(await self._permissions(config, ctx), "certificates"),
            base_url(config),
        )

    @staticmethod
    def _status_card(status: Any, metadata: Any, hosts: int, streams: int,
                     certificates: list[dict[str, Any]], may_write: bool) -> WidgetData:
        running = bool(status.get("running")) if isinstance(status, dict) else False
        _name, soonest = _nearest(certificates)
        buttons = [Action(id="start", label="Start", icon="play", confirm=True)] if not running else [
            Action(id="reload", label="Reload", icon="rotate-cw", confirm=True),
            Action(id="stop", label="Stop", icon="power", confirm=True)]
        return WidgetData(
            status="bad" if not running else "warn" if soonest is not None and soonest <= CERTIFICATE_WARN_DAYS else "ok",
            primary={"label": "Uptime" if running else "State",
                     "value": duration_short(status.get("uptimeSeconds")) if running else "Stopped"},
            secondary=[
                {"label": "Hosts", "value": hosts},
                {"label": "Streams", "value": streams},
                {"label": "Certificates", "value": len(certificates)},
                {"label": "nginx", "value": str(metadata.get("version") or "?") if isinstance(metadata, dict) else "?"},
            ],
            metrics=measured({"hosts": float(hosts)}),
            actions=buttons if may_write else [],
        )

    @staticmethod
    def _traffic_card(answer: dict[str, Any]) -> WidgetData:
        # "*" is the aggregate of every zone, which is what a global card wants.
        zone = (answer.get("serverZones") or {}).get("*") or {}
        connections = answer.get("connections") or {}
        responses = zone.get("responses") or {}
        requests = int(zone.get("requestCounter") or 0)
        average = int(zone.get("requestMsec") or 0)

        return WidgetData(
            status="unknown" if not requests
            else status_from_percent(percent(int(responses.get("5xx") or 0), requests),
                                     ERROR_WARN_SHARE, ERROR_BAD_SHARE),
            primary={"label": "Requests", "value": requests, "metric": "requests"},
            secondary=[
                {"label": "Received", "value": human_bytes(zone.get("inBytes")), "metric": "received"},
                {"label": "Sent", "value": human_bytes(zone.get("outBytes")), "metric": "sent"},
                {"label": "Avg. time", "value": f"{average / 1000:.2f}s" if average >= 1000 else f"{average:.2f}ms",
                 "metric": "avg_time"},
                {"label": "Active", "value": int(connections.get("active") or 0), "metric": "active"},
                {"label": "Reading", "value": int(connections.get("reading") or 0), "metric": "reading"},
                {"label": "Writing", "value": int(connections.get("writing") or 0), "metric": "writing"},
                {"label": "Waiting", "value": int(connections.get("waiting") or 0), "metric": "waiting"},
            ],
            metrics=measured({
                "requests": float(requests),
                "received": float(zone.get("inBytes") or 0),
                "sent": float(zone.get("outBytes") or 0),
                "avg_time": float(average),
                "active": float(connections.get("active") or 0),
                "reading": float(connections.get("reading") or 0),
                "writing": float(connections.get("writing") or 0),
                "waiting": float(connections.get("waiting") or 0),
            }),
            meta={} if requests else {"status_reason": NO_TRAFFIC},
        )

    @staticmethod
    def _renew_action(waiting: list[dict[str, Any]]) -> Action | None:
        """A renew button for what is running out, and nothing when none is.

        No button rather than one with an empty list: an empty choice looks like a
        question with no answer. One candidate needs no question, several do.
        """
        if not waiting:
            return None
        renew = Action(id="renew", label="Renew", icon="refresh-cw", confirm=True)
        if len(waiting) == 1:
            renew.params = {"id": waiting[0]["id"]}
            return renew
        renew.asks = [Ask(
            name="id",
            label="Certificate",
            kind="choice",
            options=[Choice(value=entry["id"],
                           label=f"{entry['name']}, {entry['days']} d left" if entry["days"] > 0
                           else f"{entry['name']}, already run out")
                    for entry in waiting],
        )]
        return renew

    @classmethod
    def _certificates_card(cls, entries: list[dict[str, Any]], may_write: bool, base: str) -> WidgetData:
        name, soonest = _nearest(entries)
        days = [entry["days"] for entry in entries if entry["days"] is not None]
        expired = sum(1 for day in days if day < 0)
        within_week = sum(1 for day in days if 0 <= day <= CERTIFICATE_URGENT_DAYS)
        within_month = sum(1 for day in days if 0 <= day <= CERTIFICATE_WARN_DAYS)
        renew = cls._renew_action([entry for entry in entries
                                   if entry["days"] is not None and entry["days"] <= CERTIFICATE_WARN_DAYS])
        return WidgetData(
            status="bad" if soonest is not None and soonest <= CERTIFICATE_URGENT_DAYS
            else "warn" if soonest is not None and soonest <= CERTIFICATE_WARN_DAYS
            else "ok" if entries else "unknown",
            primary={"label": "Certificates", "value": len(entries)},
            secondary=[
                {"label": "Expiring within 30d", "value": within_month},
                {"label": "Expiring within 7d", "value": within_week},
                {"label": "Expired", "value": expired},
                {"label": "Next expiration in", "value": f"{soonest} d" if soonest is not None else "?"},
            ],
            metrics=measured({
                "certificates": float(len(entries)),
                "expiring_soon": float(within_month),
                **({"days_left": float(soonest)} if soonest is not None else {}),
            }),
            link=f"{base}/certificates",
            actions=[renew] if renew and may_write else [],
            meta={"soonest": name},
        )

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        if action_id == "renew":
            answer = await self._call("POST", f"/certificates/{path_segment(params.get('id'), 'The certificate')}/renew",
                                      config, ctx)
            ctx.forget_answers()
            try:
                done: Any = answer.json()
            except ValueError:
                done = None
            if isinstance(done, dict) and done.get("success"):
                return "Certificate renewed."
            reason = " ".join(str((done or {}).get("errorReason") or "").split())[:240] if isinstance(done, dict) else ""
            raise AdapterError("nginx ignition could not renew the certificate"
                               + (f": {reason}" if reason else "."), code="certificate_failed",
                               hint="Check the certificate's provider settings, and that the port its "
                                    "challenge is answered on is reachable.")
        if action_id not in COMMANDS:
            raise AdapterError("nginx ignition has no such action.", code="no_such_action")
        await self._call("POST", f"/nginx/{action_id}", config, ctx)
        ctx.forget_answers()
        return COMMANDS[action_id]

    def detect(self, widget_kind: str, before: WidgetData | None, after: WidgetData,
               options: dict[str, Any]) -> list[Detected]:
        """A certificate crossing a line, said once at the crossing.

        Not every morning while it counts down: thirty days is a month of
        identical notifications, and a notice centre nobody reads is worse than none.
        """
        if widget_kind != "certificates" or before is None or before.error or after.error:
            return []
        now = (after.metrics or {}).get("days_left")
        was = (before.metrics or {}).get("days_left")
        if now is None or was is None:
            return []
        if not was > CERTIFICATE_WARN_DAYS >= now and now > CERTIFICATE_BAD_DAYS:
            return []
        name = str(after.meta.get("soonest") or "") or "A certificate"
        return [Detected(
            event="cert_expiring",
            title=f"{name} runs out in {int(now)} days" if now > 0 else f"{name} has run out",
            body="Renew it from this card, or let nginx ignition do it if auto-renew is on.",
            level="bad" if now <= CERTIFICATE_BAD_DAYS else "warn",
            key=f"cert_expiring:{name}:{int(now) // 7}",
            quiet_seconds=86400,
        )]

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        days = int(fake.walk("nginxignition-cert", tick, 3, 300, period=900))
        running = fake.walk("nginxignition-up", tick, 0, 1, period=1200) > 0.2
        if widget_kind == "certificates":
            return self._certificates_card(_demo_certificates(days), True, "http://nginx-ignition:8090")
        if widget_kind == "traffic":
            return self._traffic_card(_demo_statistics(tick))
        return self._status_card(
            {"running": running, "uptimeSeconds": fake.walk("nginxignition-uptime", tick, 900, 900000, period=2400)},
            {"version": "1.27.0"},
            fake.counter("nginxignition-hosts", tick, 14, 0.01),
            fake.counter("nginxignition-streams", tick, 2, 0.004),
            _demo_certificates(days),
            True,
        )


def _demo_certificates(days: int) -> list[dict[str, Any]]:
    return sorted([
        {"id": "cert-1", "name": "deck.example.com", "days": days},
        {"id": "cert-2", "name": "photos.example.com", "days": days + 12},
        {"id": "cert-3", "name": "mail.example.org", "days": 118},
        {"id": "cert-4", "name": "old.example.net", "days": 264},
    ], key=lambda row: (row["days"] is None, row["days"] or 0))


def _demo_statistics(tick: int) -> dict[str, Any]:
    active = int(fake.walk("nginxignition-active", tick, 12, 180, period=300))
    broken = fake.flicker("nginxignition-5xx", tick, 0.1)
    requests = fake.counter("nginxignition-req", tick, 184_203, 90)
    mean = fake.walk("nginxignition-ms", tick, 4, 180, period=420)
    return {
        "hostName": "nginx-ignition",
        "connections": {"active": active, "reading": active // 7, "writing": active // 4, "waiting": active // 2,
                        "accepted": requests + 197, "handled": requests + 197, "requests": requests},
        "serverZones": {
            "*": {
                "requestCounter": requests,
                "inBytes": fake.walk("nginxignition-in", tick, 4e9, 9e10, period=600),
                "outBytes": fake.walk("nginxignition-out", tick, 9e8, 4e10, period=600),
                "requestMsec": round(mean * requests),
                "requestMsecCounter": requests,
                "requestMsecs": {"times": [], "msecs": []},
                "responses": {"1xx": 0, "2xx": requests - 200, "3xx": 80, "4xx": 120, "5xx": 900 if broken else 3,
                              "miss": 0, "bypass": 0, "expired": 0, "stale": 0,
                              "updating": 0, "revalidated": 0, "hit": 0, "scarce": 0},
            },
        },
        "filterZones": None,
        "upstreamZones": None,
    }


ADAPTER = NginxIgnitionAdapter()
