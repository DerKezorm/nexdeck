"""Piwigo: how many photos and albums a gallery holds, what each album holds, and who comes to see it.

Piwigo answers on ``/ws.php`` with the method in the address (``?format=json&method=pwg.categories.getList``) and an
envelope around everything: ``{"stat": "ok", "result": ...}``, or ``{"stat": "fail", "err": 401, "message": ...}`` with
the HTTP status set to the error when it lies between 400 and 599 (``PwgError`` in ``include/ws_core.inc.php``).

The key comes from the profile of a user (Piwigo 16 and newer) and rides in ``X-PIWIGO-API`` as ``<id>:<secret>``; 16.0.0
read it from ``Authorization``, 16.1 moved it (Piwigo issue #2460). A key carries the rights of the user who made it.
Without a key Piwigo answers as a visitor, and the albums a visitor may see are all a card counts.

⚠️ ``pwg.getInfos`` and ``pwg.users.getList`` are for administrators only (``admin_only`` in ``ws.php``). The gallery card
asks the first and counts the visible albums itself when Piwigo refuses it; the users card has nothing to fall back on.
Built from the code of Piwigo master (09.11.2026), not run against a gallery, hence beta.
"""

from __future__ import annotations

import html
import re
from typing import Any

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
    allowed,
    base_url,
)

#: The methods a custom card may ask: the ones that read and hand out nothing that signs in. ``pwg.session.getStatus``
#: hands out the ``pwg_token`` of the session, ``pwg.users.getAuthKey`` a key that signs a user in.
READS = (
    "pwg.getInfos", "pwg.getVersion", "pwg.categories.getList", "pwg.categories.getImages", "pwg.images.getInfo",
    "pwg.images.search", "pwg.tags.getList", "pwg.tags.getImages", "pwg.users.getList", "pwg.groups.getList",
)

ALBUMS_SHOWN = (("top", "Top-level albums"), ("all", "All albums"))
ALBUMS_ORDER = (("photos", "Most photos first"), ("recent", "Newest photo first"), ("name", "By name"))

#: The statuses of a Piwigo user, in Piwigo's own words.
STATUS = {"webmaster": "Webmaster", "admin": "Administrator", "normal": "User", "generic": "Generic"}

TAG = re.compile(r"<[^>]*>")


def _number(value: Any) -> int:
    """Piwigo counts as numbers, or as strings of digits from the database; anything else is nothing."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _name(value: Any) -> str:
    """An album's name as Piwigo renders it, without its markup: names may carry HTML and entities."""
    return html.unescape(TAG.sub("", str(value or ""))).strip()


