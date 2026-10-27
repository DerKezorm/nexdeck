"""SFTPGo: who is connected, how full the quotas are, which addresses are banned.

SFTPGo's REST API (``/api/v2``) takes an admin API key in the header
``X-SFTPGO-API-KEY``. Measured against SFTPGo 2.7.6 on 27.10.2026.

* ⚠️ The key only works for an admin that has "Allow API key authentication"
  ticked (``filters.allow_api_key_auth``). Without it every call answers 401
  ``invalid credentials``, which looks exactly like a wrong key.
* ⚠️ The defender watches the web API as well as the protocols. A host that
  fails to sign in a few times is banned, and a banned host is refused
  everywhere with **403** ``your IP address is blocked``, the API included.
  A password sign-in that fails on every refresh would ban nexdeck itself
  within a minute, so this adapter takes an API key only and never tries a
  user name. The 403 is told apart from a missing right.
* ``/api/v2/status`` says whether the defender runs (``defender.is_active``);
  its banned list is only asked for when it does.
* A user's ``quota_size`` of 0 means unlimited. ``used_quota_size`` is absent
  until something was uploaded.
* ``ban_time`` of a banned host is the moment the ban ends, not when it began.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from . import demo as fake
from .base import (
    Action,
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    duration_short,
    human_bytes,
    path_segment,
    percent,
    status_from_percent,
)

#: How many users the quota card reads at most (100 a page).
MAX_USERS = 500


def _wait_left(until: Any, now: float | None = None) -> str:
    """Minutes until a ban ends, as ``"28 min left"``; empty when unreadable."""
    try:
        end = datetime.fromisoformat(str(until).replace("Z", "+00:00")).astimezone(UTC).timestamp()
    except ValueError:
        return ""
    seconds = end - (now if now is not None else time.time())
    return f"{max(1, round(seconds / 60))} min left" if seconds > 0 else ""


class SFTPGoAdapter(Adapter):
    kind = "sftpgo"
    label = "SFTPGo"
    category = "nas"
    description = "Active connections and what they transfer, quotas of the users, and the addresses the defender banned."
    icon = "sftpgo"
    docs_url = "https://docs.sftpgo.com/latest/rest-api/"
    #: Measured against SFTPGo 2.7.6 on 27.10.2026; it stays beta until somebody confirms it on a server in use.
    beta = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://sftpgo:8080",
              help="The address of the web admin and the REST API, not the SFTP port."),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="An admin API key, made under Admins > API keys, in the form id.secret."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    guide = (
        "In SFTPGo's web admin, open your admin account and tick Allow API key authentication. Without it every key is refused.",
        "Under API keys, create a key with the scope Admin for that admin. SFTPGo shows it once.",
        "A banned address is refused by the API as well. If nexdeck is told its address is blocked, add it to the defender's safe list.",
    )
    widgets = (
        WidgetType(
            kind="overview",
            label="Overview",
            description="Active connections, transfers running, users and banned addresses.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=30,
            metrics=("connections", "banned"),
        ),
        WidgetType(
            kind="connections",
            label="Connections",
            description="Who is connected right now, from where, and what they are transferring.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=30,
            options=(Field("limit", "Entries", type="number", default=10),),
        ),
        WidgetType(
            kind="quotas",
            bars=True,
            label="Quotas",
            description="The space each user has used, the fullest first, yellow and red near a quota.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=300,
            options=(Field("limit", "Entries", type="number", default=10),),
        ),
        WidgetType(
            kind="banned",
            label="Banned addresses",
            description="The addresses the defender keeps out for now, with how long the ban lasts.",
            renderer="list",
            default_size=(3, 2),
            refresh_seconds=60,
        ),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 10) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api/v2{path}", params=params,
            headers={"X-SFTPGO-API-KEY": str(config.get("api_key") or ""), "Accept": "application/json"},
            verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        self._check(response)
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("SFTPGo did not answer with JSON.", code="not_json",
                               hint="The URL probably points at another service or at the SFTP port.") from error

    @staticmethod
    def _check(response: Any) -> None:
        if response.status_code == 403 and "blocked" in response.text.lower():
            raise AdapterError("SFTPGo's defender has banned nexdeck's address.", code="blocked_by_defender",
                               hint="Unban the address in SFTPGo and add it to the defender's safe list, so a wrong login "
                                    "elsewhere never locks the dashboard out.")
        if response.status_code in (401, 403):
            raise AuthFailed("SFTPGo refused the API key.")
        if response.status_code >= 400:
            raise AdapterError(f"SFTPGo answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of the web admin, not the SFTP port.")

    async def _users(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        users: list[dict[str, Any]] = []
        while len(users) < MAX_USERS:
            page = await self._get(config, ctx, "/users", {"limit": 100, "offset": len(users)}, cache=60)
            if not isinstance(page, list) or not page:
                break
            users += [one for one in page if isinstance(one, dict)]
            if len(page) < 100:
                break
        return users

    async def _banned(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]] | None:
        """The banned hosts, or ``None`` when the defender is switched off."""
        status = await self._get(config, ctx, "/status", cache=60)
        if not ((status or {}).get("defender") or {}).get("is_active"):
            return None
        hosts = await self._get(config, ctx, "/defender/hosts", cache=10)
        return [one for one in hosts if isinstance(one, dict)] if isinstance(hosts, list) else []

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        version = await self._get(config, ctx, "/version", cache=0)
        return f"SFTPGo {(version or {}).get('version', '?')} answers."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "connections":
            return self._connections(await self._get(config, ctx, "/connections"), options)
        if widget_kind == "quotas":
            return self._quotas(await self._users(config, ctx), options)
        if widget_kind == "banned":
            return self._banned_card(await self._banned(config, ctx))
        connections = await self._get(config, ctx, "/connections")
        users = await self._users(config, ctx)
        return self._overview(connections, users, await self._banned(config, ctx))

    def _overview(self, connections: Any, users: list[dict[str, Any]], banned: list[dict[str, Any]] | None) -> WidgetData:
        rows = [one for one in connections if isinstance(one, dict)] if isinstance(connections, list) else []
        transfers = sum(len(one.get("active_transfers") or []) for one in rows)
        secondary = [
            {"label": "Transfers", "value": transfers},
            {"label": "Users", "value": len(users)},
            {"label": "Banned addresses", "value": len(banned)} if banned is not None else {"label": "Defender", "value": "Off"},
        ]
        return WidgetData(
            status="warn" if banned else "ok",
            primary={"label": "Connections", "value": len(rows)},
            secondary=secondary,
            metrics={"connections": float(len(rows)), **({"banned": float(len(banned))} if banned is not None else {})},
        )

    def _connections(self, connections: Any, options: dict[str, Any], now: float | None = None) -> WidgetData:
        now = now if now is not None else time.time()
        items = []
        for one in connections if isinstance(connections, list) else []:
            if not isinstance(one, dict):
                continue
            transfers = [t for t in one.get("active_transfers") or [] if isinstance(t, dict)]
            moving = " · ".join(f"{'Uploading' if t.get('operation_type') == 'upload' else 'Downloading'} {t.get('path') or '?'}" for t in transfers)
            since = max(0.0, now - float(one.get("connection_time") or 0) / 1000) if one.get("connection_time") else None
            identifier = str(one.get("connection_id") or "")
            items.append({
                "title": str(one.get("username") or "?"),
                "subtitle": " · ".join(part for part in (str(one.get("remote_address") or ""), moving, duration_short(since) if since is not None else "") if part),
                "status": "ok",
                "value": str(one.get("protocol") or ""),
                "actions": [Action(id="disconnect", label="Disconnect", icon="power", confirm=True, params={"id": identifier})] if identifier else [],
            })
        return WidgetData(
            items=items[: int(options.get("limit") or 10)],
            secondary=[{"label": "Connections", "value": len(items)}],
        )

    def _quotas(self, users: list[dict[str, Any]], options: dict[str, Any]) -> WidgetData:
        rows = []
        for user in users:
            used = int(user.get("used_quota_size") or 0)
            ceiling = int(user.get("quota_size") or 0)
            share = percent(used, ceiling) if ceiling > 0 else None
            rows.append({
                "title": str(user.get("username") or "?"),
                "subtitle": " · ".join(part for part in (
                    f"{human_bytes(used)} of {human_bytes(ceiling)}" if ceiling > 0 else human_bytes(used),
                    "Disabled" if user.get("status") == 0 else "") if part),
                "status": status_from_percent(share) if share is not None else "ok",
                "value": used,
            })
        rows.sort(key=lambda row: (-row["value"], row["title"]))
        states = {row["status"] for row in rows}
        return WidgetData(
            status="bad" if "bad" in states else "warn" if "warn" in states else "ok",
            items=rows[: int(options.get("limit") or 10)],
            secondary=[{"label": "Users", "value": len(rows)}],
        )

    def _banned_card(self, banned: list[dict[str, Any]] | None, now: float | None = None) -> WidgetData:
        if banned is None:
            return WidgetData(status="unknown", items=[], secondary=[{"label": "Defender", "value": "Off"}])
        items = []
        for host in banned:
            identifier = str(host.get("id") or "")
            items.append({
                "title": str(host.get("ip") or "?"),
                "subtitle": _wait_left(host.get("ban_time"), now),
                "status": "warn",
                "value": "Banned",
                "actions": [Action(id="unban", label="Unban", icon="shield-check", confirm=True, params={"id": identifier})] if identifier else [],
            })
        return WidgetData(
            status="warn" if items else "ok",
            items=items,
            secondary=[{"label": "Banned addresses", "value": len(items)}],
        )

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        if action_id not in ("disconnect", "unban"):
            raise AdapterError("SFTPGo has no such action.", code="no_such_action")
        identifier = path_segment(params.get("id"), "The connection" if action_id == "disconnect" else "The address")
        path = f"/connections/{identifier}" if action_id == "disconnect" else f"/defender/hosts/{identifier}"
        response = await ctx.request(
            "DELETE", f"{base_url(config)}/api/v2{path}",
            headers={"X-SFTPGO-API-KEY": str(config.get("api_key") or ""), "Accept": "application/json"},
            verify=not config.get("insecure"), auth_errors=False,
        )
        if response.status_code == 404 and action_id == "disconnect":
            raise AdapterError("That connection is already closed.", code="gone")
        self._check(response)
        ctx.forget_answers()
        return "Connection closed." if action_id == "disconnect" else "Address unbanned."

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = time.time()
        moving = fake.flicker("sftpgo-transfer", tick, 0.6)
        connections = [
            {"username": "alice", "connection_id": "SFTP_a1_1", "remote_address": "192.0.2.21:50112", "protocol": "SFTP",
             "connection_time": int((now - 600) * 1000),
             "active_transfers": [{"operation_type": "upload", "path": "/photos/2026/IMG_0412.jpg"}] if moving else []},
            {"username": "bob", "connection_id": "FTP_b2_1", "remote_address": "192.0.2.34:41020", "protocol": "FTP",
             "connection_time": int((now - 90) * 1000), "active_transfers": []},
            {"username": "backup", "connection_id": "DAV_c3_1", "remote_address": "192.0.2.50:38877", "protocol": "DAV",
             "connection_time": int((now - 3300) * 1000),
             "active_transfers": [{"operation_type": "download", "path": "/nightly/db.tar.zst"}]},
        ]
        users = [
            {"username": "alice", "status": 1, "quota_size": 20 * 1024 ** 3, "used_quota_size": int(fake.walk("sftpgo-a", tick, 14.0, 19.4) * 1024 ** 3)},
            {"username": "bob", "status": 1, "quota_size": 5 * 1024 ** 3, "used_quota_size": int(fake.walk("sftpgo-b", tick, 1.0, 2.5) * 1024 ** 3)},
            {"username": "backup", "status": 1, "quota_size": 0, "used_quota_size": 180 * 1024 ** 3},
            {"username": "guest", "status": 0, "quota_size": 1024 ** 3, "used_quota_size": 12 * 1024 ** 2},
        ]
        banned = [{"id": "3139322e302e322e37", "ip": "192.0.2.7", "ban_time": datetime.fromtimestamp(now + 1700, UTC).isoformat()}] \
            if fake.flicker("sftpgo-ban", tick, 0.4) else []
        if widget_kind == "connections":
            return self._connections(connections, options, now)
        if widget_kind == "quotas":
            return self._quotas(users, options)
        if widget_kind == "banned":
            return self._banned_card(banned, now)
        return self._overview(connections, users, banned)


ADAPTER = SFTPGoAdapter()
