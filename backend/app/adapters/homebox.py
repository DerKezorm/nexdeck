"""Homebox: how many things are in the inventory, what they are worth, and whose warranty runs out.

Measured against Homebox v0.26.2 (ghcr.io/sysadminsmedia/homebox) on
11.09.2026, with six invented items in one location: three with a warranty
(one ending in 20 days, one next spring, one ended ten days ago), one with a
lifetime warranty, one without, and four batteries at 5.00 each.

⚠️ An API key from Profile > API Keys works as ``Authorization: Bearer <key>``
and without the word Bearer as well. A missing one gets 401 "authorization
header or query is required", a made-up one 401 "valid authorization token is
required". (The image refuses to start without ``HBOX_AUTH_API_KEY_PEPPER``,
which is what those keys are signed with.)

⚠️ Items are "entities" in this version, and the summary the list hands out
has no warranty at all. The CSV export has it for every item in one request,
together with the location and a link of the item's own (``/item/<id>``).

⚠️ ``totalItemPrice`` in the statistics multiplies by the quantity: the four
batteries counted 20.00 there. The ``totalPrice`` of the entity list covers
only the page it came with and ignores the quantity, so the card takes the
statistics. ``totalWithWarranty`` counts a warranty that already ended and
not a lifetime one.

⚠️ ``/v1/currency`` is in the API documentation and answers 404. The currency
is on ``/v1/groups``.

Measured again on 26.09.2026 against v0.26.2 and v0.25.0 side by side, with
five invented things in three places under three tags:

⚠️ API keys exist from 0.26 on. On 0.25 ``/v1/users/self/api-keys`` is 404,
so no key can work there, and the card signs in with the account instead:
``POST /v1/users/login`` hands out a token that already carries the word
Bearer, valid for seven days on both versions. A wrong password and an
unknown account both get 401 "unauthorized".

⚠️ The export moved with 0.26, from ``/v1/items/export`` to
``/v1/entities/export``. Its columns and the warranty in them are the same;
the adapter asks the new address first and remembers which one answered.

⚠️ ``/v1/groups/statistics/locations`` and ``/tags`` do NOT multiply by the
quantity: four batteries at 5.00 count 5.00 there, 20.00 in the total. A
place or tag whose things add up to nothing is left out of the answer. The
card per place therefore shows its own sum as the whole and says so.
"""

from __future__ import annotations

import csv
import io
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

from .base import (
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    part_on,
)

#: How long an ended warranty stays on the card.
ENDED_DAYS = 30
SESSION = "homebox_session"
EXPORT_AT = "homebox_export"
EXPORTS = ("/entities/export", "/items/export")


