"""Pocket ID: who signed in lately, and how many users there are.

Measured against Pocket ID 2.14.0 on 11.09.2026, with the static key of the
container, three users (an administrator, a user, a disabled user) and sign-ins
made with one-time login codes, the only kind that works without a browser.

⚠️ The key goes as ``X-API-KEY``. None, a made-up one and a bearer token all
get 401 ``{"code": "not_signed_in"}``. A key of a user who is not an
administrator gets 403 ``{"code": "forbidden"}`` for ``/api/users`` and
``/api/audit-logs/all``; both cards need an administrator's key.

⚠️ No key makes another key: ``POST /api/api-keys`` with an API key gets 403
``api_key_auth_not_allowed``. A key comes from a signed-in session. Without a
browser that is a one-time login code, made by an administrator's key with
``POST /api/users/<id>/one-time-access-token`` or on the container with
``pocket-id one-time-access-token <user>``, and exchanged at
``POST /api/one-time-access-token/<code>`` for an ``access_token`` cookie.
``STATIC_API_KEY`` in the environment is the other way: it acts as an
administrator called "Static API User", who then stands in the user list.

⚠️ A failed attempt leaves no trace. A wrong code, a code of the wrong length
and a code used twice all get 401 ``token_invalid_or_expired``, and the audit
log gained nothing; its events in this version know no failed sign-in at all.
So the cards show sign-ins, not attempts.

⚠️ ``filters[event]`` narrows the audit log; a filter on a field it does not
know is ignored without a word. A sign-in from inside the network has
``country: "Internal Network"`` and ``city: "LAN"``. Pages hold at most 100.

⚠️ An address that is not the API, such as ``/openapi.json``, answers 200 with
the web interface's page; paths under ``/api`` that do not exist get 404 JSON.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from .base import (
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
    ago,
    base_url,
)

#: The sign-in events of the audit log, with the word the card shows.
SIGN_IN_EVENTS = {"SIGN_IN": "Passkey", "TOKEN_SIGN_IN": "Login code", "REMOTE_SIGN_IN": "Other device"}
#: The administrator STATIC_API_KEY makes; not a person.
STATIC_USER_ID = "00000000-0000-0000-0000-000000000000"


def _seconds(raw: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _people(users: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [one for one in users if one.get("id") != STATIC_USER_ID and not str(one.get("username") or "").startswith("static-api-user-")]


class PocketIdAdapter(Adapter):
    kind = "pocketid"
    label = "Pocket ID"
    category = "network"
    description = "Who signed in lately and how, and how many users, administrators and disabled accounts there are."
    icon = "pocket-id"
    #: Confirmed against a live instance on 2026-09-11.
    beta = False
    docs_url = "https://pocket-id.org/docs/api"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://pocket-id:1411"),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="An administrator's key from Settings > API keys, or the STATIC_API_KEY of the container. A key of a user who is not an administrator is refused."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="signins", label="Recent sign-ins", description="Who signed in, how and from where, the newest first.",
                   renderer="list", default_size=(3, 3), refresh_seconds=120,
                   options=(Field("limit", "Entries", type="number", default=10),)),
        WidgetType(kind="summary", label="Users", description="How many users there are, how many of them are administrators, and how many are disabled.",
                   renderer="value", default_size=(3, 2), refresh_seconds=600, metrics=("users",)),
    )

    async def _json(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 30) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api{path}", headers={"X-API-KEY": str(config.get("api_key") or "")},
            params=params, verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        if response.status_code == 401:
            raise AuthFailed("Pocket ID rejected the API key.")
        if response.status_code == 403:
            raise AuthFailed("Pocket ID refused: this key does not belong to an administrator.")
        if response.status_code >= 400:
            raise AdapterError(f"Pocket ID answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of Pocket ID itself, without /api.")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Pocket ID did not answer with JSON.", code="not_json",
                               hint="The URL probably points at the web interface under another path, or at something else.") from error

    async def _page(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any], cache: float = 30) -> dict[str, Any]:
        answer = await self._json(config, ctx, path, params, cache)
        if not isinstance(answer, dict) or not isinstance(answer.get("data"), list):
            raise AdapterError("This address answers, but not the way Pocket ID does.", code="not_pocketid")
        return answer

    async def _users(self, config: dict[str, Any], ctx: Context, cache: float = 300) -> list[dict[str, Any]]:
        page = await self._page(config, ctx, "/users", {"pagination[limit]": 100}, cache)
        return [one for one in page["data"] if isinstance(one, dict)]

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        version = await self._json(config, ctx, "/version/current", cache=0)
        users = await self._users(config, ctx, cache=0)
        number = (version or {}).get("currentVersion", "?") if isinstance(version, dict) else "?"
        return f"Pocket ID {number} answers with {len(_people(users))} users."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "summary":
            return self._summary(await self._users(config, ctx))
        limit = max(1, min(100, int(options.get("limit") or 10)))
        params: dict[str, Any] = {"sort[column]": "createdAt", "sort[direction]": "desc", "pagination[limit]": limit}
        for index, event in enumerate(SIGN_IN_EVENTS):
            params[f"filters[event][{index}]"] = event
        page = await self._page(config, ctx, "/audit-logs/all", params, cache=30)
        return self._signins(page, time.time())

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _signins(page: dict[str, Any], now: float) -> WidgetData:
        # ⚠️ Filtered here as well: a Pocket ID that ignored the filter would hand out every event.
        entries = [one for one in page.get("data") or [] if isinstance(one, dict) and one.get("event") in SIGN_IN_EVENTS]
        entries.sort(key=lambda one: -(_seconds(one.get("createdAt")) or 0))
        items = []
        for entry in entries:
            country = str(entry.get("country") or "")
            place = "Internal network" if country == "Internal Network" else ", ".join(
                piece for piece in (str(entry.get("city") or ""), country) if piece and piece != "unknown")
            device = str(entry.get("device") or "").strip().removesuffix(" on").strip()
            items.append({
                "title": str(entry.get("username") or "?"),
                "subtitle": " · ".join(piece for piece in (SIGN_IN_EVENTS[entry["event"]], place, device) if piece),
                "status": "ok",
                "value": ago(_seconds(entry.get("createdAt")), now=now),
            })
        total = (page.get("pagination") or {}).get("totalItems") if isinstance(page.get("pagination"), dict) else None
        return WidgetData(
            status="ok",
            items=items,
            secondary=[{"label": "Sign-ins", "value": int(total)}] if isinstance(total, int) else [],
            meta={"empty": "Nobody has signed in yet."},
        )

    @staticmethod
    def _summary(users: list[dict[str, Any]]) -> WidgetData:
        people = _people(users)
        admins = sum(1 for one in people if one.get("isAdmin") is True)
        disabled = sum(1 for one in people if one.get("disabled") is True)
        return WidgetData(
            status="ok",
            primary={"label": "Users", "value": len(people)},
            secondary=[{"label": "Administrators", "value": admins}, {"label": "Disabled", "value": disabled}],
            metrics={"users": float(len(people))},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = time.time()
        if widget_kind == "summary":
            users = [{"id": f"u{index}", "username": name, "isAdmin": index == 0, "disabled": name == "guest"}
                     for index, name in enumerate(("admin", "kim", "sam", "guest", "robin"))]
            if tick % 3 == 0:
                users.append({"id": "u9", "username": "new-member", "isAdmin": False, "disabled": False})
            return self._summary(users)

        def at(minutes: float) -> str:
            return datetime.fromtimestamp(now - minutes * 60).astimezone().isoformat()

        data = [
            {"event": "SIGN_IN", "username": "kim", "country": "Internal Network", "city": "LAN", "device": "Firefox on Linux", "createdAt": at(4 + tick % 5)},
            {"event": "REMOTE_SIGN_IN", "username": "sam", "country": "Germany", "city": "Berlin", "device": "Safari on iOS", "createdAt": at(95)},
            {"event": "TOKEN_SIGN_IN", "username": "robin", "country": "Internal Network", "city": "LAN", "device": "Chrome on Windows", "createdAt": at(600)},
        ]
        return self._signins({"data": data[: int(options.get("limit") or 10)], "pagination": {"totalItems": 41 + tick % 4}}, now)


ADAPTER = PocketIdAdapter()
