"""Healthchecks: the cron jobs and background work that did not report in.

Measured against Healthchecks 4.4, the official image, on 11.09.2026. The
same API answers on healthchecks.io.

⚠️ The official image's uWSGI closes the connection after every answer and
does not say so. Measured: of twenty requests sent back to back over one
kept-alive connection, four failed with "server disconnected"; with
``Connection: close`` none did. Two cards on the same instance ask within
milliseconds of each other, so every request here says ``close``.

⚠️ A wrong key is answered with 401 and ``{"error": "missing api key"}``.
The key was not missing. The message the card shows says "rejected" instead.
"""

from __future__ import annotations

import time
from typing import Any

from . import demo as fake
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
    duration_short,
    ring_of,
)

#: What Healthchecks calls a state, and how a card colours it.
COLOUR = {"down": "bad", "grace": "warn", "started": "ok", "up": "ok", "new": "unknown", "paused": "unknown"}
#: The ones that need someone first.
ORDER = {"down": 0, "grace": 1, "started": 2, "up": 3, "new": 4, "paused": 5}
WORD = {"down": "Down", "grace": "Late", "started": "Running", "up": "Up", "new": "New", "paused": "Paused"}


class HealthchecksAdapter(Adapter):
    kind = "healthchecks"
    label = "Healthchecks"
    category = "monitoring"
    description = "Cron jobs and background work, and which of them did not report in."
    icon = "healthchecks"
    beta = False
    docs_url = "https://healthchecks.io/docs/api/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://healthchecks.io",
              help="Your own instance, or https://healthchecks.io for the hosted service."),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="Project settings > API Access. The read-only key is enough."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="checks", label="Checks", description="Every check with its last ping, down and late ones first.",
                   renderer="list", default_size=(3, 3), refresh_seconds=60, metrics=("down",),
                   options=(Field("limit", "Entries", type="number", default=12),
                            Field("tag", "Tag", help="Only checks with this tag. Empty shows all."),
                            Field("problems", "Only late and down checks", type="bool", default=False))),
        WidgetType(kind="summary", label="Checks up", description="How many checks are up, late and down.",
                   renderer="value", default_size=(3, 2), refresh_seconds=60, ring=True, metrics=("down", "late")),
    )

    async def _checks(self, config: dict[str, Any], ctx: Context, tag: str = "", cache: float = 10) -> list[dict[str, Any]]:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api/v3/checks/",
            headers={"X-Api-Key": str(config.get("api_key") or ""), "Connection": "close"},
            params={"tag": tag} if tag else None,
            verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("Healthchecks rejected the API key.")
        if response.status_code >= 400:
            raise AdapterError(f"Healthchecks answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of Healthchecks itself, without /api.")
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("Healthchecks did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a reverse proxy.") from error
        if not isinstance(answer, dict) or not isinstance(answer.get("checks"), list):
            raise AdapterError("This address answers, but not the way Healthchecks does.", code="not_healthchecks")
        return [check for check in answer["checks"] if isinstance(check, dict)]

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        checks = await self._checks(config, ctx, cache=0)
        down = sum(1 for check in checks if check.get("status") == "down")
        return f"Healthchecks answers with {len(checks)} checks, {down} down."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "summary":
            return self._summary(await self._checks(config, ctx))
        checks = await self._checks(config, ctx, tag=str(options.get("tag") or "").strip())
        return self._list(checks, options, base_url(config))

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _counts(checks: list[dict[str, Any]]) -> dict[str, int]:
        counts = dict.fromkeys(ORDER, 0)
        for check in checks:
            state = str(check.get("status") or "")
            if state in counts:
                counts[state] += 1
        return counts

    @classmethod
    def _summary(cls, checks: list[dict[str, Any]]) -> WidgetData:
        counts = cls._counts(checks)
        up = counts["up"] + counts["started"]
        waiting = counts["new"] + counts["paused"]
        # ⚠️ Seen on a real board: five chips and a button on a card two columns
        # wide ran off its edge. A chip at zero only where the zero says something.
        secondary: list[dict[str, Any]] = [{"label": "Down", "value": counts["down"]}]
        secondary += [{"label": label, "value": counts[key]} for label, key in (("Late", "grace"), ("Paused", "paused"), ("New", "new")) if counts[key]]
        return WidgetData(
            status="bad" if counts["down"] else "warn" if counts["grace"] else "ok",
            primary={"label": "Checks up", "value": up, "unit": f"/ {len(checks)}"},
            secondary=secondary,
            meta={"ring": ring_of(("Up", up), ("Late", counts["grace"]), ("Down", counts["down"]), ("Not running", waiting))},
            metrics={"down": float(counts["down"]), "late": float(counts["grace"])},
        )

    @classmethod
    def _list(cls, checks: list[dict[str, Any]], options: dict[str, Any], base: str) -> WidgetData:
        only_problems = bool(options.get("problems"))
        rows: list[tuple[int, str, dict[str, Any]]] = []
        for check in checks:
            state = str(check.get("status") or "")
            if only_problems and state not in ("down", "grace"):
                continue
            name = str(check.get("name") or check.get("slug") or "?")
            # A cron check has a schedule and no timeout; a simple one the other way round.
            rhythm = str(check.get("schedule") or "") or (duration_short(check.get("timeout")) if check.get("timeout") else "")
            # ⚠️ The state in words, not only in colour, and in the subtitle,
            # which is the part of a row that gets translated.
            word = "" if state == "up" else WORD.get(state, state)
            subtitle = " · ".join(part for part in (word, rhythm, str(check.get("tags") or "").strip()) if part)
            row: dict[str, Any] = {
                "title": name,
                "subtitle": subtitle,
                "status": COLOUR.get(state, "unknown"),
                "value": ago(check.get("last_ping")),
            }
            # Only a read-write key hands out the check's own id; a read-only
            # one has ``unique_key`` instead, and no page to link to.
            if check.get("uuid"):
                row["url"] = f"{base}/checks/{check['uuid']}/details/"
            rows.append((ORDER.get(state, 9), name.lower(), row))
        rows.sort(key=lambda entry: (entry[0], entry[1]))
        counts = cls._counts(checks)
        return WidgetData(
            status="bad" if counts["down"] else "warn" if counts["grace"] else "ok",
            items=[row for _order, _name, row in rows][: int(options.get("limit") or 12)],
            secondary=[{"label": "Up", "value": counts["up"] + counts["started"]}, {"label": "Late", "value": counts["grace"]},
                       {"label": "Down", "value": counts["down"]}],
            meta={"empty": "No late or down checks." if only_problems else "No checks yet."},
            metrics={"down": float(counts["down"])},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        late = fake.flicker("hc-scrub", tick, 0.7)
        checks = [
            {"name": "Nightly backup", "status": "up", "timeout": 86400, "tags": "backup", "last_ping": fake_time(tick, 3 * 3600)},
            {"name": "Database dump", "status": "up", "schedule": "0 3 * * *", "last_ping": fake_time(tick, 5 * 3600)},
            {"name": "Certificate renewal", "status": "up", "timeout": 604800, "tags": "web", "last_ping": fake_time(tick, 2 * 86400)},
            {"name": "Disk scrub", "status": "grace" if late else "up", "timeout": 604800, "tags": "nas", "last_ping": fake_time(tick, 7 * 86400 + 3600)},
            {"name": "Photo import", "status": "up", "timeout": 3600, "last_ping": fake_time(tick, 20 * 60)},
            {"name": "Offsite sync", "status": "paused", "timeout": 86400},
        ]
        if widget_kind == "summary":
            return self._summary(checks)
        return self._list(checks, options, "https://healthchecks.example.com")


def fake_time(tick: int, seconds_ago: int) -> float:
    """A moment for the demo, moving along with the ticks like the rest of it."""
    return time.time() - seconds_ago - (tick % 60)


ADAPTER = HealthchecksAdapter()
