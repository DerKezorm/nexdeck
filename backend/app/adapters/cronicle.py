"""Cronicle: scheduled events, the jobs running now, the latest runs and a button to run an event.

Measured on 27.10.2026 against bluet/cronicle-docker (Cronicle's own image
does not exist) with four shell events, one of them failing and one slow.

- ``X-API-Key: <key>`` on a GET works, as does ``api_key`` in the query or in
  a JSON body; the header keeps the key out of the logs. A key with only the
  privilege "Run Events" reads the schedule, the jobs and the history.
- **Every answer is HTTP 200.** The envelope has ``code``: ``0``, or a word
  (``api`` for a wrong key, ``session`` when there is none, ``event`` for an
  event that is not there, ``master`` while the server has not yet chosen
  itself the primary, which takes up to 60 seconds after a start, ``user``
  for a call only an administrator may make) and a ``description``. The
  ``code`` of a *job* in the history is a different thing: ``0`` is success.
- ``get_schedule``: ``rows`` (the events; ``timing`` is ``{}`` or lists of
  ``years``, ``months``, ``days``, ``weekdays`` (0 is Sunday, from the
  documentation), ``hours`` and ``minutes``, an absent list meaning every
  one) and ``list.length``.
- ``get_master_state``: ``state.jobCodes`` is the code of the **last run of
  each event**, ``state.stats`` the counts of completed and failed jobs. That
  these are of the current day is from Cronicle's documentation, not waited for.
- ``get_active_jobs``: ``jobs``, keyed by id, with ``time_start`` and ``now``
  of the server's clock; ``progress`` (0 to 1) only when the plugin reports it.
- ``get_history``: ``rows`` newest first, each with ``code``, ``elapsed`` in
  seconds, ``epoch`` of its end and, for a failure, a ``description``.
- ``run_event`` answers ``{"code": 0, "ids": [job id]}`` and runs a disabled
  event as well. That a key without the privilege is refused with a word
  containing "privilege" was not measured.
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
    ReadCommands,
    WidgetData,
    WidgetType,
    ago,
    allowed,
    base_url,
    duration_short,
)

WEEKDAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _numbers(value: Any) -> list[int]:
    return sorted(int(one) for one in value if isinstance(one, int | float) and not isinstance(one, bool)) if isinstance(value, list) else []


def when(timing: Any) -> list[str]:
    """How an event is timed, as the parts of a subtitle: a cadence and the times, or ``On demand``."""
    if not isinstance(timing, dict) or not any(_numbers(timing.get(key)) for key in ("years", "months", "days", "weekdays", "hours", "minutes")):
        return ["On demand"]
    hours, minutes = _numbers(timing.get("hours")), _numbers(timing.get("minutes"))
    days, weekdays, months, years = (_numbers(timing.get(key)) for key in ("days", "weekdays", "months", "years"))
    parts: list[str] = []
    if weekdays:
        parts.append(", ".join(WEEKDAYS[one % 7] for one in weekdays))
    if days:
        parts.append("day " + ", ".join(str(one) for one in days))
    if months:
        parts.append(", ".join(MONTHS[(one - 1) % 12] for one in months))
    if years:
        parts.append(", ".join(str(one) for one in years))
    if hours and minutes:
        stamps = [f"{hour:02d}:{minute:02d}" for hour in hours for minute in minutes]
        parts += [stamps[0] if len(stamps) == 1 else ", ".join(stamps[:3]) + (f" +{len(stamps) - 3}" if len(stamps) > 3 else "")]
    elif minutes:
        parts += ["Every hour", ", ".join(f":{minute:02d}" for minute in minutes[:4])]
    elif hours:
        parts += ["Every minute", ", ".join(f"{hour:02d}h" for hour in hours[:4])]
    else:
        parts += ["Every minute"]
    if not (weekdays or days or months or years) and (hours and minutes):
        parts.insert(0, "Daily")
    return parts


class CronicleAdapter(Adapter):
    kind = "cronicle"
    label = "Cronicle"
    category = "hosts"
    description = "Scheduled events of Cronicle, the jobs running now and how the latest runs ended, with a button to run an event."
    icon = "cronicle"
    docs_url = "https://github.com/jhuckaby/Cronicle/blob/master/docs/APIs.md"
    #: Measured against one Cronicle server (the bluet image) with four shell events.
    beta = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://cronicle:3012"),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="Admin > API Keys. Reading needs no privilege; the button to run an event needs Run Events."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    # Cronicle runs any of its calls from a GET (run_event, abort_job, delete_event): a card may ask the get_ ones.
    raw_read_commands = ReadCommands(after={"app": allowed(prefixes=("get_",))})
    widgets = (
        WidgetType(
            kind="overview",
            label="Cronicle overview",
            description="Events whose last run failed, jobs running now, and the jobs completed and failed today.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=60,
            metrics=("failing", "running"),
        ),
        WidgetType(
            kind="events",
            label="Events",
            description="Every scheduled event with its timing and how its last run ended, failing ones first, each with a button to run it.",
            renderer="list",
            default_size=(4, 3),
            min_size=(3, 2),
            refresh_seconds=120,
            metrics=("failing",),
            options=(Field("limit", "Entries", type="number", default=10), Field("only_failing", "Only the failing ones", type="bool", default=False)),
        ),
        WidgetType(
            kind="runs",
            label="Latest runs",
            description="The jobs running now with their progress, then the latest finished ones, failures with the reason Cronicle gives.",
            renderer="list",
            default_size=(4, 3),
            min_size=(3, 2),
            refresh_seconds=60,
            options=(Field("limit", "Entries", type="number", default=10), Field("only_failing", "Only the failing ones", type="bool", default=False)),
        ),
    )

    # -- asking Cronicle -------------------------------------------------------------

    async def _call(self, config: dict[str, Any], ctx: Context, name: str, params: dict[str, Any] | None = None,
                    post: dict[str, Any] | None = None, cache: float = 20) -> dict[str, Any]:
        headers = {"X-API-Key": str(config.get("api_key") or "").strip(), "Accept": "application/json"}
        url = f"{base_url(config)}/api/app/{name}"
        verify = not config.get("insecure")
        if post is not None:
            response = await ctx.request("POST", url, headers=headers, json_body=post, verify=verify, timeout=25, auth_errors=False)
        else:
            response = await ctx.request("GET", url, headers=headers, params=params, verify=verify, cache_seconds=cache, timeout=25, auth_errors=False)
        if response.status_code >= 400:
            raise AdapterError(f"Cronicle answered with HTTP {response.status_code}.", code="http_error",
                               hint="The URL is the address of Cronicle itself, usually port 3012.")
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("Cronicle did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a reverse proxy.") from error
        if not isinstance(answer, dict) or "code" not in answer:
            raise AdapterError("This address answers, but not the way Cronicle does.", code="not_cronicle")
        code, text = answer["code"], str(answer.get("description") or "")
        if code == 0:
            return answer
        if code in ("api", "session"):
            failure = AuthFailed("Cronicle rejected the API key." if config.get("api_key") else "Cronicle wants an API key.")
            failure.hint = "Make a key under Admin > API Keys and keep it active."
            raise failure
        if code == "master":
            raise AdapterError("Cronicle has not chosen its primary server yet.", code="not_master",
                               hint="After a start that takes up to a minute; this clears by itself.")
        if "privilege" in text.lower() or code == "user":
            failure = AuthFailed("This API key may not do that.")
            failure.hint = "Give the key the privilege Run Events under Admin > API Keys."
            raise failure
        raise AdapterError(f"Cronicle: {text or code}", code="cronicle_error")

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        answer = await self._call(config, ctx, "get_schedule", {"limit": 1}, cache=0)
        return f"Cronicle answers, {int((answer.get('list') or {}).get('length') or 0)} events scheduled."

    # -- the cards -----------------------------------------------------------------------

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        link = base_url(config)
        limit = max(1, min(100, int(options.get("limit") or 10)))
        if widget_kind == "runs":
            active = await self._call(config, ctx, "get_active_jobs")
            history = await self._call(config, ctx, "get_history", {"offset": 0, "limit": limit if not options.get("only_failing") else 100})
            return self.runs_card(active.get("jobs"), history.get("rows"), options, link)
        schedule = await self._call(config, ctx, "get_schedule", {"limit": 500})
        state = (await self._call(config, ctx, "get_master_state")).get("state")
        if widget_kind == "events":
            return self.events_card(schedule.get("rows"), state, options, link)
        active = await self._call(config, ctx, "get_active_jobs")
        return self.overview_card(schedule.get("rows"), state, active.get("jobs"), link)

    @staticmethod
    def _failing(events: Any, state: Any) -> int:
        codes = (state or {}).get("jobCodes") if isinstance(state, dict) else None
        codes = codes if isinstance(codes, dict) else {}
        return sum(1 for event in events or [] if isinstance(event, dict) and event.get("enabled") and codes.get(event.get("id")) not in (None, 0))

    @classmethod
    def overview_card(cls, events: Any, state: Any, active: Any, link: str | None = None) -> WidgetData:
        events = [one for one in events or [] if isinstance(one, dict)]
        failing = cls._failing(events, state)
        running = len(active) if isinstance(active, dict) else 0
        stats = (state or {}).get("stats") if isinstance(state, dict) else None
        stats = stats if isinstance(stats, dict) else {}
        return WidgetData(
            status="bad" if failing else "ok",
            primary={"label": "Failing", "value": failing},
            secondary=[{"label": "Events", "value": len(events)}, {"label": "Running", "value": running},
                       {"label": "Completed today", "value": int(stats.get("jobs_completed") or 0)},
                       {"label": "Failed today", "value": int(stats.get("jobs_failed") or 0)}],
            metrics={"failing": float(failing), "running": float(running)},
            link=link,
        )

    @classmethod
    def events_card(cls, events: Any, state: Any, options: dict[str, Any], link: str | None = None) -> WidgetData:
        codes = (state or {}).get("jobCodes") if isinstance(state, dict) else None
        codes = codes if isinstance(codes, dict) else {}
        rows = []
        for event in events or []:
            if not isinstance(event, dict):
                continue
            identifier = str(event.get("id") or "")
            enabled = bool(event.get("enabled"))
            code = codes.get(identifier)
            status = "unknown" if not enabled or code is None else ("ok" if code == 0 else "bad")
            if options.get("only_failing") and not (enabled and status == "bad"):
                continue
            word = "Disabled" if not enabled else ("Never run" if code is None else ("Failed" if code != 0 else ""))
            rows.append((status != "bad", not enabled, str(event.get("title") or "").casefold(), {
                "title": str(event.get("title") or identifier or "?"),
                "subtitle": " · ".join(part for part in (word, *when(event.get("timing"))) if part),
                "status": status,
                "actions": [{"id": "run", "label": "Run now", "icon": "play", "confirm": True, "params": {"id": identifier}}] if identifier else [],
            }))
        # Failing first, disabled ones last.
        rows.sort(key=lambda entry: entry[:3])
        limit = max(1, min(100, int(options.get("limit") or 10)))
        failing = cls._failing(events, state)
        return WidgetData(
            status="bad" if failing else "ok",
            items=[entry[3] for entry in rows[:limit]],
            secondary=[{"label": "Failing", "value": failing}, {"label": "Events", "value": len([one for one in events or [] if isinstance(one, dict)])}],
            metrics={"failing": float(failing)},
            link=link,
            meta={"empty": "No event fails." if options.get("only_failing") else "No event is scheduled."},
        )

    @staticmethod
    def runs_card(active: Any, history: Any, options: dict[str, Any], link: str | None = None) -> WidgetData:
        rows = []
        only_failing = bool(options.get("only_failing"))
        for job in (active.values() if isinstance(active, dict) and not only_failing else []):
            if not isinstance(job, dict):
                continue
            started = float(job.get("time_start") or 0)
            elapsed = max(0.0, float(job.get("now") or started) - started)
            row: dict[str, Any] = {
                "title": str(job.get("event_title") or job.get("event") or "?"),
                "subtitle": " · ".join(part for part in ("Running", duration_short(elapsed)) if part),
                "status": "ok",
                "value": "",
            }
            if isinstance(job.get("progress"), int | float) and 0 <= job["progress"] <= 1:
                row["progress"] = round(100 * float(job["progress"]), 1)
            rows.append(row)
        for run in history or []:
            if not isinstance(run, dict) or (only_failing and run.get("code") in (0, None)):
                continue
            failed = run.get("code") not in (0, None)
            reason = " ".join(str(run.get("description") or "").split())[:120]
            rows.append({
                "title": str(run.get("event_title") or run.get("event") or "?"),
                "subtitle": " · ".join(part for part in ("Failed" if failed else "", reason, duration_short(run.get("elapsed"))) if part),
                "status": "bad" if failed else "ok",
                "value": ago(run.get("epoch")),
            })
        limit = max(1, min(100, int(options.get("limit") or 10)))
        failed_count = sum(1 for row in rows if row["status"] == "bad")
        return WidgetData(
            status="warn" if failed_count else "ok",
            items=rows[:limit],
            secondary=[{"label": "Running", "value": len(active) if isinstance(active, dict) else 0}],
            link=link,
            meta={"empty": "No run has failed lately." if only_failing else "Nothing has run yet."},
        )

    # -- the button ----------------------------------------------------------------------------

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        if action_id != "run":
            raise AdapterError("Unknown action.", code="no_such_action")
        identifier = str(params.get("id") or "").strip()
        if not identifier or len(identifier) > 64 or not identifier.isalnum():
            raise AdapterError("That is not the id of an event.", code="bad_param")
        try:
            await self._call(config, ctx, "run_event", post={"id": identifier})
        except AdapterError as error:
            if error.code == "cronicle_error" and "locate event" in error.message:
                raise AdapterError("Cronicle has no such event any more.", code="not_found") from error
            # An event allows as many jobs at once as its setting says, one by default.
            if error.code == "cronicle_error" and "already running" in error.message:
                raise AdapterError("This event is running already.", code="already_running",
                                   hint="Cronicle starts another run once the one going has ended, or when the event allows more at once.") from error
            raise
        ctx.forget_answers()
        return "The event is running."

    # -- demo ------------------------------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = time.time() - tick % 60
        broke = (tick // 300) % 3 == 0
        events = [
            {"id": "e1", "title": "Nightly backup", "enabled": 1, "timing": {"hours": [3], "minutes": [15]}},
            {"id": "e2", "title": "Cleanup temp files", "enabled": 1, "timing": {"minutes": [0, 30]}},
            {"id": "e3", "title": "Weekly report", "enabled": 1, "timing": {"weekdays": [1], "hours": [6], "minutes": [0]}},
            {"id": "e4", "title": "Old sync", "enabled": 0, "timing": {}},
        ]
        state = {"jobCodes": {"e1": 0, "e2": 1 if broke else 0, "e3": 0, "e4": 0}, "stats": {"jobs_completed": 41 + tick // 120, "jobs_failed": 3 if broke else 0}}
        active = {"j1": {"event_title": "Weekly report", "time_start": now - 40 - tick % 60, "now": now, "progress": min(0.95, (40 + tick % 60) / 120)}}
        if widget_kind == "events":
            return self.events_card(events, state, options)
        if widget_kind == "runs":
            history = [
                {"event_title": "Cleanup temp files", "code": 1 if broke else 0, "epoch": now - 900, "elapsed": 4.2, "description": "Script exited with code: 1" if broke else ""},
                {"event_title": "Nightly backup", "code": 0, "epoch": now - 30000, "elapsed": 912.0},
                {"event_title": "Cleanup temp files", "code": 0, "epoch": now - 2700, "elapsed": 3.9},
            ]
            return self.runs_card(active, history, options)
        return self.overview_card(events, state, active if fake.flicker("cronicle-running", tick, 0.7) else {})


ADAPTER = CronicleAdapter()
