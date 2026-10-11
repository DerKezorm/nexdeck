"""nexdiary: the diary of a family, as numbers only, read through its API tokens.

Written against the answer of nexdiary's ``GET /api/v1/dashboard`` as agreed
with it (nexdiary 0.8.0) and against ``routers/v1.py`` for the walls around
it. The route was not yet in a released nexdiary when this was written, so
the shape below is the agreed one and has not been measured; the adapter is
in beta for that reason.

- The token (``nxa_…``) goes in ``Authorization: Bearer``, never in the
  address. nexdiary refuses any request that carries an ``Origin`` header
  (403 ``origin_refused``), so it is only ever called from nexdeck's server.
- API tokens are off until nexdiary's operator opens them: 401 ``api_off``.
  A wrong, withdrawn or run-out token answers 401 ``token_invalid``; the card
  tells the two apart. 429 ``slow_down`` after 600 requests in a minute.
- Every request makes nexdiary decrypt the account's whole history. The cards therefore refresh every ten
  minutes, and nexdeck keeps the one answer they share for five.
- ``streak_unit`` says ``days`` or ``weeks``: with a weekly goal under seven days nexdiary counts the streak in
  weeks. Without the field (an older nexdiary) it is days.
- The token reads as its account. The answer holds five numbers and two
  dates, and the cards show those: whether the day has been written, the
  streak, the entries and notes of the month, and when the next time capsule
  opens.

What the cards leave out on purpose, and the API does not even carry: every
word anybody wrote, the values, the titles of days and capsules, and who
wrote what. A diary is the one thing on a board that guests must not read
anything of, so the cards are statistics and nothing else.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
)
from .nexapp_base import NexappApi, count_of

#: Every request makes nexdiary decrypt the whole history of the account, so the answer is kept for five minutes and
#: both cards, which read the one answer, ask only every ten.
KEEP_SECONDS = 300


class NexdiaryAdapter(NexappApi, Adapter):
    kind = "nexdiary"
    label = "nexdiary"
    category = "other"
    description = "The diary of a family in nexdiary, as numbers only: whether today is written, the streak, the month, and when the next time capsule opens."
    icon = "nexdiary"
    #: Beta until every card has run against a real nexdiary.
    beta = True
    docs_url = "https://nexdiary.nexapps.dev"
    app = "nexdiary"
    thing = "token"
    where_on = "nexdiary's operator switches API tokens on under Settings > API"
    where_make = "Make a token under My account > Connections in nexdiary."
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://nexdiary:8550"),
        Field("api_key", "API token", type="password", secret=True, required=True,
              help="My account > Connections in nexdiary, after the operator has switched on API tokens. It starts with nxa_ and only reads."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="diary",
            label="Diary",
            description="Whether today has been written, the streak, and the entries and notes of this month. Numbers only, never a word of the diary.",
            renderer="value",
            default_size=(3, 2),
            refresh_seconds=KEEP_SECONDS * 2,
            metrics=("streak",),
        ),
        WidgetType(
            kind="capsule",
            label="Time capsule",
            description="In how many days the next sealed time capsule opens, or that none is sealed. No content.",
            renderer="value",
            default_size=(2, 2),
            refresh_seconds=KEEP_SECONDS * 2,
            metrics=("capsule_days",),
        ),
    )

    def default_link(self, config: dict[str, Any]) -> str:
        return base_url(config)

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        me = await self._get(config, ctx, "/me", cache=0)
        me = me if isinstance(me, dict) else {}
        return f"nexdiary {me.get('version') or '?'} answers; the token of {me.get('name') or '?'} reads."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        numbers = await self._get(config, ctx, "/dashboard", cache=KEEP_SECONDS, missing=(
            "This nexdiary has no dashboard route yet; it needs a newer version.", "too_old",
            "Update nexdiary; the route came with the version that has a card for nexdeck."))
        numbers = numbers if isinstance(numbers, dict) else {}
        return capsule_of(numbers) if widget_kind == "capsule" else diary_of(numbers)

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        opens = date.today() + timedelta(days=74)
        numbers = {
            "version": "0.8.0", "today_written": fake.flicker("nexdiary-today", tick, 0.5), "streak": 12,
            "entries_month": 9, "notes_month": int(fake.walk("nexdiary-notes", tick, 28, 34)),
            "next_capsule": opens.isoformat(), "next_capsule_days": 74,
        }
        return capsule_of(numbers) if widget_kind == "capsule" else diary_of(numbers)


def diary_of(numbers: dict[str, Any]) -> WidgetData:
    """The streak as the number, today's yes or no beside this month's entries and notes."""
    streak = count_of(numbers.get("streak"))
    return WidgetData(
        status="ok",
        primary={"label": "Streak", "value": streak, "unit": _unit(streak, numbers.get("streak_unit"))},
        secondary=[
            # Left out when the answer does not say: "No" would claim something nobody knows.
            *([{"label": "Written today", "value": "Yes" if numbers["today_written"] else "No"}]
              if isinstance(numbers.get("today_written"), bool) else []),
            {"label": "Entries this month", "value": count_of(numbers.get("entries_month"))},
            {"label": "Notes this month", "value": count_of(numbers.get("notes_month"))},
        ],
        metrics={"streak": float(streak)},
    )


def capsule_of(numbers: dict[str, Any]) -> WidgetData:
    """In how many days the next capsule opens, or that none is sealed."""
    days = numbers.get("next_capsule_days")
    opens = _day(numbers.get("next_capsule"))
    if isinstance(days, bool) or not isinstance(days, (int, float)):
        return WidgetData(status="ok", primary={"label": "Next time capsule", "value": "None sealed"})
    return WidgetData(
        status="ok",
        primary={"label": "Opens in", "value": max(0, int(days)), "unit": _unit(max(0, int(days)), "days")},
        secondary=[{"label": "On", "value": opens}] if opens else [],
        metrics={"capsule_days": float(max(0, int(days)))},
    )


def _unit(amount: int, unit: Any) -> str:
    """``day`` or ``days``, ``week`` or ``weeks``. nexdiary counts the streak in weeks when the goal is under seven
    days a week, and says so in ``streak_unit``; an older nexdiary does not, and its streak is in days."""
    word = "week" if unit == "weeks" else "day"
    return word if amount == 1 else f"{word}s"


def _day(moment: Any) -> str:
    """The day as ``2026-12-24``, or nothing when the answer has none."""
    try:
        return datetime.fromisoformat(str(moment)[:10]).date().isoformat()
    except ValueError:
        return ""


ADAPTER = NexdiaryAdapter()
