"""Keycloak: realms, how many sessions are open, and who fails to sign in.

The admin API (``/admin/realms``) takes a bearer token that a client with a
service account gets from the token endpoint with the client credentials
grant. Measured against Keycloak 26 (``start-dev``) on 27.10.2026, with a
client in the master realm whose service account holds the roles view-realm,
view-users, view-events and view-clients of each realm it should see.

* ⚠️ The token lives **60 seconds**. It is kept per connection and fetched
  again shortly before it ends, never once per card.
* ``GET /admin/realms`` lists only the realms the service account may view;
  ``?briefRepresentation=true`` keeps the answer small. A realm of the list
  that the account may not read further answers 403 on its own calls, which
  turns that realm grey and does not fail the card.
* ``/client-session-stats`` gives ``active`` and ``offline`` per client as
  **strings**. A user signed in to two clients counts twice, so the card says
  sessions per client.
* Failed sign-ins are ``LOGIN_ERROR`` events, and events are **off** unless the
  realm has them switched on (Realm settings > Events); a realm without them
  answers ``[]``, which looks exactly like no failures. ``/events/config``
  says whether they are on, and a realm without them is marked as such.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    ReadCommands,
    WidgetData,
    WidgetType,
    ago,
    base_url,
)

#: How many realms are looked into, and how many calls run at once.
MAX_REALMS = 20
PARALLEL = 4
#: Failed sign-ins in 24 hours from which a realm turns yellow, then red.
WARN_FAILED = 10
BAD_FAILED = 50

ERRORS = {
    "user_not_found": "User not found",
    "invalid_user_credentials": "Wrong password",
    "user_disabled": "User disabled",
    "user_temporarily_disabled": "Temporarily locked",
    "invalid_client_credentials": "Wrong client secret",
    "expired_code": "Expired code",
    "invalid_totp": "Wrong code",
}


def _count(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


class KeycloakAdapter(Adapter):
    kind = "keycloak"
    label = "Keycloak"
    category = "network"
    description = "Realms, open sessions and failed sign-ins of a Keycloak server."
    icon = "keycloak"
    docs_url = "https://www.keycloak.org/docs-api/latest/rest-api/index.html"
    #: Measured against Keycloak 26 on 27.10.2026; it stays beta until somebody confirms it on a server in use.
    beta = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://keycloak.example.com",
              help="The address of Keycloak, with its relative path if it has one, such as /auth."),
        Field("realm", "Realm of the client", default="master", placeholder="master",
              help="The realm the client below lives in. The client's service account is what signs in."),
        Field("client_id", "Client ID", required=True, placeholder="nexdeck"),
        Field("client_secret", "Client secret", type="password", secret=True, required=True,
              help="From the client's Credentials tab. Client authentication and Service accounts roles have to be on."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    guide = (
        "Create a client with Client authentication on and only Service accounts roles ticked as the flow.",
        "On its Service accounts roles tab assign view-realm, view-users, view-events and view-clients of the realm-management client of each realm nexdeck should show. From the master realm one client can reach all of them.",
        "Switch on Events in each realm's settings, or its failed sign-ins stay invisible. Keycloak keeps none by default.",
    )
    # The client-secret of a client is a secret, not a read.
    raw_read_commands = ReadCommands(words=frozenset({"secret"}))
    widgets = (
        WidgetType(
            kind="overview",
            label="Overview",
            description="Open sessions, realms, users and the sign-ins that failed in the last 24 hours.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=120,
            metrics=("sessions", "failed_logins"),
        ),
        WidgetType(
            kind="realms",
            bars=True,
            label="Realms",
            description="Every realm with its users, its open sessions and the failed sign-ins of the last 24 hours.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=300,
        ),
        WidgetType(
            kind="failed",
            label="Failed sign-ins",
            description="The latest sign-ins that failed in the realms that keep events, with the user, the client, the address and the reason.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=120,
            options=(Field("limit", "Entries", type="number", default=8),),
        ),
    )

    async def _token(self, config: dict[str, Any], ctx: Context) -> str:
        held = ctx.cache.get("keycloak.token")
        if held and held[0] > time.monotonic():
            return held[1]
        response = await ctx.request(
            "POST", f"{base_url(config)}/realms/{quote(str(config.get('realm') or 'master'), safe='')}/protocol/openid-connect/token",
            data={"grant_type": "client_credentials", "client_id": str(config.get("client_id") or ""),
                  "client_secret": str(config.get("client_secret") or "")},
            verify=not config.get("insecure"), auth_errors=False,
        )
        if response.status_code in (400, 401):
            try:
                why = str(response.json().get("error_description") or "")
            except ValueError:
                why = ""
            raise AuthFailed("Keycloak refused the client" + (f": {why}." if why else "."))
        if response.status_code >= 400:
            raise AdapterError(f"Keycloak answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL and the realm; Keycloak 17 and newer have no /auth in front unless it was set.")
        try:
            body = response.json()
            token = str(body["access_token"])
        except (ValueError, KeyError, TypeError) as error:
            raise AdapterError("Keycloak did not hand out a token.", code="no_token",
                               hint="The URL probably points at another service.") from error
        # ⚠️ Ten seconds before it ends, so a token is never used on its last breath.
        ctx.cache["keycloak.token"] = (time.monotonic() + max(5, _count(body.get("expires_in")) - 10), token)
        return token

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None,
                   cache: float = 20) -> Any:
        """One admin call; ``None`` for a realm the account may not read (403), so one realm never fails the card."""
        for attempt in range(2):
            token = await self._token(config, ctx)
            response = await ctx.request(
                "GET", f"{base_url(config)}/admin{path}", params=params,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
            )
            if response.status_code == 401 and attempt == 0:
                ctx.cache.pop("keycloak.token", None)
                continue
            break
        if response.status_code == 403:
            return None
        if response.status_code == 401:
            raise AuthFailed("Keycloak refused the token it had just handed out.")
        if response.status_code >= 400:
            raise AdapterError(f"Keycloak answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of Keycloak.")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Keycloak did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a proxy.") from error

    async def _realms(self, config: dict[str, Any], ctx: Context, since: str | None) -> list[dict[str, Any]]:
        """Each realm with users, sessions and failed sign-ins; ``readable`` False where the account may not look."""
        listed = await self._get(config, ctx, "/realms", {"briefRepresentation": "true"}, cache=60)
        if listed is None:
            raise AdapterError("The service account may not list realms.", code="no_rights",
                               hint="Give it view-realm on the realm-management client of each realm.")
        names = [one for one in listed if isinstance(one, dict) and one.get("realm")][:MAX_REALMS]
        gate = asyncio.Semaphore(PARALLEL)

        async def one(realm: dict[str, Any]) -> dict[str, Any]:
            name = quote(str(realm["realm"]), safe="")
            async with gate:
                users = await self._get(config, ctx, f"/realms/{name}/users/count")
                stats = await self._get(config, ctx, f"/realms/{name}/client-session-stats")
                events = await self._get(config, ctx, f"/realms/{name}/events/config")
                failed = None
                keeps = isinstance(events, dict) and events.get("eventsEnabled") and "LOGIN_ERROR" in (events.get("enabledEventTypes") or [])
                if keeps:
                    failed = await self._get(config, ctx, f"/realms/{name}/events",
                                             {"type": "LOGIN_ERROR", "max": 100, **({"dateFrom": since} if since else {})})
            readable = users is not None and stats is not None
            return {
                "name": str(realm["realm"]), "enabled": realm.get("enabled") is not False, "readable": readable,
                "users": _count(users), "sessions": sum(_count(row.get("active")) for row in stats or [] if isinstance(row, dict)),
                "offline": sum(_count(row.get("offline")) for row in stats or [] if isinstance(row, dict)),
                "events": bool(keeps), "failed": [one for one in failed or [] if isinstance(one, dict)] if keeps else [],
            }

        return list(await asyncio.gather(*(one(realm) for realm in names)))

    @staticmethod
    def _yesterday() -> str:
        return (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        listed = await self._get(config, ctx, "/realms", {"briefRepresentation": "true"}, cache=0)
        if listed is None:
            raise AdapterError("The service account may not list realms.", code="no_rights",
                               hint="Give it view-realm on the realm-management client of each realm.")
        return f"Keycloak answers, {len(listed)} realm(s)."

    async def running_version(self, config: dict[str, Any], ctx: Context) -> str | None:
        # /admin/serverinfo answers a service account without its systemInfo part (measured), so the version is not known.
        info = await self._get(config, ctx, "/serverinfo", cache=300)
        version = ((info or {}).get("systemInfo") or {}).get("version") if isinstance(info, dict) else None
        return str(version) if version else None

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        realms = await self._realms(config, ctx, self._yesterday())
        if widget_kind == "failed":
            return self._failed(realms, options)
        if widget_kind == "realms":
            return self._realm_list(realms)
        return self._overview(realms)

    def _failures(self, realm: dict[str, Any], now: float | None = None) -> int:
        """Failed sign-ins within the last 24 hours (Keycloak's dateFrom is by day, so the cut is made here)."""
        limit = ((now if now is not None else time.time()) - 86400) * 1000
        return sum(1 for event in realm["failed"] if float(event.get("time") or 0) >= limit)

    def _overview(self, realms: list[dict[str, Any]], now: float | None = None) -> WidgetData:
        readable = [one for one in realms if one["readable"]]
        sessions = sum(one["sessions"] for one in readable)
        failed = sum(self._failures(one, now) for one in readable)
        keeping = [one for one in readable if one["events"]]
        secondary = [
            {"label": "Realms", "value": len(realms)},
            {"label": "Users", "value": sum(one["users"] for one in readable)},
            {"label": "Failed sign-ins in 24 h", "value": failed} if keeping else {"label": "Events", "value": "Off"},
        ]
        return WidgetData(
            status="bad" if failed >= BAD_FAILED else "warn" if failed >= WARN_FAILED or any(not one["enabled"] for one in realms) else "ok",
            primary={"label": "Sessions", "value": sessions},
            secondary=secondary,
            metrics={"sessions": float(sessions), **({"failed_logins": float(failed)} if keeping else {})},
        )

    def _realm_list(self, realms: list[dict[str, Any]], now: float | None = None) -> WidgetData:
        items = []
        for realm in realms:
            failed = self._failures(realm, now)
            parts = [f"{realm['users']} users" if realm["readable"] else "No access",
                     f"{failed} failed" if realm["events"] and failed else "" if realm["events"] or not realm["readable"] else "Events off"]
            items.append({
                "title": realm["name"],
                "subtitle": " · ".join(part for part in parts if part),
                "status": "bad" if failed >= BAD_FAILED else "warn" if failed >= WARN_FAILED or not realm["enabled"] else "unknown" if not realm["readable"] else "ok",
                "value": realm["sessions"],
            })
        order = {"bad": 0, "warn": 1, "ok": 2, "unknown": 3}
        items.sort(key=lambda row: (order[row["status"]], -row["value"], row["title"]))
        states = {row["status"] for row in items}
        return WidgetData(
            status="bad" if "bad" in states else "warn" if "warn" in states else "ok",
            items=items,
            secondary=[{"label": "Realms", "value": len(items)}],
        )

    def _failed(self, realms: list[dict[str, Any]], options: dict[str, Any], now: float | None = None) -> WidgetData:
        events = [(one["name"], event) for one in realms for event in one["failed"]]
        events.sort(key=lambda pair: -float(pair[1].get("time") or 0))
        items = []
        for realm, event in events[: int(options.get("limit") or 8)]:
            details = event.get("details") if isinstance(event.get("details"), dict) else {}
            code = str(event.get("error") or "")
            items.append({
                "title": str(details.get("username") or "Unknown user"),
                "subtitle": " · ".join(part for part in (
                    realm, str(event.get("clientId") or ""), str(event.get("ipAddress") or ""),
                    f"{ago(float(event['time']) / 1000, now)} ago" if event.get("time") else "") if part),
                "status": "warn",
                "value": ERRORS.get(code, code.replace("_", " ").capitalize() or "Failed"),
            })
        keeping = [one for one in realms if one["events"]]
        return WidgetData(
            status="warn" if items else "ok" if keeping else "unknown",
            items=items,
            secondary=[{"label": "Realms with events", "value": len(keeping)}],
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = time.time()
        burst = fake.flicker("keycloak-failed", tick, 0.4)
        failed = [{"time": (now - 60 * (n + 1)) * 1000, "clientId": "app", "ipAddress": "192.0.2.50", "error": "invalid_user_credentials",
                   "details": {"username": "carol"}} for n in range(14 if burst else 3)]
        realms = [
            {"name": "home", "enabled": True, "readable": True, "users": 6, "sessions": int(fake.walk("keycloak-s1", tick, 3, 14)),
             "offline": 0, "events": True, "failed": failed},
            {"name": "work", "enabled": True, "readable": True, "users": 41, "sessions": int(fake.walk("keycloak-s2", tick, 12, 38)),
             "offline": 4, "events": True, "failed": []},
            {"name": "lab", "enabled": True, "readable": True, "users": 2, "sessions": 0, "offline": 0, "events": False, "failed": []},
        ]
        if widget_kind == "failed":
            return self._failed(realms, options, now)
        if widget_kind == "realms":
            return self._realm_list(realms, now)
        return self._overview(realms, now)


ADAPTER = KeycloakAdapter()
