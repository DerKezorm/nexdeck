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
"""

from __future__ import annotations

import csv
import io
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
)

#: How long an ended warranty stays on the card.
ENDED_DAYS = 30


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
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="Profile > API Keys > Create API Key. Homebox shows the key only once."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="inventory", label="Inventory", description="How many items there are, what they are worth together and how many locations.",
                   renderer="value", default_size=(3, 2), refresh_seconds=900, metrics=("items",)),
        WidgetType(kind="warranties", label="Warranties", description="The warranties that end within the chosen days, and those that ended in the last 30.",
                   renderer="list", default_size=(3, 3), refresh_seconds=3600,
                   options=(Field("days", "Days ahead", type="number", default=60),
                            Field("limit", "Entries", type="number", default=8))),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"Authorization": f"Bearer {config.get('api_key') or ''}"}

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 60) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api/v1{path}", headers=self._headers(config),
            verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("Homebox rejected the API key.")
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
            export = await self._get(config, ctx, "/entities/export", cache=600)
            return self._warranties(_warranty_rows(export.text), datetime.now(UTC).date(), base_url(config), options)
        statistics = await self._json(config, ctx, "/groups/statistics")
        group = await self._json(config, ctx, "/groups", cache=3600)
        return self._inventory(statistics, str(group.get("currency") or ""))

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
            secondary=[{"label": "Total value", "value": worth}, {"label": "Locations", "value": int(statistics.get("totalLocations") or 0)}],
            metrics={"items": float(items)},
        )

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
        return self._inventory({"totalItems": 214 + tick % 3, "totalItemPrice": 18_430.5, "totalLocations": 9}, "EUR")


ADAPTER = HomeboxAdapter()
