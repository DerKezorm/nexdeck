"""nexpaper: the household's paperwork, read through its API keys.

Written against nexpaper's ``GET /api/v1/dashboard`` and ``routers/v1.py`` for
the walls around it, and measured on 11.10.2026 against a fresh nexpaper with
made-up content: every card, a wrong credential, the API switched off, an
Origin header, the rate. In beta until it has run against one in use.

- The key (``npk_…``) goes in ``Authorization: Bearer``, never in the
  address. nexpaper refuses any request that carries an ``Origin`` header
  (403 ``origin_refused``), so it is only ever called from nexdeck's server.
- API keys are off until nexpaper's operator opens them: 401 ``api_off``. A
  wrong, blocked or run-out key answers 401 ``key_invalid``; a device token
  (``npd_…``) 401 ``token_wrong_kind``; a key that may only upload (scope
  ``upload``) 403 ``key_scope`` on every route that reads. Five wrong keys
  from one address make it rest a quarter of an hour (429
  ``too_many_attempts``), and more than 120 requests a minute 429
  ``slow_down``. The cards tell all of these apart.
- The three cards read the one answer, which nexdeck keeps for 30 seconds,
  so a board with all of them asks nexpaper twice a minute at most.
- ``/me`` names the key's scope. The connection test says so when the key
  could never fill a card.

What the cards leave out on purpose: the text of a document, its sender, the
vault it lies in and who else may see it. A document shows by its title and
the day it came in, which is as much as the agreed answer carries.
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    Context,
    Field,
    WidgetData,
    WidgetType,
    ago,
    base_url,
)
from .nexapp_base import NexappApi, count_of, epoch_of

#: How far ahead the deadlines card looks, and how close a deadline has to be to turn it yellow.
LOOK_AHEAD_DAYS = 14
SOON_DAYS = 3
#: What a deadline is, as nexpaper names it (``kind``). Any other value is shown as it came.
KINDS = {"due": "Due", "contract_end": "Contract ends", "warranty_end": "Warranty ends"}
#: The inbox card turns yellow at this many documents, or when the oldest has waited this many days.
WARN_COUNT = 10
WARN_DAYS = 14
#: nexpaper's answer is the same for all three cards; this is how long nexdeck keeps it.
KEEP_SECONDS = 30


class NexpaperAdapter(NexappApi, Adapter):
    kind = "nexpaper"
    label = "nexpaper"
    category = "other"
    description = "The paperwork of a household in nexpaper: what waits in the inbox, which deadlines are near, and how many documents are filed."
    icon = "nexpaper"
    #: Beta until every card has run against a nexpaper in use; measured against a fresh one on 11.10.2026.
    beta = True
    docs_url = "https://nexpaper.nexapps.dev"
    app = "nexpaper"
    own_fields = ("scope",)
    thing = "key"
    where_on = "nexpaper's operator switches API keys on under Settings > API"
    where_make = "Make a key with the scope Read under My account in nexpaper."
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://nexpaper:8560"),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="Under My account in nexpaper, after the operator has allowed API keys. It starts with npk_ and needs the scope Read."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="inbox",
            label="nexpaper inbox",
            description="The documents waiting in the inbox, the oldest first, each opening in nexpaper. Yellow when many wait or the oldest has waited long.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=120,
            metrics=("inbox",),
            options=(
                Field("warn_count", "Yellow from (documents)", type="number", default=WARN_COUNT,
                      help="Yellow when at least this many documents wait. 0 switches this off."),
                Field("warn_days", "Yellow after (days)", type="number", default=WARN_DAYS,
                      help="Yellow when the oldest document has waited longer than this. 0 switches this off."),
            ),
        ),
        WidgetType(
            kind="deadlines",
            label="Deadlines",
            description="What falls due in the next 14 days, soonest first, each opening its document. Yellow when something is due within 3 days.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=300,
            options=(Field("limit", "Entries", type="number", default=8),),
        ),
        WidgetType(
            kind="library",
            label="Filing",
            description="How many documents there are in all, how many came in this week, and how many are being read for their text right now.",
            renderer="value",
            default_size=(3, 2),
            refresh_seconds=300,
            metrics=("documents",),
        ),
    )

    def default_link(self, config: dict[str, Any]) -> str:
        return base_url(config)

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        me = await self._me(config, ctx)
        me = me if isinstance(me, dict) else {}
        if me.get("scope") and me.get("scope") != "read":
            raise AdapterError(
                "This key may only upload files. The cards need a key with the scope read.", code="wrong_scope",
                hint=self.where_make,
            )
        return f"nexpaper {me.get('version') or '?'} answers; the key of {me.get('name') or '?'} reads."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        numbers = await self._get(config, ctx, "/dashboard", cache=KEEP_SECONDS, missing=(
            "This nexpaper has no dashboard route yet; it needs a newer version.", "too_old",
            "Update nexpaper; the route came with the version that has a card for nexdeck. Or the address has a path: use the one you open nexpaper with."))
        numbers = self._expect(numbers, "inbox", "inbox_oldest", "filed", "total", "added_week", "processing", "deadlines")
        base = base_url(config)
        if widget_kind == "deadlines":
            return deadlines_of(numbers, _today(), _limit(options, 8), base)
        if widget_kind == "library":
            return library_of(numbers)
        return inbox_of(numbers, _now(), _threshold(options, "warn_count", WARN_COUNT), _threshold(options, "warn_days", WARN_DAYS))

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = _now()
        today = _today()
        if widget_kind == "deadlines":
            rows = [
                {"id": 40, "title": "Car insurance, renewal", "date": (today + timedelta(days=2)).isoformat(), "kind": "due"},
                {"id": 41, "title": "Tax return, reminder", "date": (today + timedelta(days=9)).isoformat(), "kind": "due"},
                {"id": 42, "title": "Gym membership, cancel by", "date": (today + timedelta(days=13)).isoformat(), "kind": "due"},
            ]
            if fake.flicker("nexpaper-late", tick, 0.4):
                rows.insert(0, {"id": 39, "title": "Electricity bill", "date": (today - timedelta(days=1)).isoformat(), "kind": "due"})
            return deadlines_of({"deadlines": rows}, today, _limit(options, 8), "http://nexpaper.example.com")
        if widget_kind == "library":
            return library_of({"total": 419 + int(fake.counter("nexpaper-total", tick, 0, 0.01)), "filed": 412, "added_week": 9,
                               "processing": 1 if fake.flicker("nexpaper-ocr", tick, 0.4) else 0})
        waiting = int(fake.walk("nexpaper-inbox", tick, 4, 13))
        rows = [
            {"id": 12 + number, "title": title, "added_at": _iso(now - 86400 * days), "url": f"http://nexpaper.example.com/eingang/{12 + number}"}
            for number, (title, days) in enumerate((("Scan from the printer", 16), ("Letter from the council", 6), ("Phone bill", 2), ("Receipt, hardware store", 1)))
        ]
        return inbox_of({"inbox": waiting, "inbox_oldest": rows, "inbox_oldest_at": rows[0]["added_at"]}, now,
                        _threshold(options, "warn_count", WARN_COUNT), _threshold(options, "warn_days", WARN_DAYS))


def _now() -> float:
    return time.time()


def _today() -> date:
    """Today on nexdeck's clock, which is the clock of the people looking at the board."""
    return datetime.now().astimezone().date()


