"""nextrmnl: the connection manager of the nexapps family, read through its API keys.

Built against nextrmnl's own ``/api/v1``, which exists for dashboards and
nothing else: status, live sessions, history and whether each connection's
port answers. Every call is a GET, and a key there can open no terminal, no
file and no vault. nextrmnl leaves the sender addresses out of every answer,
so they cannot end up on a board guests see.

Three things nextrmnl says that shape the cards:
- The operator has a switch for API keys, closed by default. A key that is
  fine but refused because of it gets a sentence that says where the switch
  is, not "the key was rejected".
- ``end`` of a past session is ``normal``, ``failed``, ``hostkey`` or ``cut``.
  ``hostkey`` means the server answered with another host key than before:
  that is the one row that must stand out.
- nextrmnl reuses its reachability answer for a minute, so asking more
  often than that only gets the same answer.
"""

from __future__ import annotations

from typing import Any

from .base import Adapter, AdapterError, Context, Field, WidgetData, WidgetType, ago, base_url

#: nextrmnl's refusals by their code, as a sentence that says what to do and a code the interface translates by.
REFUSALS: dict[str, tuple[str, str]] = {
    "api_key_missing": ("nextrmnl received no API key. Enter the key in this connection.", "nextrmnl_key_missing"),
    "api_key_invalid": (
        "nextrmnl does not know this key, it was deleted, or the account that made it is no operator any more. "
        "Create a new key in nextrmnl under Settings → Security → API keys.",
        "nextrmnl_key_invalid",
    ),
    "api_keys_off": (
        "API keys are switched off on this nextrmnl. The operator switches them on under Settings → Security → API keys.",
        "nextrmnl_keys_off",
    ),
}

#: How a past session ended, as the row shows it: status, and the word under the title.
ENDS: dict[str, tuple[str, str]] = {
    "normal": ("ok", ""),
    "running": ("ok", "Running"),
    "failed": ("bad", "Failed"),
    "hostkey": ("bad", "Host key changed"),
    "cut": ("warn", "Cut off"),
}


def _limit(options: dict[str, Any]) -> int:
    try:
        wanted = int(options.get("limit") or 8)
    except (TypeError, ValueError):
        wanted = 8
    return max(1, min(100, wanted))


