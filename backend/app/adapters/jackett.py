"""Jackett: the indexers it has set up and the ones that fail.

Measured on 27.10.2026 against lscr.io/linuxserver/jackett (Jackett
v0.24.2934) with two public indexers set up, one of them failing on a
certificate, with and without an administrator password.

⚠️ The API key does not read the list of indexers. ``/api/v2.0/indexers`` and
``/api/v2.0/server/config`` answer **302 to /UI/Login** for a request that
carries only ``?apikey=``; the key is for the Torznab search addresses. The
web interface's own session cookie (``Jackett``) is what opens them, and that
is what this adapter signs in for, so it asks for no API key at all.

⚠️ The sign-in is the same with and without a password: ``POST /UI/Dashboard``
with ``password=`` (empty when none is set) answers 302 to ``Dashboard`` and,
**only when it was accepted**, sets the ``Jackett`` cookie. A wrong password
answers the very same 302 without the cookie, so the cookie decides. A
cookie from before a password was set stays valid.

⚠️ ``/api/v2.0/server/config`` hands out the API key and the administrator
password along with the version. Only ``app_version`` is read here, and
nothing from it is kept.

⚠️ An indexer that broke keeps its message in ``last_error`` until the next
good search; the text is the exception with its whole stack of detail, so the
first line is what a card shows. ``POST /api/v2.0/indexers/<id>/test`` answers
**204** when it works and **500** with ``{"result": "error", "error": ...}``
when it does not.
"""

from __future__ import annotations

from typing import Any

import httpx

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    Unreachable,
    WidgetData,
    WidgetType,
    base_url,
    outbound_client,
    path_segment,
)

COOKIE = "Jackett"
KINDS = {"public": "Public", "private": "Private", "semi-private": "Semi-private"}


def _first_line(text: Any, size: int = 140) -> str:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    return lines[0][:size] if lines else ""


