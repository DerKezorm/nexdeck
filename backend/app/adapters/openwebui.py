"""Open WebUI: who has an account and who waits for approval, and which models it offers.

Measured against Open WebUI 0.11.3 on 11.09.2026, with an Ollama 0.34.0 as its
connection, an OpenAI-compatible connection to the same Ollama, an
administrator, a user and a signup waiting for approval.

⚠️ API keys are off unless switched on (``ENABLE_API_KEYS`` defaults to
False). With them off a key gets 403 "Use of API key is not enabled in the
environment." An administrator may then create a key; a user only with the
permission ``features.api_keys``, and without it gets 403 as well.

⚠️ A made-up key gets 401, and so does a user's key on an address for
administrators. The two differ only in the detail text: "the token is
invalid" against "You do not have permission". No key at all gets 401 "Not
authenticated".

⚠️ Every request with a key marks its owner as active: ``last_active_at``
jumped to the second of a single call. A card polling with an administrator's
key keeps that administrator active for good, so the key's own user is left
out of "Active" and its row shows no time. Open WebUI's own measure of active
is a ``last_active_at`` within the last three minutes.

⚠️ ``/api/models`` merges models of the same id across connections: the
OpenAI-compatible connection to the same Ollama added nothing until it was
given a prefix. ``loaded`` is Ollama's own answer, kept for one second.

⚠️ A user's key sees only the models that user may use, which for a new user
is none.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

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
    human_bytes,
)

#: Open WebUI's own measure of "active": seen within the last three minutes.
ACTIVE_SECONDS = 180
ROLES = {"admin": "Administrator", "user": "User", "pending": "Waiting for approval"}
CONNECTIONS = {"ollama": "Ollama", "openai": "OpenAI"}


def _detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return ""
    return str(payload.get("detail") or "") if isinstance(payload, dict) else ""


def _stamp(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _not_openwebui() -> AdapterError:
    return AdapterError("This address answers, but not the way Open WebUI does.", code="not_openwebui",
                        hint="Check the URL; it is the address of Open WebUI itself.")


class OpenWebUIAdapter(Adapter):
    kind = "openwebui"
    label = "Open WebUI"
    category = "other"
    description = "Who has an account and who waits for approval, and which models Open WebUI offers."
    icon = "open-webui"
    #: Confirmed against a live instance on 2026-09-11.
    beta = False
    docs_url = "https://docs.openwebui.com/reference/api-endpoints"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://open-webui:8080"),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="An administrator's key from Settings > Account > API keys. API keys have to be switched on in the admin settings first."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="users", label="Users",
                   description="Everyone with an account: the ones waiting for approval first, then by when they were last active.",
                   renderer="list", default_size=(3, 3), refresh_seconds=120,
                   options=(Field("limit", "Entries", type="number", default=8),)),
        WidgetType(kind="models", label="Models",
                   description="The models Open WebUI offers and their connection; the ones Ollama has loaded come first.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300,
                   options=(Field("limit", "Entries", type="number", default=10),)),
        WidgetType(kind="summary", label="Accounts",
                   description="How many accounts there are, how many were active in the last three minutes, and how many wait for approval.",
                   renderer="value", default_size=(3, 2), refresh_seconds=120, metrics=("users", "active")),
    )

    async def _json(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 30) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}{path}", headers={"Authorization": f"Bearer {config.get('api_key') or ''}"},
            params=params, verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        if response.status_code in (401, 403):
            detail = _detail(response)
            if "not enabled" in detail:
                raise AuthFailed("API keys are switched off in Open WebUI. An administrator switches them on in the admin settings.")
            if "permission" in detail:
                raise AuthFailed("Open WebUI refused: this card needs the API key of an administrator.")
            raise AuthFailed("Open WebUI rejected the API key.")
        if response.status_code >= 400:
            raise AdapterError(f"Open WebUI answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of Open WebUI itself, without /api.")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Open WebUI did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a sign-in page or a reverse proxy.") from error

    async def _me(self, config: dict[str, Any], ctx: Context, cache: float = 600) -> dict[str, Any]:
        me = await self._json(config, ctx, "/api/v1/auths/", cache=cache)
        if not isinstance(me, dict) or "role" not in me:
            raise _not_openwebui()
        return me

    async def _recent(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        """The first page of accounts, the most recently active first (thirty per page)."""
        page = await self._json(config, ctx, "/api/v1/users/", {"order_by": "last_active_at", "direction": "desc", "page": 1})
        if not isinstance(page, dict) or not isinstance(page.get("users"), list):
            raise _not_openwebui()
        return [one for one in page["users"] if isinstance(one, dict)]

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        version = await self._json(config, ctx, "/api/version", cache=0)
        if not isinstance(version, dict) or "version" not in version:
            raise _not_openwebui()
        me = await self._me(config, ctx, cache=0)
        if me.get("role") != "admin":
            return f"Open WebUI {version['version']} answers, but this key is not an administrator's: only the models card works with it."
        return f"Open WebUI {version['version']} answers for {me.get('name') or '?'}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        now = time.time()
        if widget_kind == "models":
            payload = await self._json(config, ctx, "/api/models", cache=60)
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise _not_openwebui()
            return self._models(payload["data"], options)
        me = await self._me(config, ctx)
        recent = await self._recent(config, ctx)
        own = str(me.get("id") or "")
        if widget_kind == "users":
            return self._users(recent, own, options, now)
        everyone = await self._json(config, ctx, "/api/v1/users/all")
        if not isinstance(everyone, dict) or not isinstance(everyone.get("users"), list):
            raise _not_openwebui()
        return self._summary(everyone, recent, own, now)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _users(users: list[dict[str, Any]], own: str, options: dict[str, Any], now: float) -> WidgetData:
        ordered = sorted(users, key=lambda one: (one.get("role") != "pending", -(_stamp(one.get("last_active_at")) or 0.0)))
        items = []
        for one in ordered[: max(1, int(options.get("limit") or 8))]:
            role = str(one.get("role") or "")
            mine = bool(own) and str(one.get("id") or "") == own
            items.append({
                "title": str(one.get("name") or one.get("username") or "?"),
                "subtitle": " · ".join(part for part in (ROLES.get(role, role), "Used by this card" if mine else "") if part),
                "status": "warn" if role == "pending" else "ok",
                # The key's own user turns active whenever the card asks, so its time says nothing.
                "value": "" if mine else ago(_stamp(one.get("last_active_at")), now=now),
            })
        pending = sum(1 for one in users if one.get("role") == "pending")
        return WidgetData(
            status="warn" if pending else "ok",
            items=items,
            secondary=[{"label": "Pending", "value": pending}] if pending else [],
            meta={"empty": "No accounts yet."},
        )

    @staticmethod
    def _models(models: list[Any], options: dict[str, Any]) -> WidgetData:
        # The arena is a way of comparing models side by side, not a model of its own.
        offered = [one for one in models if isinstance(one, dict) and not one.get("arena")]
        ordered = sorted(offered, key=lambda one: (not one.get("loaded"), str(one.get("name") or one.get("id") or "").lower()))
        items = []
        for one in ordered[: max(1, int(options.get("limit") or 10))]:
            ollama = one.get("ollama") if isinstance(one.get("ollama"), dict) else {}
            details = ollama.get("details") if isinstance(ollama.get("details"), dict) else {}
            owner = str(one.get("owned_by") or "")
            size = _stamp(ollama.get("size"))
            items.append({
                "title": str(one.get("name") or one.get("id") or "?"),
                "subtitle": " · ".join(part for part in ("Loaded" if one.get("loaded") else "", CONNECTIONS.get(owner, owner),
                                                          str(details.get("parameter_size") or "")) if part),
                "status": "ok" if one.get("loaded") else "unknown",
                "value": human_bytes(size) if size else "",
            })
        return WidgetData(
            status="ok",
            items=items,
            secondary=[{"label": "Loaded", "value": sum(1 for one in offered if one.get("loaded"))}],
            meta={"empty": "No models. A user's key sees only the models that user may use."},
        )

    @staticmethod
    def _summary(everyone: dict[str, Any], recent: list[dict[str, Any]], own: str, now: float) -> WidgetData:
        accounts = [one for one in everyone.get("users") or [] if isinstance(one, dict)]
        total = int(everyone.get("total") or len(accounts))
        pending = sum(1 for one in accounts if one.get("role") == "pending")
        active = sum(1 for one in recent
                     if not (own and str(one.get("id") or "") == own) and (_stamp(one.get("last_active_at")) or 0.0) >= now - ACTIVE_SECONDS)
        return WidgetData(
            status="warn" if pending else "ok",
            primary={"label": "Users", "value": total},
            secondary=[{"label": "Active", "value": active}, {"label": "Pending", "value": pending}],
            metrics={"users": float(total), "active": float(active)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = time.time()
        users = [
            {"id": "u1", "name": "Admin", "role": "admin", "last_active_at": now - 5},
            {"id": "u2", "name": "Robin Example", "role": "user", "last_active_at": now - 60 - tick % 7 * 30},
            {"id": "u3", "name": "Alex Example", "role": "user", "last_active_at": now - 3 * 3600},
            {"id": "u4", "name": "Kim Example", "role": "user", "last_active_at": now - 2 * 86400},
        ]
        if tick % 3 == 0:
            users.append({"id": "u5", "name": "Sam Example", "role": "pending", "last_active_at": now - 600})
        if widget_kind == "users":
            return self._users(users, "u1", options, now)
        if widget_kind == "models":
            return self._models([
                {"id": "llama3.2:3b", "name": "llama3.2:3b", "owned_by": "ollama", "loaded": tick % 4 < 2,
                 "ollama": {"size": 2_019_393_189, "details": {"parameter_size": "3.2B"}}},
                {"id": "qwen2.5-coder:7b", "name": "qwen2.5-coder:7b", "owned_by": "ollama", "loaded": False,
                 "ollama": {"size": 4_683_087_332, "details": {"parameter_size": "7.6B"}}},
                {"id": "remote.gpt-4o-mini", "name": "gpt-4o-mini", "owned_by": "openai"},
                {"id": "arena-model", "name": "Arena Model", "owned_by": "arena", "arena": True},
            ], options)
        return self._summary({"users": users, "total": len(users)}, users, "u1", now)


ADAPTER = OpenWebUIAdapter()