class NextrmnlAdapter(Adapter):
    kind = "nextrmnl"
    label = "nextrmnl"
    category = "hosts"
    description = "Live SSH sessions, the latest ones and whether your connections answer, from nextrmnl, through a read-only API key."
    icon = "nextrmnl"
    docs_url = "https://nextrmnl.nexapps.dev"
    keywords = ("SSH", "SFTP", "terminal", "PuTTY")
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://ssh.example.com",
              help="The address nextrmnl is reached at."),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="A key from nextrmnl under Settings → Security → API keys. The operator makes it, "
                   "and API keys have to be switched on there."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="status",
            label="Status",
            description="Live sessions, today's sessions and failures, connections, and whether an update waits.",
            renderer="value",
            default_size=(2, 2),
            refresh_seconds=60,
            metrics=("sessions_running",),
        ),
        WidgetType(
            kind="sessions",
            label="Live sessions",
            description="Who is connected where right now, and since when.",
            renderer="list",
            default_size=(3, 2),
            refresh_seconds=30,
        ),
        WidgetType(
            kind="history",
            label="Latest sessions",
            description="The latest sessions and how they ended; a changed host key stands out.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=60,
            options=(Field("limit", "Entries", type="number", default=8, help="Between 1 and 100."),),
        ),
        WidgetType(
            kind="connections",
            label="Connections",
            description="Whether the port of each connection answers, and how fast.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=120,
            options=(Field("only_down", "Only what does not answer", type="bool", default=False),),
        ),
    )

    def default_link(self, config: dict[str, Any]) -> str:
        return base_url(config)

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, *, params: Any = None, cache: float = 20) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}{path}", params=params,
            headers={"Authorization": f"Bearer {config.get('api_key', '')}"},
            verify=not config.get("insecure"), cache_seconds=cache,
            # ⚠️ Not turned into "the credentials were rejected": nextrmnl says
            # whether the key is unknown or API keys are switched off, and the
            # second is fixed somewhere else entirely.
            auth_errors=False,
        )
        if response.status_code in (401, 403):
            try:
                detail = response.json().get("detail") or {}
            except ValueError:
                detail = {}
            code = detail.get("code") if isinstance(detail, dict) else None
            if code in REFUSALS:
                message, ours = REFUSALS[code]
                raise AdapterError(message, code=ours)
            raise AdapterError("nextrmnl refused the request.", code="nextrmnl_refused")
        if response.status_code == 404:
            raise AdapterError(
                "This nextrmnl has no API for dashboards yet. It needs a version with API keys.",
                code="nextrmnl_too_old",
            )
        if response.status_code >= 400:
            raise AdapterError(f"nextrmnl answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("nextrmnl did not answer with JSON.", code="bad_answer",
                               hint="The URL probably points at a sign-in page or a reverse proxy.") from error

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        status = await self._get(config, ctx, "/api/v1/status", cache=0)
        return f"nextrmnl {status.get('version', '?')} answers; {int(status.get('sessions_running') or 0)} live sessions."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "status":
            return self._status(await self._get(config, ctx, "/api/v1/status"))
        if widget_kind == "sessions":
            return self._sessions(await self._get(config, ctx, "/api/v1/sessions"))
        if widget_kind == "history":
            return self._history(await self._get(config, ctx, "/api/v1/history", params={"limit": _limit(options)}))
        if widget_kind == "connections":
            return self._connections(await self._get(config, ctx, "/api/v1/connections", cache=60), bool(options.get("only_down")))
        raise KeyError(widget_kind)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _status(status: dict[str, Any]) -> WidgetData:
        running = int(status.get("sessions_running") or 0)
        update = bool(status.get("update_available"))
        chips: list[dict[str, Any]] = [
            {"label": "Today", "value": int(status.get("sessions_today") or 0)},
            {"label": "Failed today", "value": int(status.get("failed_today") or 0)},
            {"label": "Connections", "value": int(status.get("connections") or 0)},
        ]
        if update and status.get("latest_version"):
            chips.append({"label": "New version", "value": str(status["latest_version"])})
        return WidgetData(
            status="warn" if update else "ok",
            primary={"label": "Live sessions", "value": running},
            secondary=chips,
            metrics={"sessions_running": float(running)},
            meta={"status_reason": "An update of nextrmnl is out." if update else ""},
        )

    @staticmethod
    def _sessions(sessions: list[dict[str, Any]]) -> WidgetData:
        rows = []
        for session in sessions if isinstance(sessions, list) else []:
            connecting = session.get("state") == "connecting"
            rows.append({
                "title": str(session.get("name") or session.get("target") or "?"),
                "subtitle": " · ".join(str(part) for part in (session.get("account"), session.get("target")) if part),
                "value": ago(session.get("started_at")),
                "status": "unknown" if connecting else "ok",
            })
        return WidgetData(status="ok", items=rows, primary={"label": "Live sessions", "value": len(rows)},
                          meta={"empty": "No live session."})

    @staticmethod
    def _history(records: list[dict[str, Any]]) -> WidgetData:
        rows = []
        for record in records if isinstance(records, list) else []:
            status, word = ENDS.get(str(record.get("end") or ""), ("unknown", ""))
            detail = str(record.get("detail") or "") if status != "ok" else ""
            rows.append({
                "title": str(record.get("name") or record.get("target") or "?"),
                "subtitle": " · ".join(part for part in (word, str(record.get("account") or ""), detail) if part),
                "value": ago(record.get("started_at")),
                "status": status,
            })
        hostkey = any(record.get("end") == "hostkey" for record in records if isinstance(record, dict)) if isinstance(records, list) else False
        return WidgetData(
            status="bad" if hostkey else "ok",
            items=rows,
            meta={"empty": "No session yet.", "status_reason": "A server answered with another host key than before." if hostkey else ""},
        )

    @staticmethod
    def _connections(connections: list[dict[str, Any]], only_down: bool) -> WidgetData:
        rows = []
        down = 0
        for connection in connections if isinstance(connections, list) else []:
            reach = str(connection.get("reach") or "unknown")
            status = {"up": "ok", "down": "bad"}.get(reach, "unknown")
            down += status == "bad"
            if only_down and status != "bad":
                continue
            latency = connection.get("latency_ms")
            rows.append({
                "title": str(connection.get("name") or "?"),
                "subtitle": " · ".join(str(part) for part in (connection.get("group"), connection.get("target")) if part),
                "value": f"{latency} ms" if status == "ok" and latency is not None else "",
                "status": status,
            })
        return WidgetData(status="bad" if down else "ok", items=rows, primary={"label": "Down", "value": down},
                          meta={"empty": "Every connection answers." if only_down else "No connection yet."})

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        import time

        now = time.time()

        def stamp(seconds_ago: float) -> str:
            return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - seconds_ago))

        if widget_kind == "status":
            return self._status({"version": "0.3.0", "sessions_running": 2, "sessions_today": 9, "failed_today": 1,
                                 "connections": 14, "update_available": False})
        if widget_kind == "sessions":
            return self._sessions([
                {"account": "admin", "name": "nas", "target": "root@192.0.2.10:22", "started_at": stamp(1800), "state": "open"},
                {"account": "alex", "name": "pve", "target": "root@192.0.2.20:22", "started_at": stamp(240), "state": "open"},
            ])
        if widget_kind == "history":
            return self._history([
                {"account": "alex", "name": "pve", "target": "root@192.0.2.20:22", "started_at": stamp(240), "end": "running"},
                {"account": "admin", "name": "router", "target": "admin@192.0.2.1:22", "started_at": stamp(5400), "end": "hostkey",
                 "detail": "The host key changed."},
                {"account": "admin", "name": "nas", "target": "root@192.0.2.10:22", "started_at": stamp(9000), "end": "normal"},
                {"account": "alex", "name": "backup", "target": "backup@198.51.100.7:22", "started_at": stamp(86000), "end": "failed",
                 "detail": "Authentication failed."},
            ][: _limit(options)])
        if widget_kind == "connections":
            return self._connections([
                {"name": "nas", "group": "Home", "target": "nas.example.com:22", "reach": "up", "latency_ms": 3},
                {"name": "pve", "group": "Home", "target": "pve.example.com:22", "reach": "up", "latency_ms": 2},
                {"name": "backup", "group": "Offsite", "target": "198.51.100.7:22", "reach": "down", "latency_ms": None},
                {"name": "router", "group": "Network", "target": "192.0.2.1:22", "reach": "up", "latency_ms": 1},
            ], bool(options.get("only_down")))
        raise KeyError(widget_kind)


ADAPTER = NextrmnlAdapter()