def _warranty_rows(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if "HB.warranty_expires" not in (reader.fieldnames or []):
        raise AdapterError("This address answers, but not the way Homebox does.", code="not_homebox",
                           hint="The export of the items has no warranty column.")
    return [row for row in reader if str(row.get("HB.url") or "").startswith("/item/")]


class HomeboxAdapter(Adapter):
    kind = "homebox"
    label = "Homebox"
    category = "other"
    description = "How many things are in the inventory, what they are worth, and which warranty runs out."
    icon = "homebox"
    #: Confirmed against a live instance on 2026-09-11.
    beta = False
    docs_url = "https://homebox.software/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://homebox:7745"),
        Field("api_key", "API key", type="password", secret=True,
              help="Homebox 0.26 or newer: Profile > API Keys > Create API Key. Homebox shows the key only once. "
                   "Older versions have no keys; fill in the account below instead."),
        Field("username", "E-mail", help="Only without an API key: the e-mail address the account signs in with."),
        Field("password", "Password", type="password", secret=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="inventory", label="Inventory", description="How many items there are, what they are worth together and how many locations.",
                   renderer="value", default_size=(3, 2), refresh_seconds=900, metrics=("items",),
                   parts=(("value", "Total value"), ("locations", "Locations")),
                   options=(Field("currency", "Currency", placeholder="EUR",
                                  help="Written after the value. Empty takes the one set in Homebox."),)),
        WidgetType(kind="worth", label="Value by place",
                   description="What the things in each place are worth, or under each tag, the largest first, with each one's share.",
                   renderer="list", default_size=(3, 3), refresh_seconds=900,
                   options=(Field("by", "Group by", type="select", default="location", options=(("location", "Place"), ("tag", "Tag"))),
                            Field("currency", "Currency", placeholder="EUR", help="Written after the value. Empty takes the one set in Homebox."),
                            Field("limit", "Entries", type="number", default=8))),
        WidgetType(kind="warranties", label="Warranties", description="The warranties that end within the chosen days, and those that ended in the last 30.",
                   renderer="list", default_size=(3, 3), refresh_seconds=3600,
                   options=(Field("days", "Days ahead", type="number", default=60),
                            Field("limit", "Entries", type="number", default=8))),
    )

    async def _authorization(self, config: dict[str, Any], ctx: Context, *, fresh: bool = False) -> str:
        key = str(config.get("api_key") or "").strip()
        if key:
            return f"Bearer {key}"
        user = str(config.get("username") or "").strip()
        if not user:
            raise AuthFailed("Homebox needs an API key, or an account on versions before 0.26.")
        who = (base_url(config), user, str(config.get("password") or ""))
        held = ctx.cache.get(SESSION)
        if not fresh and isinstance(held, tuple) and held[0] == who and held[2] > time.time():
            return str(held[1])
        response = await ctx.request("POST", f"{base_url(config)}/api/v1/users/login",
                                     json_body={"username": user, "password": who[2], "stayLoggedIn": False},
                                     verify=not config.get("insecure"), auth_errors=False)
        if response.status_code == 401:
            raise AuthFailed("Homebox rejected the e-mail or the password.")
        try:
            answer = response.json()
        except ValueError:
            answer = None
        token = str(answer.get("token") or "") if isinstance(answer, dict) else ""
        if response.status_code >= 400 or not token:
            raise AdapterError(f"Homebox did not sign in (HTTP {response.status_code}).", code="http_error",
                               hint="Check the URL; it is the address of Homebox itself, without /api.")
        # ⚠️ The token already says "Bearer". Seven days; taken up again a day early.
        try:
            ends = datetime.fromisoformat(str(answer.get("expiresAt"))[:19]).replace(tzinfo=UTC).timestamp()
        except ValueError:
            ends = time.time() + 2 * 86400
        token = token if token.startswith("Bearer ") else f"Bearer {token}"
        ctx.cache[SESSION] = (who, token, ends - 86400)
        return token

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 60) -> Any:
        async def ask(fresh: bool) -> Any:
            return await ctx.request(
                "GET", f"{base_url(config)}/api/v1{path}", headers={"Authorization": await self._authorization(config, ctx, fresh=fresh)},
                verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
            )

        with_key = bool(str(config.get("api_key") or "").strip())
        response = await ask(False)
        if response.status_code in (401, 403) and not with_key:
            # A token Homebox let go of before its time: once more with a new one.
            response = await ask(True)
        if response.status_code in (401, 403):
            raise AuthFailed("Homebox rejected the API key. Versions before 0.26 have no keys; sign in with the account there."
                             if with_key else "Homebox rejected the account's token.")
        if response.status_code >= 400:
            raise AdapterError(f"Homebox answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of Homebox itself, without /api.")
        return response

    async def _json(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 60) -> dict[str, Any]:
        response = await self._get(config, ctx, path, cache)
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("Homebox did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than Homebox.") from error
        if not isinstance(answer, dict):
            raise AdapterError("This address answers, but not the way Homebox does.", code="not_homebox")
        return answer

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        status = await self._json(config, ctx, "/status", cache=0)
        statistics = await self._json(config, ctx, "/groups/statistics", cache=0)
        version = (status.get("build") or {}).get("version") if isinstance(status.get("build"), dict) else None
        return f"Homebox {version or '?'} answers with {int(statistics.get('totalItems') or 0)} items."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "warranties":
            export = await self._export(config, ctx)
            return self._warranties(_warranty_rows(export.text), datetime.now(UTC).date(), base_url(config), options)
        statistics = await self._json(config, ctx, "/groups/statistics") if widget_kind == "inventory" else {}
        currency = str(options.get("currency") or "").strip()
        if not currency and (widget_kind == "worth" or part_on(options, "value")):
            # An empty currency still takes the group's; a given one spares the question.
            currency = str((await self._json(config, ctx, "/groups", cache=3600)).get("currency") or "")
        if widget_kind == "worth":
            by = "tags" if options.get("by") == "tag" else "locations"
            response = await self._get(config, ctx, f"/groups/statistics/{by}", cache=600)
            try:
                totals = response.json()
            except ValueError as error:
                raise AdapterError("Homebox did not answer with JSON.", code="not_json") from error
            return self._worth(totals if isinstance(totals, list) else [], currency, int(options.get("limit") or 8), by)
        return self._inventory(statistics, currency)

    async def _export(self, config: dict[str, Any], ctx: Context) -> Any:
        """⚠️ 0.26 moved it; the first address that answers is remembered."""
        known = ctx.cache.get(EXPORT_AT)
        for path in ([known] if known in EXPORTS else []) + [one for one in EXPORTS if one != known]:
            try:
                response = await self._get(config, ctx, path, cache=600)
            except AdapterError as error:
                if error.code == "http_error":
                    continue
                raise
            ctx.cache[EXPORT_AT] = path
            return response
        raise AdapterError("Homebox answered neither export address.", code="http_error",
                           hint="Check the URL; it is the address of Homebox itself, without /api.")

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _inventory(statistics: dict[str, Any], currency: str) -> WidgetData:
        items = int(statistics.get("totalItems") or 0)
        try:
            worth = f"{float(statistics.get('totalItemPrice') or 0):,.2f} {currency}".strip()
        except (TypeError, ValueError):
            worth = ""
        return WidgetData(
            status="ok",
            primary={"label": "Things", "value": items},
            secondary=[{"label": "Total value", "value": worth, "part": "value"},
                       {"label": "Locations", "value": int(statistics.get("totalLocations") or 0), "part": "locations"}],
            metrics={"items": float(items)},
        )

    @staticmethod
    def _worth(totals: list[Any], currency: str, limit: int, by: str) -> WidgetData:
        found = [(str(one.get("name") or "?"), float(one.get("total") or 0)) for one in totals if isinstance(one, dict)]
        found = sorted((row for row in found if row[1] > 0), key=lambda row: (-row[1], row[0]))
        whole = sum(value for _name, value in found)
        items = [{"title": name, "value": f"{value:,.2f} {currency}".strip(), "progress": round(100 * value / whole, 1),
                  "subtitle": f"{100 * value / whole:.0f} %", "status": "ok"} for name, value in found]
        # ⚠️ Homebox leaves out what adds up to nothing, and counts one of each.
        notice = ""
        if items:
            notice = ("Shares of what these places hold; places without a price are not listed." if by == "locations"
                      else "Shares of what these tags hold; a thing under two tags counts for both.")
        return WidgetData(status="ok" if items else "unknown", items=items[:max(1, limit)],
                          meta={"empty": "Nothing with a price yet.", "notice": notice})

    @staticmethod
    def _warranties(rows: list[dict[str, str]], today: date, base: str, options: dict[str, Any]) -> WidgetData:
        ahead = max(1, int(options.get("days") or 60))
        ending: list[tuple[date, dict[str, Any]]] = []
        soon = 0
        for row in rows:
            try:
                ends = date.fromisoformat(str(row.get("HB.warranty_expires") or "")[:10])
            except ValueError:
                continue
            left = (ends - today).days
            if left > ahead or left < -ENDED_DAYS:
                continue
            place = str(row.get("HB.location") or "")
            item: dict[str, Any] = {
                "title": str(row.get("HB.name") or "?"),
                "subtitle": " · ".join(part for part in ("Expired" if left < 0 else "", place, ends.isoformat()) if part),
                "status": "bad" if left < 0 else "warn" if left <= 30 else "ok",
                "value": f"{left} d" if left >= 0 else "",
            }
            if str(row.get("HB.url") or "").startswith("/item/"):
                item["url"] = f"{base}{row['HB.url']}"
            if left >= 0:
                soon += 1
            ending.append((ends, item))
        ending.sort(key=lambda pair: pair[0])
        return WidgetData(
            status="bad" if any(item["status"] == "bad" for _ends, item in ending) else "ok",
            items=[item for _ends, item in ending][: int(options.get("limit") or 8)],
            secondary=[{"label": "Ending soon", "value": soon}],
            meta={"empty": "No warranty ends in this time."},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        today = datetime.now(UTC).date()
        if widget_kind == "warranties":
            rows = [
                {"HB.name": "Cordless Drill", "HB.location": "Garage", "HB.url": "/item/demo-drill", "HB.warranty_expires": (today + timedelta(days=20)).isoformat()},
                {"HB.name": "Coffee Machine", "HB.location": "Kitchen", "HB.url": "/item/demo-coffee", "HB.warranty_expires": (today + timedelta(days=48)).isoformat()},
                {"HB.name": "Wifi Router", "HB.location": "Office", "HB.url": "/item/demo-router", "HB.warranty_expires": (today - timedelta(days=10)).isoformat()},
            ]
            return self._warranties(rows, today, "https://homebox.example.com", options)
        if widget_kind == "worth":
            by = "tags" if options.get("by") == "tag" else "locations"
            totals = ([{"name": "Office", "total": 4210.0}, {"name": "Living Room", "total": 3890.5}, {"name": "Kitchen", "total": 2140.0},
                       {"name": "Garage", "total": 1320.0 + tick % 3 * 25}, {"name": "Attic", "total": 0}] if by == "locations" else
                      [{"name": "Electronics", "total": 7480.0}, {"name": "Tools", "total": 1320.0}, {"name": "Kitchen", "total": 2140.0}])
            return self._worth(totals, str(options.get("currency") or "EUR"), int(options.get("limit") or 8), by)
        return self._inventory({"totalItems": 214 + tick % 3, "totalItemPrice": 18_430.5, "totalLocations": 9}, str(options.get("currency") or "EUR"))


ADAPTER = HomeboxAdapter()