def _day(moment: Any) -> str:
    """The day of a moment Piwigo writes as ``2026-11-09 17:55:04``, in the server's time without a zone.

    ⚠️ The day only: the hour belongs to a zone Piwigo does not name, and an age worked out from it would be wrong by it.
    """
    text = str(moment or "")
    return text[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", text) and not text.startswith("0000") else ""


class PiwigoAdapter(Adapter):
    kind = "piwigo"
    beta = True
    label = "Piwigo"
    category = "media"
    description = "Photos and albums of a Piwigo gallery, and who visits it."
    icon = "piwigo"
    docs_url = "https://github.com/Piwigo/Piwigo/wiki/Piwigo-Web-API"
    keywords = ("photo gallery",)
    raw_read_commands = ReadCommands(params={"method": allowed(*READS), "format": allowed("json")})
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://piwigo.local",
              help="The address of the gallery, where ws.php lies."),
        Field("key_id", "API key ID", type="password", secret=True, placeholder="pkid-20260109-a1b2c3d4e5f6a7b8c9d0",
              help="Profile > API Keys, Piwigo 16.1 or newer. Without a key only public albums are counted."),
        Field("key_secret", "Secret", type="password", secret=True,
              help="Shown once, when the key is made. Users and the figures of the whole gallery need the key of an administrator."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="library",
            label="Gallery",
            description="Photos and albums, with users, tags and comments for an administrator's key.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=300,
            metrics=("photos", "albums"),
        ),
        WidgetType(
            kind="albums",
            bars=True,
            label="Albums",
            description="How many photos each album holds, its sub-albums included.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=300,
            options=(
                Field("shown", "Albums", type="select", default="top", options=ALBUMS_SHOWN),
                Field("order", "Order", type="select", default="photos", options=ALBUMS_ORDER),
                Field("limit", "Entries", type="number", default=8),
            ),
        ),
        WidgetType(
            kind="users",
            label="Users",
            description="The users of the gallery and when each came last. Needs an administrator's key.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=900,
            options=(Field("limit", "Entries", type="number", default=8),),
        ),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        key_id = str(config.get("key_id") or "").strip()
        secret = str(config.get("key_secret") or "").strip()
        headers = {"Accept": "application/json"}
        if key_id and secret:
            headers["X-PIWIGO-API"] = f"{key_id}:{secret}"
        return headers

    async def _call(self, config: dict[str, Any], ctx: Context, method: str, cache: float = 60, **params: Any) -> Any:
        response = await ctx.request(
            "GET",
            f"{base_url(config)}/ws.php",
            headers=self._headers(config),
            params={"format": "json", "method": method, **params},
            verify=not config.get("insecure"),
            cache_seconds=cache,
            auth_errors=False,
        )
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict) or body.get("stat") not in ("ok", "fail"):
            if response.status_code >= 400:
                raise AdapterError(f"The service answered with HTTP {response.status_code}.", code="http_error",
                                   hint="Check the URL; it should be the address of the gallery, where ws.php lies.")
            raise AdapterError("The service did not answer like Piwigo.", code="not_json",
                               hint="Check the URL; it should be the address of the gallery, where ws.php lies.")
        if body["stat"] == "ok":
            return body.get("result")
        code = _number(body.get("err")) or response.status_code
        said = str(body.get("message") or "").strip()
        if code in (401, 403):
            refused = AuthFailed(f"Piwigo refused: {said or 'Access denied'}.", status=code)
            refused.hint = "The key may be wrong or expired, or not the key of an administrator, which users and the figures of the whole gallery need."
            raise refused
        raise AdapterError(f"Piwigo answered with error {code}: {said or '?'}.", code="piwigo_error",
                           hint="An older Piwigo may not know this method.")

    async def _albums(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        """Every album the key may see, each with its full name: one answer serves both cards that list albums."""
        result = await self._call(config, ctx, "pwg.categories.getList", cache=300, recursive="true", fullname="true")
        found = result.get("categories") if isinstance(result, dict) else None
        return [one for one in found or [] if isinstance(one, dict)]

    async def _infos(self, config: dict[str, Any], ctx: Context) -> dict[str, Any] | None:
        """The figures of the whole gallery, or ``None`` when the key is not an administrator's."""
        try:
            result = await self._call(config, ctx, "pwg.getInfos", cache=300)
        except AuthFailed:
            return None
        pairs = result.get("infos") if isinstance(result, dict) else None
        return {str(one.get("name")): one.get("value") for one in pairs or [] if isinstance(one, dict)}

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        result = await self._call(config, ctx, "pwg.session.getStatus", cache=0)
        status = result if isinstance(result, dict) else {}
        version = status.get("version") or "?"
        who = str(status.get("username") or "")
        if status.get("status") == "guest" or not who:
            return f"Piwigo {version} answers to a visitor: only public albums are counted."
        return f"Piwigo {version} answers, as {who} ({STATUS.get(str(status.get('status')), status.get('status'))})."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "users":
            limit = max(1, _number(options.get("limit")) or 8)
            result = await self._call(config, ctx, "pwg.users.getList", cache=900, display="username,status,last_visit,total_count",
                                      per_page="100")
            return self._users(result, limit)
        albums = await self._albums(config, ctx)
        if widget_kind == "albums":
            return self._album_list(albums, options)
        return self._library(albums, await self._infos(config, ctx))

    @staticmethod
    def _library(albums: list[dict[str, Any]], infos: dict[str, Any] | None) -> WidgetData:
        if infos is None:
            photos = sum(_number(one.get("nb_images")) for one in albums)
            return WidgetData(
                primary={"label": "Photos", "value": photos},
                secondary=[{"label": "Albums", "value": len(albums)}],
                metrics={"photos": float(photos), "albums": float(len(albums))},
            )
        photos = _number(infos.get("nb_elements"))
        count = _number(infos.get("nb_categories"))
        return WidgetData(
            primary={"label": "Photos", "value": photos},
            secondary=[
                {"label": "Albums", "value": count},
                {"label": "Users", "value": _number(infos.get("nb_users"))},
                {"label": "Tags", "value": _number(infos.get("nb_tags"))},
                {"label": "Comments", "value": _number(infos.get("nb_comments"))},
            ],
            metrics={"photos": float(photos), "albums": float(count)},
        )

    @staticmethod
    def _album_list(albums: list[dict[str, Any]], options: dict[str, Any]) -> WidgetData:
        limit = max(1, _number(options.get("limit")) or 8)
        shown = albums if options.get("shown") == "all" else [one for one in albums if not one.get("id_uppercat")]
        order = options.get("order") or "photos"
        if order == "name":
            shown = sorted(shown, key=lambda one: _name(one.get("name")).casefold())
        elif order == "recent":
            shown = sorted(shown, key=lambda one: str(one.get("max_date_last") or ""), reverse=True)
        else:
            shown = sorted(shown, key=lambda one: _number(one.get("total_nb_images")), reverse=True)
        items = [
            {
                "title": _name(one.get("name")) or "?",
                "subtitle": _day(one.get("max_date_last")),
                "value": _number(one.get("total_nb_images")),
                "status": "ok",
            }
            for one in shown[:limit]
        ]
        data = WidgetData(items=items, secondary=[{"label": "Albums", "value": len(shown)}])
        if not items:
            data.meta["empty"] = "No albums."
        return data

    @staticmethod
    def _users(result: Any, limit: int) -> WidgetData:
        found = result.get("users") if isinstance(result, dict) else None
        people = [one for one in found or [] if isinstance(one, dict) and one.get("status") != "guest"]
        people.sort(key=lambda one: str(one.get("last_visit") or ""), reverse=True)
        paging = result.get("paging") if isinstance(result, dict) else None
        total = _number(paging.get("total_count")) if isinstance(paging, dict) else 0
        # The total counts the visitor's account too, which is not shown.
        guests = sum(1 for one in found or [] if isinstance(one, dict) and one.get("status") == "guest")
        count = max(len(people), total - guests) if total else len(people)
        items = [
            {
                "title": str(one.get("username") or "?"),
                "subtitle": STATUS.get(str(one.get("status")), str(one.get("status") or "")),
                "value": _day(one.get("last_visit")) or "–",
                "status": "ok",
            }
            for one in people[:limit]
        ]
        data = WidgetData(items=items, secondary=[{"label": "Users", "value": count}], metrics={"users": float(count)})
        if not items:
            data.meta["empty"] = "No users."
        return data

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        photos = fake.counter("piwigo-photos", tick, 18420, 0.2)
        albums = [
            {"id": 1, "name": "Holidays", "id_uppercat": None, "total_nb_images": 6120, "nb_images": 40, "max_date_last": "2026-08-30 18:02:11"},
            {"id": 2, "name": "Holidays / Norway 2026", "id_uppercat": "1", "total_nb_images": 2310, "nb_images": 2310, "max_date_last": "2026-08-30 18:02:11"},
            {"id": 3, "name": "Family", "id_uppercat": None, "total_nb_images": photos - 9380, "nb_images": photos - 9380, "max_date_last": "2026-11-08 10:14:00"},
            {"id": 4, "name": "Garden", "id_uppercat": None, "total_nb_images": 2140, "nb_images": 2140, "max_date_last": "2026-10-21 16:40:05"},
            {"id": 5, "name": "Scans", "id_uppercat": None, "total_nb_images": 1120, "nb_images": 1120, "max_date_last": "2025-12-27 09:12:44"},
        ]
        if widget_kind == "albums":
            return self._album_list(albums, options)
        if widget_kind == "users":
            people = [
                {"username": "alex", "status": "webmaster", "last_visit": "2026-11-09 08:12:00"},
                {"username": "sam", "status": "normal", "last_visit": "2026-11-07 19:45:31"},
                {"username": "family", "status": "generic", "last_visit": "2026-11-02 14:03:10"},
                {"username": "kim", "status": "normal", "last_visit": None},
                {"username": "guest", "status": "guest", "last_visit": None},
            ]
            return self._users({"users": people, "paging": {"total_count": len(people)}}, _number(options.get("limit")) or 8)
        return self._library(albums, {"nb_elements": photos, "nb_categories": 64, "nb_users": 4, "nb_tags": 212, "nb_comments": 37})


ADAPTER = PiwigoAdapter()