class JackettAdapter(Adapter):
    kind = "jackett"
    label = "Jackett"
    category = "downloads"
    description = "The indexers Jackett has set up, which of them fail and why, and a test for each."
    icon = "jackett"
    docs_url = "https://github.com/Jackett/Jackett#supported-systems"
    #: Measured against Jackett v0.24.2934 in a container with two public indexers.
    beta = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://jackett:9117"),
        Field("password", "Admin password", type="password", secret=True,
              help="Only when you set one under Jackett's Admin password. Leave it empty otherwise."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="overview",
            label="Jackett overview",
            description="Indexers set up, how many fail, and how many are public or private.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=120,
            metrics=("indexers", "failing"),
        ),
        WidgetType(
            kind="indexers",
            label="Indexers",
            description="Every indexer set up, failing ones first with the reason, each with a test button.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=120,
            metrics=("failing",),
            options=(
                Field("limit", "Entries", type="number", default=12),
                Field("only_failing", "Only the failing ones", type="bool", default=False),
            ),
        ),
    )

    # -- the session ---------------------------------------------------------

    def _client(self, config: dict[str, Any], ctx: Context) -> httpx.AsyncClient:
        client = ctx.cache.get("jackett_client")
        if client is None or client.is_closed:
            # One client per connection: it keeps the cookie the sign-in sets.
            client = outbound_client(base_url=base_url(config), verify=not config.get("insecure"), timeout=15, keep_cookies=True)
            ctx.cache["jackett_client"] = client
        return client

    async def _sign_in(self, config: dict[str, Any], ctx: Context) -> None:
        client = self._client(config, ctx)
        try:
            await client.post("/UI/Dashboard", data={"password": str(config.get("password") or "")})
        except httpx.TimeoutException as error:
            raise Unreachable("Jackett did not answer in time.") from error
        except httpx.HTTPError as error:
            raise Unreachable(f"Jackett could not be reached: {error.__class__.__name__}.") from error
        if not any(cookie.name == COOKIE for cookie in client.cookies.jar):
            raise AuthFailed("Jackett rejected the admin password." if config.get("password") else "Jackett wants its admin password.")

    async def _call(self, config: dict[str, Any], ctx: Context, method: str, path: str, retry: bool = True) -> httpx.Response:
        client = self._client(config, ctx)
        try:
            response = await client.request(method, path)
        except httpx.TimeoutException as error:
            raise Unreachable("Jackett did not answer in time.") from error
        except httpx.HTTPError as error:
            raise Unreachable(f"Jackett could not be reached: {error.__class__.__name__}.") from error
        # Not signed in, or the cookie ran out: the interface's own redirect to its login page.
        if response.status_code in (301, 302, 303, 307) and "/UI/Login" in str(response.headers.get("location", "")):
            if not retry:
                raise AuthFailed("Jackett did not accept the sign-in.")
            await self._sign_in(config, ctx)
            return await self._call(config, ctx, method, path, retry=False)
        return response

    async def _json(self, config: dict[str, Any], ctx: Context, path: str) -> Any:
        response = await self._call(config, ctx, "GET", path)
        if response.status_code == 404:
            raise AdapterError("This address answers, but not the way Jackett does.", code="not_jackett",
                               hint="Use the address of the Jackett web interface, usually port 9117.")
        if response.status_code >= 400:
            raise AdapterError(f"Jackett answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Jackett did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than Jackett.") from error

    async def _indexers(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        answer = await self._json(config, ctx, "/api/v2.0/indexers?configured=true")
        if not isinstance(answer, list):
            raise AdapterError("This address answers, but not the way Jackett does.", code="not_jackett")
        return [one for one in answer if isinstance(one, dict)]

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        server = await self._json(config, ctx, "/api/v2.0/server/config")
        version = str(server.get("app_version") or "").lstrip("v") if isinstance(server, dict) else ""
        indexers = await self._indexers(config, ctx)
        return f"Jackett {version} answers, {len(indexers)} indexers set up." if version else f"Jackett answers, {len(indexers)} indexers set up."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        indexers = await self._indexers(config, ctx)
        if widget_kind == "indexers":
            return self.indexers_card(indexers, options, base_url(config))
        return self.overview_card(indexers, base_url(config))

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def overview_card(indexers: list[dict[str, Any]], link: str | None = None) -> WidgetData:
        failing = sum(1 for one in indexers if one.get("last_error"))
        public = sum(1 for one in indexers if one.get("type") == "public")
        return WidgetData(
            status="warn" if failing else "ok",
            primary={"label": "Indexers", "value": len(indexers)},
            secondary=[
                {"label": "Failing", "value": failing},
                {"label": "Public", "value": public},
                {"label": "Private", "value": len(indexers) - public},
            ],
            metrics={"indexers": float(len(indexers)), "failing": float(failing)},
            link=link,
        )

    @staticmethod
    def indexers_card(indexers: list[dict[str, Any]], options: dict[str, Any], link: str | None = None) -> WidgetData:
        failing = [one for one in indexers if one.get("last_error")]
        shown = failing if options.get("only_failing") else indexers
        shown = sorted(shown, key=lambda one: (0 if one.get("last_error") else 1, str(one.get("name") or "").casefold()))
        items = []
        for one in shown[: max(1, min(100, int(options.get("limit") or 12)))]:
            broken = bool(one.get("last_error"))
            identifier = str(one.get("id") or "")
            items.append({
                "title": str(one.get("name") or identifier or "?"),
                "subtitle": _first_line(one.get("last_error")) if broken else KINDS.get(str(one.get("type") or ""), str(one.get("type") or "")),
                "value": "Failing" if broken else "Works",
                "status": "bad" if broken else "ok",
                "actions": [{"id": "test", "label": "Test", "icon": "refresh-cw", "params": {"id": identifier}}] if identifier else [],
            })
        return WidgetData(
            status="warn" if failing else "ok",
            items=items,
            secondary=[{"label": "Failing", "value": len(failing)}, {"label": "Indexers", "value": len(indexers)}],
            metrics={"failing": float(len(failing))},
            link=link,
            meta={"empty": "No indexer is set up." if not indexers else "No indexer fails."},
        )

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        if action_id != "test":
            raise AdapterError("Unknown action.", code="no_such_action")
        identifier = path_segment(params.get("id"), "The indexer")
        response = await self._call(config, ctx, "POST", f"/api/v2.0/indexers/{identifier}/test")
        ctx.forget_answers()
        if response.status_code < 300:
            return f"{identifier} answers."
        try:
            reason = _first_line(response.json().get("error"))
        except (ValueError, AttributeError):
            reason = ""
        raise AdapterError(reason or f"Jackett answered with HTTP {response.status_code}.", code="indexer_failed",
                           hint="The indexer itself did not answer the test search; Jackett's log has the details.")

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        broke = fake.flicker("jackett-broken", tick, 0.3)
        indexers = [
            {"id": "tracker-one", "name": "Tracker One", "type": "public", "last_error": ""},
            {"id": "tracker-two", "name": "Tracker Two", "type": "public", "last_error": ""},
            {"id": "members-only", "name": "Members Only", "type": "private", "last_error": ""},
            {"id": "film-index", "name": "Film Index", "type": "semi-private",
             "last_error": "Exception (film-index): The operation has timed out." if broke else ""},
            {"id": "old-mirror", "name": "Old Mirror", "type": "public",
             "last_error": "Exception (old-mirror): Cloudflare protection detected."},
        ]
        if widget_kind == "indexers":
            return self.indexers_card(indexers, options)
        return self.overview_card(indexers)


ADAPTER: Adapter = JackettAdapter()