def _iso(moment: float) -> str:
    return datetime.fromtimestamp(moment, UTC).isoformat(timespec="seconds")


def _limit(options: dict[str, Any], default: int) -> int:
    try:
        return max(1, min(50, int(options.get("limit") or default)))
    except (TypeError, ValueError):
        return default


def _threshold(options: dict[str, Any], name: str, default: int) -> int:
    """A limit the operator set; 0 switches it off, and what is not a number is the default."""
    wanted = options.get(name)
    if wanted is None or wanted == "":
        return default
    try:
        return max(0, int(wanted))
    except (TypeError, ValueError):
        return default


def inbox_of(numbers: dict[str, Any], now: float, warn_count: int, warn_days: int) -> WidgetData:
    """The count above the oldest documents; yellow by count or by age, as the card was told."""
    waiting = count_of(numbers.get("inbox"))
    rows = [one for one in numbers.get("inbox_oldest") or [] if isinstance(one, dict)]
    oldest = epoch_of(numbers.get("inbox_oldest_at")) or (epoch_of(rows[0].get("added_at")) if rows else None)
    days = int((now - oldest) // 86400) if oldest is not None and waiting else None
    reasons = []
    if warn_count and waiting >= warn_count:
        reasons.append(f"{waiting} in the inbox")
    if warn_days and days is not None and days > warn_days:
        reasons.append(f"oldest {days} d old")
    items = []
    for row in rows:
        added = epoch_of(row.get("added_at"))
        late = bool(warn_days and added is not None and (now - added) // 86400 > warn_days)
        items.append({
            "id": row.get("id"),
            "title": str(row.get("title") or "?"),
            "status": "warn" if late else "ok",
            "when": added,
            "url": str(row.get("url") or ""),
        })
    return WidgetData(
        status="warn" if reasons else "ok",
        primary={"label": "In the inbox", "value": waiting},
        secondary=[{"label": "Oldest", "value": ago(oldest, now)}] if days is not None and ago(oldest, now) else [],
        items=items,
        metrics={"inbox": float(waiting)},
        meta={"headline": True, "empty": "The inbox is empty.", "status_reason": " · ".join(reasons)},
    )


def _due(moment: Any) -> date | None:
    try:
        return date.fromisoformat(str(moment)[:10])
    except ValueError:
        return None


def deadlines_of(numbers: dict[str, Any], today: date, limit: int, base: str) -> WidgetData:
    """What falls due in the next fortnight, soonest first. Overdue is red, within three days yellow."""
    rows: list[tuple[date, dict[str, Any]]] = []
    for row in numbers.get("deadlines") or []:
        day = _due(row.get("date")) if isinstance(row, dict) else None
        if day is not None and (day - today).days <= LOOK_AHEAD_DAYS:
            rows.append((day, row))
    rows.sort(key=lambda pair: pair[0])
    items = []
    for day, row in rows[:limit]:
        left = (day - today).days
        items.append({
            # A document can come twice, as a contract that ends and a warranty that ends: the key is both.
            "id": f"{row.get('id')}:{row.get('kind')}",
            "title": str(row.get("title") or "?"),
            "subtitle": " · ".join(part for part in (KINDS.get(str(row.get("kind") or ""), str(row.get("kind") or "")), day.isoformat()) if part),
            "value": "Today" if left == 0 else "Tomorrow" if left == 1 else f"in {left} d" if left > 0 else f"{-left} d overdue",
            "status": "bad" if left < 0 else "warn" if left <= SOON_DAYS else "ok",
            "url": str(row.get("url") or "") or base,
        })
    return WidgetData(
        status="bad" if any(item["status"] == "bad" for item in items) else "warn" if any(item["status"] == "warn" for item in items) else "ok",
        items=items,
        meta={"empty": "Nothing falls due in the next 14 days."},
    )


def library_of(numbers: dict[str, Any]) -> WidgetData:
    total = count_of(numbers.get("total"))
    return WidgetData(
        status="ok",
        primary={"label": "Documents", "value": total},
        secondary=[
            {"label": "Filed", "value": count_of(numbers.get("filed"))},
            {"label": "This week", "value": count_of(numbers.get("added_week"))},
            {"label": "Reading text", "value": count_of(numbers.get("processing"))},
        ],
        metrics={"documents": float(total)},
    )


ADAPTER = NexpaperAdapter()
