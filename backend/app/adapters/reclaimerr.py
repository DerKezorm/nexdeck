"""Reclaimerr: what its clean-up rules have marked for deletion, and when it goes.

Built for issue #31 from Reclaimerr's external API (``/api/v1``, documented at
https://jessielw.github.io/Reclaimerr/reference/api/) and its route handlers
and answer models in the source of 0.5.5, then measured against a live
Reclaimerr 0.5.5 with a Jellyfin of made-up titles behind it.

- Only the external API. A token made by an administrator under Settings >
  Integrations rides as ``Authorization: Bearer rcl_…``. The cookie routes
  under ``/api/…`` are Reclaimerr's own interface; its documentation rules
  them out for integrations, and nexdeck never calls them.
- A token carries scopes. ``GET /api/v1`` names them and answers with any
  scope at all, so the test and every card ask it first; a card that misses
  one says which in words, instead of a bare refusal. A missing scope comes
  back as 403 "API token requires the … scope". ``candidates:manage``,
  ``protections:manage`` and ``tasks:run`` include their read scope.
- A candidate carries its deadline (``auto_delete_eligible_at``) and its
  state, but no size. The size lives on the movie or the whole series
  (``media:read``). Measured: with Jellyfin every movie candidate is a
  ``version`` (one file of a movie), and a movie's size is the sum of its
  files; a version is given the movie's size, which is its own as long as
  the movie has one file. A season or an episode has none.
- Automatic deletion is off until an administrator opts a rule in, so on a
  fresh Reclaimerr every candidate is ``disabled``: marked for deletion by
  hand. The cards count those as marked too, and only the ones with a
  running timer have a deadline.
- What users vote for deletion is not in the external API. A candidate only
  says that a delete request of a user is open (``pending_delete_request``
  among its ``blockers``), and the row shows that.
- The buttons act through the external API as well: postpone, reset the
  timer, keep (cancel the automatic deletion) and protect need
  ``candidates:manage``; running a task needs ``tasks:run``. A task that
  deletes or writes to Radarr and Sonarr never gets a button: only the ones
  in :data:`RUNNABLE` do, so a task a later Reclaimerr adds has none either.
- What was deleted or moved comes from the event feed (``events:read``),
  read by the overview card and told as "media was cleaned up".
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from . import demo as fake
from .base import (
    Action,
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Detected,
    Field,
    WidgetData,
    WidgetType,
    ago,
    base_url,
    human_bytes,
)

#: What a scope also covers: the manage and run scopes include reading.
IMPLIED = {
    "candidates:read": "candidates:manage",
    "protections:read": "protections:manage",
    "tasks:read": "tasks:run",
}

#: The states of a candidate in which it is on its way out by itself.
LEAVING = ("scheduled", "eligible", "postponed")
#: Marked for deletion: by itself, or by an administrator's hand. Not the
#: ones somebody chose to keep.
MARKED = (*LEAVING, "disabled")

#: What a candidate is, in words; Reclaimerr's own ``scope``.
KINDS = {"movie": "Movie", "version": "Movie version", "series": "Whole series", "season": "Season", "episode": "Episode"}

#: Why a candidate is held back, in words; Reclaimerr's own ``blockers``.
BLOCKERS = {
    "protected": "Protected",
    "pending_protection_request": "Protection requested",
    "pending_delete_request": "Delete request open",
}

#: The tasks a button may start. ⚠️ An allowlist: deleting candidates,
#: tagging them in Radarr and Sonarr and the weekly housekeeping change
#: things, and a task a later Reclaimerr adds is not on it until someone
#: has read what it does.
RUNNABLE = frozenset({
    "sync_media", "sync_media_libraries", "sync_linked_data", "refresh_playback_history",
    "scan_cleanup_candidates", "check_app_updates", "imdb_ratings_refresh",
    "anilist_ratings_refresh", "mdblist_ratings_refresh", "omdb_ratings_refresh",
})

#: A task's state in words, and its colour.
TASK_STATES = {
    "scheduled": ("Scheduled", "ok"),
    "queued": ("Queued", "ok"),
    "running": ("Running", "ok"),
    "completed": ("Done", "ok"),
    "error": ("Failed", "bad"),
    "disabled": ("Disabled", "unknown"),
}

SHOW = (("marked", "Marked for deletion"), ("leaving", "Leaving by themselves"), ("all", "All candidates"))
POSTPONE = (("7", "7 days"), ("14", "14 days"), ("30", "30 days"))
TASKS_SHOWN = (("enabled", "Enabled"), ("all", "All"))

#: How long the token's scopes are believed: they change only with a new token.
SCOPE_SECONDS = 300
#: Sizes change with the library, not by the minute.
SIZE_SECONDS = 1800
#: At most this many titles are asked for their size in one go.
SIZE_LIMIT = 60
#: How far back the overview looks for deleted and moved titles.
EVENT_WINDOW = timedelta(days=1)
REMOVED_TYPES = ("candidate.deleted", "candidate.moved")

_SCOPE_REFUSAL = re.compile(r"requires the ([a-z]+:[a-z]+) scope")


def lacks(scope: str) -> str:
    """The sentence a card says for a scope its token does not have."""
    return f"The API token lacks the scope {scope}."


def _has(granted: frozenset[str], scope: str) -> bool:
    return scope in granted or IMPLIED.get(scope, "") in granted


def _when(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _until(moment: datetime | None, now: datetime) -> str:
    """How long until a moment: "in 5 d", or "due" once it has passed."""
    if moment is None:
        return ""
    seconds = (moment - now).total_seconds()
    if seconds <= 0:
        return "due"
    if seconds < 3600:
        return f"in {max(1, round(seconds / 60))} min"
    if seconds < 48 * 3600:
        return f"in {round(seconds / 3600)} h"
    return f"in {round(seconds / 86400)} d"


def _every(task: dict[str, Any]) -> str:
    """A task's schedule in words: every so often, a cron line, or by hand."""
    kind = str(task.get("schedule_type") or "")
    value = str(task.get("schedule_value") or "")
    if kind == "manual" or not value:
        return "Manual"
    if kind == "interval":
        try:
            seconds = int(value)
        except ValueError:
            return value
        if seconds % 3600 == 0:
            return f"every {seconds // 3600} h"
        return f"every {max(1, round(seconds / 60))} min"
    return value


def _limit(options: dict[str, Any], default: int = 8) -> int:
    try:
        wanted = int(options.get("limit") or default)
    except (TypeError, ValueError):
        wanted = default
    return max(1, min(50, wanted))


def _hours(options: dict[str, Any]) -> int:
    try:
        wanted = int(options.get("stale_hours") or 48)
    except (TypeError, ValueError):
        wanted = 48
    return max(1, min(24 * 60, wanted))


def _title(candidate: dict[str, Any]) -> str:
    """A candidate's name; Reclaimerr already adds S01 or S01E02 to a season or an episode."""
    title = str(candidate.get("title") or "?")
    year = candidate.get("year")
    if candidate.get("scope") in ("movie", "version", "series") and year:
        return f"{title} ({year})"
    return title


def _space(marked: list[dict[str, Any]], sizes: dict[int, int | None]) -> tuple[int, bool]:
    """The space the marked titles free, and whether some of it is not known.

    Each movie and each series counts once, however many of its files or
    seasons are marked. A season or an episode of a series that is marked
    as a whole is inside that size already; any other one is a gap.
    """
    total = 0
    gaps = False
    counted: set[tuple[str, int]] = set()
    whole_series = {int(c.get("media_id") or 0) for c in marked if c.get("scope") == "series"}
    for candidate in marked:
        scope = candidate.get("scope")
        media_id = int(candidate.get("media_id") or 0)
        if scope in ("season", "episode"):
            gaps = gaps or media_id not in whole_series
            continue
        key = ("series" if scope == "series" else "movies", media_id)
        if key in counted:
            continue
        counted.add(key)
        size = sizes.get(int(candidate.get("id") or 0))
        if size is None:
            gaps = True
        else:
            total += size
    return total, gaps


def _buttons(state: str, number: int, days: int) -> list[Action]:
    """What a row offers, by where the title stands.

    A deadline that runs can be moved, stopped or started again; a title kept
    from automatic deletion can be given its timer back; one marked by hand
    has no timer to touch. Each can be protected for good.
    """
    protect = Action(id="protect", label="Protect", icon="shield", confirm=True, params={"id": number})
    reset = Action(id="reset", label="Reset timer", icon="rotate-cw", confirm=True, params={"id": number})
    if state in LEAVING:
        return [Action(id="postpone", label=f"Postpone {days} d", icon="clock", params={"id": number, "days": days}),
                Action(id="keep", label="Keep", icon="check", confirm=True, params={"id": number}), reset, protect]
    if state == "canceled":
        return [reset, protect]
    return [protect]


class ReclaimerrAdapter(Adapter):
    kind = "reclaimerr"
    label = "Reclaimerr"
    category = "media"
    description = "What Reclaimerr's clean-up rules have marked for deletion, when each title goes and how much space it frees, and its tasks."
    icon = "reclaimerr"
    docs_url = "https://jessielw.github.io/Reclaimerr/reference/api/"
    keywords = ("clean-up", "cleanup", "deletion", "Maintainerr")
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://reclaimerr:8000"),
        Field("api_key", "API token", type="password", secret=True, required=True,
              help="An rcl_ token from Settings > Integrations in Reclaimerr. Reading needs system:read, candidates:read, "
                   "media:read, protections:read, tasks:read and events:read; the buttons need candidates:manage and tasks:run."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="overview",
            label="Reclaimerr overview",
            description="How many titles are marked for deletion, the space they free, the next automatic deletion and how many are protected; amber when the last sync or scan is old or a task failed.",
            renderer="value",
            default_size=(3, 2),
            min_size=(1, 1),
            refresh_seconds=300,
            metrics=("candidates", "reclaimable"),
            options=(
                Field("stale_hours", "Old after (hours)", type="number", default=48,
                      help="A sync or a scan longer ago than this turns the card amber."),
            ),
        ),
        WidgetType(
            kind="leaving",
            label="Leaving soon",
            description="The titles marked for deletion, the nearest deadline first, with their size and the days left; a delete request of a user is shown on its row.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=300,
            options=(
                Field("show", "Show", type="select", default="marked", options=SHOW),
                Field("limit", "Entries", type="number", default=8, help="Between 1 and 50."),
                Field("postpone", "Postpone by", type="select", default="7", options=POSTPONE),
            ),
        ),
        WidgetType(
            kind="tasks",
            label="Tasks",
            description="Reclaimerr's tasks with their schedule, the last run and the next one; a failed one turns red.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=120,
            options=(Field("show", "Show", type="select", default="enabled", options=TASKS_SHOWN),),
        ),
    )

    # -- talking to Reclaimerr -------------------------------------------------

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"Authorization": f"Bearer {str(config.get('api_key') or '').strip()}", "Accept": "application/json"}

    async def _call(self, method: str, config: dict[str, Any], ctx: Context, path: str, *,
                    params: dict[str, Any] | None = None, body: Any = None, cache: float = 0) -> Any:
        response = await ctx.request(
            method, f"{base_url(config)}/api/v1{path}", headers=self._headers(config), params=params,
            json_body=body, verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        detail = ""
        if response.status_code >= 400:
            try:
                detail = str((response.json() or {}).get("detail") or "")
            except (ValueError, AttributeError):
                detail = ""
        if response.status_code == 401:
            raise AuthFailed(f"Reclaimerr turned the token away: {detail}" if detail else "Reclaimerr turned the token away.")
        if response.status_code == 403:
            found = _SCOPE_REFUSAL.search(detail)
            if found:
                raise AdapterError(lacks(found.group(1)), code="missing_scope",
                                   hint="Give the token that scope under Settings > Integrations in Reclaimerr.")
            raise AuthFailed()
        if response.status_code == 404 and path == "":
            raise AdapterError("This Reclaimerr has no external API under /api/v1.", code="http_error",
                               hint="Check the URL, or update Reclaimerr.")
        if response.status_code >= 400:
            raise AdapterError(f"Reclaimerr answered with HTTP {response.status_code}: {detail}" if detail
                               else f"Reclaimerr answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Reclaimerr did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a reverse proxy.") from error

    async def _scopes(self, config: dict[str, Any], ctx: Context, cache: float = SCOPE_SECONDS) -> frozenset[str]:
        found = await self._call("GET", config, ctx, "", cache=cache)
        granted = found.get("granted_scopes") if isinstance(found, dict) else None
        return frozenset(str(scope) for scope in granted or [])

    async def _candidates(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page = 1
        while True:
            found = await self._call("GET", config, ctx, "/candidates", params={"page": page, "per_page": 200}, cache=60)
            items = found.get("items") if isinstance(found, dict) else None
            rows += [item for item in items or [] if isinstance(item, dict)]
            # Ten pages are two thousand titles; a library that marks more has
            # its overview counted from those.
            if not isinstance(found, dict) or page >= int(found.get("total_pages") or 0) or page >= 10:
                return rows
            page += 1

    async def _sizes(self, config: dict[str, Any], ctx: Context, candidates: list[dict[str, Any]]) -> dict[int, int | None]:
        """The size of each candidate that is a whole movie or a whole series, by candidate id."""
        wanted: dict[tuple[str, int], list[int]] = {}
        for candidate in candidates:
            scope = candidate.get("scope")
            if scope not in ("movie", "version", "series") or not candidate.get("media_id"):
                continue
            path = "series" if scope == "series" else "movies"
            wanted.setdefault((path, int(candidate["media_id"])), []).append(int(candidate.get("id") or 0))
        gate = asyncio.Semaphore(4)

        async def one(path: str, media_id: int) -> int | None:
            async with gate:
                try:
                    found = await self._call("GET", config, ctx, f"/{path}/{media_id}", cache=SIZE_SECONDS)
                except AdapterError as error:
                    if error.code == "missing_scope":
                        raise
                    return None
            size = found.get("size_bytes") if isinstance(found, dict) else None
            return int(size) if isinstance(size, int | float) and size >= 0 else None

        keys = list(wanted)[:SIZE_LIMIT]
        answers = await asyncio.gather(*(one(path, media_id) for path, media_id in keys))
        sizes: dict[int, int | None] = {}
        for key, size in zip(keys, answers, strict=True):
            for candidate_id in wanted[key]:
                sizes[candidate_id] = size
        return sizes

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        granted = await self._scopes(config, ctx, cache=0)
        if not granted:
            raise AdapterError("The token has no scope at all.", code="missing_scope",
                               hint="Give it at least candidates:read under Settings > Integrations in Reclaimerr.")
        version = ""
        if _has(granted, "system:read"):
            system = await self._call("GET", config, ctx, "/system")
            if isinstance(system, dict):
                version = f" {system.get('version')}" if system.get("version") else ""
        missing = [scope for scope in ("system:read", "candidates:read", "media:read", "protections:read", "tasks:read", "events:read")
                   if not _has(granted, scope)]
        said = f"Reclaimerr{version} answers; the token has {', '.join(sorted(granted))}."
        return f"{said} Missing for every card: {', '.join(missing)}." if missing else said

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        granted = await self._scopes(config, ctx)
        if widget_kind == "tasks":
            return await self._tasks(config, ctx, granted, options)
        if not _has(granted, "candidates:read"):
            raise AdapterError(lacks("candidates:read"), code="missing_scope",
                               hint="Give the token that scope under Settings > Integrations in Reclaimerr.")
        candidates = await self._candidates(config, ctx)
        # Only the titles the card shows are asked for their size.
        if widget_kind == "overview":
            shown = [c for c in candidates if c.get("auto_delete_state") in MARKED]
        else:
            shown = self._shown(options, candidates)
        sizes = await self._sizes(config, ctx, shown) if _has(granted, "media:read") else {}
        if widget_kind == "overview":
            return await self._overview(config, ctx, granted, options, candidates, sizes)
        return self._leaving(granted, options, candidates, sizes)

    @staticmethod
    def _shown(options: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The rows of the leaving card: the nearest deadline first, then the
        ones marked by hand, then the kept ones; as many as it shows."""
        wanted = {"all": None, "leaving": LEAVING}.get(str(options.get("show") or ""), MARKED)
        shown = [c for c in candidates if wanted is None or c.get("auto_delete_state") in wanted]
        far = datetime.max.replace(tzinfo=UTC)

        def order(candidate: dict[str, Any]) -> tuple[int, datetime, int]:
            state = candidate.get("auto_delete_state")
            rank = 0 if state in LEAVING else 1 if state == "disabled" else 2
            deadline = _when(candidate.get("auto_delete_eligible_at")) if rank == 0 else None
            return rank, deadline or far, int(candidate.get("id") or 0)

        shown.sort(key=order)
        return shown[:_limit(options)]

    async def _overview(self, config: dict[str, Any], ctx: Context, granted: frozenset[str], options: dict[str, Any],
                        candidates: list[dict[str, Any]], sizes: dict[int, int | None]) -> WidgetData:
        now = datetime.now(UTC)
        marked = [c for c in candidates if c.get("auto_delete_state") in MARKED]
        leaving = [c for c in marked if c.get("auto_delete_state") in LEAVING]
        reasons: list[str] = []
        notes: list[str] = []
        secondary: list[dict[str, Any]] = []

        if _has(granted, "media:read"):
            total, gaps = _space(marked, sizes)
            space = f"at least {human_bytes(total)}" if gaps else human_bytes(total)
            secondary.append({"label": "Space to free", "value": space})
        else:
            total = None
            notes.append(lacks("media:read"))

        deadlines = sorted(d for d in (_when(c.get("auto_delete_eligible_at")) for c in leaving if not c.get("blockers")) if d)
        secondary.append({"label": "Next deletion", "value": _until(deadlines[0], now) if deadlines else "nothing planned"})

        if _has(granted, "protections:read"):
            found = await self._call("GET", config, ctx, "/protections", params={"per_page": 1}, cache=300)
            secondary.append({"label": "Protected", "value": int(found.get("total") or 0) if isinstance(found, dict) else 0})
        else:
            notes.append(lacks("protections:read"))

        stale = timedelta(hours=_hours(options))
        if _has(granted, "system:read"):
            system = await self._call("GET", config, ctx, "/system", cache=60)
            system = system if isinstance(system, dict) else {}
            if system.get("has_main_media_server") is False:
                reasons.append("No main media server is set.")
            for key, what in (("last_media_sync_at", "media sync"), ("last_candidate_scan_at", "candidate scan")):
                moment = _when(system.get(key))
                if moment is None:
                    reasons.append(f"No {what} has finished yet.")
                elif now - moment > stale:
                    reasons.append(f"Last {what} {ago(moment.isoformat())} ago.")
        else:
            notes.append(lacks("system:read"))

        if _has(granted, "tasks:read"):
            found = await self._call("GET", config, ctx, "/tasks", cache=60)
            for task in (found.get("items") if isinstance(found, dict) else None) or []:
                if task.get("status") == "error":
                    reasons.append(f"{task.get('name') or task.get('id')} failed.")
        else:
            notes.append(lacks("tasks:read"))

        meta: dict[str, Any] = {"status_reason": " · ".join(reasons + notes)}
        if _has(granted, "events:read"):
            meta["removed"] = await self._removed(config, ctx, now)

        metrics = {"candidates": float(len(marked))}
        if total is not None:
            metrics["reclaimable"] = float(total)
        return WidgetData(
            status="warn" if reasons else "ok",
            primary={"label": "Candidates", "value": len(marked)},
            secondary=secondary,
            metrics=metrics,
            meta=meta,
        )

    async def _removed(self, config: dict[str, Any], ctx: Context, now: datetime) -> list[dict[str, Any]]:
        """What Reclaimerr deleted or moved in the last day, oldest first, for :meth:`detect`."""
        found: list[dict[str, Any]] = []
        since = (now - EVENT_WINDOW).isoformat()
        for kind in REMOVED_TYPES:
            cursor = None
            for _page in range(5):
                params: dict[str, Any] = {"event_type": kind, "occurred_after": since, "limit": 200}
                if cursor:
                    params["cursor"] = cursor
                feed = await self._call("GET", config, ctx, "/events", params=params, cache=60)
                if not isinstance(feed, dict):
                    break
                for event in feed.get("items") or []:
                    candidate = (event.get("payload") or {}).get("candidate") or {}
                    found.append({"id": str(event.get("id") or ""), "type": kind, "title": _title(candidate) if candidate else "A title"})
                cursor = feed.get("next_cursor")
                if not feed.get("has_more") or not cursor:
                    break
        return [event for event in found if event["id"]]

    def _leaving(self, granted: frozenset[str], options: dict[str, Any], candidates: list[dict[str, Any]],
                 sizes: dict[int, int | None]) -> WidgetData:
        now = datetime.now(UTC)
        show = str(options.get("show") or "marked")
        manage = _has(granted, "candidates:manage")
        days = str(options.get("postpone") or "7")
        days = days if days in {value for value, _label in POSTPONE} else "7"
        rows = []
        for candidate in self._shown(options, candidates):
            number = int(candidate.get("id") or 0)
            state = str(candidate.get("auto_delete_state") or "")
            deadline = _when(candidate.get("auto_delete_eligible_at"))
            blockers = [BLOCKERS.get(str(b), str(b).replace("_", " ").capitalize()) for b in candidate.get("blockers") or []]
            parts = [KINDS.get(str(candidate.get("scope")), "Media")]
            size = sizes.get(number)
            if size is not None:
                parts.append(human_bytes(size))
            if candidate.get("delete_operation") == "move":
                parts.append("Moved, not deleted")
            parts += blockers
            if candidate.get("last_delete_error"):
                parts.append("Last deletion failed")
            if state == "canceled":
                value, status = "Kept", "unknown"
            elif state == "disabled":
                # Marked, and waiting for an administrator: no deadline runs.
                value = "Manual"
                status = "bad" if candidate.get("last_delete_error") else "warn" if blockers else "ok"
            else:
                value = _until(deadline, now)
                if state == "postponed":
                    value = f"Postponed, {value}" if value != "due" else "Postponed, due"
                due_soon = deadline is not None and deadline - now < timedelta(days=3)
                status = "warn" if blockers or due_soon or candidate.get("last_delete_error") else "ok"
                if candidate.get("last_delete_error"):
                    status = "bad"
            row: dict[str, Any] = {
                "id": number,
                "title": _title(candidate),
                "subtitle": " · ".join(parts),
                "value": value,
                "status": status,
            }
            if manage and number:
                row["actions"] = _buttons(state, number, int(days))
            rows.append(row)
        meta: dict[str, Any] = {"empty": {"all": "No candidate.", "leaving": "No title leaves by itself."}.get(
            show, "No title is marked for deletion.")}
        if not manage:
            meta["notice"] = "The buttons need the scope candidates:manage."
        if not _has(granted, "media:read"):
            meta["notice"] = " · ".join(filter(None, [meta.get("notice", ""), lacks("media:read")]))
        return WidgetData(
            status="warn" if any(row["status"] == "bad" for row in rows) else "ok",
            items=rows,
            secondary=[{"label": "Candidates", "value": sum(1 for c in candidates if c.get("auto_delete_state") in MARKED)}],
            meta=meta,
        )

    async def _tasks(self, config: dict[str, Any], ctx: Context, granted: frozenset[str], options: dict[str, Any]) -> WidgetData:
        if not _has(granted, "tasks:read"):
            raise AdapterError(lacks("tasks:read"), code="missing_scope",
                               hint="Give the token that scope under Settings > Integrations in Reclaimerr.")
        found = await self._call("GET", config, ctx, "/tasks", cache=20)
        tasks = [task for task in ((found.get("items") if isinstance(found, dict) else None) or []) if isinstance(task, dict)]
        if options.get("show") != "all":
            tasks = [task for task in tasks if task.get("enabled")]
        run = _has(granted, "tasks:run")
        now = datetime.now(UTC)
        rows = []
        failed = 0
        for task in tasks:
            key = str(task.get("id") or "")
            state = str(task.get("status") or "")
            word, status = TASK_STATES.get(state, (state.capitalize() or "?", "unknown"))
            last = _when(task.get("last_run_at"))
            parts = [_every(task)]
            if last is not None:
                parts.append(f"ran {ago(last.isoformat())} ago")
            if state == "error":
                failed += 1
                if task.get("error"):
                    parts.append(str(task["error"])[:160])
            following = _when(task.get("next_run_at"))
            value = _until(following, now) if state in ("scheduled", "completed") and following else word
            if state == "scheduled" and not following:
                # A task run by hand only: nothing is due, and it is not running.
                value = "Idle"
            row: dict[str, Any] = {
                "id": key,
                "title": str(task.get("name") or key),
                "subtitle": " · ".join(parts),
                "value": value,
                "status": status,
            }
            if run and key in RUNNABLE and task.get("can_run") and state not in ("running", "queued"):
                row["actions"] = [Action(id="run", label="Run now", icon="play", params={"task": key})]
            rows.append(row)
        meta: dict[str, Any] = {"empty": "No task is enabled." if options.get("show") != "all" else "No task."}
        if not run:
            meta["notice"] = "The buttons need the scope tasks:run."
        if found.get("has_main_server") is False if isinstance(found, dict) else False:
            meta["status_reason"] = "No main media server is set."
        return WidgetData(status="bad" if failed else "ok", items=rows, meta=meta)

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        if widget_kind == "tasks" and action_id == "run":
            task = str(params.get("task") or "")
            if task not in RUNNABLE:
                raise AdapterError("That task is not started from nexdeck.", code="no_such_action")
            answer = await self._call("POST", config, ctx, f"/tasks/{task}/run")
            ctx.forget_answers()
            if isinstance(answer, dict) and answer.get("already_active"):
                return "The task is running already."
            return "The task is queued."
        if widget_kind != "leaving" or action_id not in ("postpone", "keep", "reset", "protect"):
            raise AdapterError("Unknown action.", code="no_such_action")
        try:
            number = int(params.get("id") or 0)
        except (TypeError, ValueError):
            number = 0
        if number <= 0:
            raise AdapterError("No title was named.", code="missing_param")
        reason = "From nexdeck"
        if action_id == "postpone":
            try:
                days = int(params.get("days") or 7)
            except (TypeError, ValueError):
                days = 7
            days = max(1, min(365, days))
            # Reclaimerr takes a moment, and only one after the current
            # deadline: counted from whichever is later, now or the deadline.
            current = await self._call("GET", config, ctx, f"/candidates/{number}")
            deadline = _when(current.get("auto_delete_eligible_at")) if isinstance(current, dict) else None
            start = max(deadline or datetime.now(UTC), datetime.now(UTC))
            until = start + timedelta(days=days)
            await self._call("POST", config, ctx, f"/candidates/{number}/postpone",
                             body={"until": until.isoformat(), "reason": reason})
            ctx.forget_answers()
            return f"Postponed until {until.date().isoformat()}."
        path = {"keep": "cancel", "reset": "reset-timer", "protect": "protect"}[action_id]
        await self._call("POST", config, ctx, f"/candidates/{number}/{path}", body={"reason": reason})
        ctx.forget_answers()
        return {"keep": "Kept: it is not deleted by itself.", "reset": "The timer starts again.",
                "protect": "Protected for good."}[action_id]

    def detect(self, widget_kind: str, before: WidgetData | None, after: WidgetData,
               options: dict[str, Any]) -> list[Detected]:
        """A title Reclaimerr deleted or moved since the last look.

        ⚠️ Only from the event feed, never from a candidate leaving the list:
        a candidate also leaves when it is kept, protected or no longer
        matches a rule. And only when the feed was read both times, so a new
        card or one that was broken does not tell the whole last day at once.
        """
        if widget_kind != "overview" or before is None or before.error:
            return []
        if not isinstance(before.meta.get("removed"), list) or not isinstance(after.meta.get("removed"), list):
            return []
        seen = {str(event.get("id")) for event in before.meta["removed"]}
        fresh = [event for event in after.meta["removed"] if str(event.get("id")) not in seen]
        if len(fresh) > 5:
            return [Detected(
                event="media_removed",
                title=f"Reclaimerr cleaned up {len(fresh)} titles",
                body=", ".join(str(event.get("title")) for event in fresh[:5]) + ", …",
                key=f"media_removed:rcl:{fresh[-1].get('id')}",
            )]
        return [
            Detected(
                event="media_removed",
                title=f"{event.get('title')} was {'moved' if event.get('type') == 'candidate.moved' else 'deleted'}",
                body="Reclaimerr cleaned it up.",
                key=f"media_removed:rcl:{event.get('id')}",
            )
            for event in fresh
        ]

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "overview":
            leaving = 9 + int(fake.walk("rcl-leaving", tick, 0, 4))
            return WidgetData(
                status="ok",
                primary={"label": "Candidates", "value": leaving},
                secondary=[{"label": "Space to free", "value": "at least 312.4 GB"},
                           {"label": "Next deletion", "value": "in 2 d"}, {"label": "Protected", "value": 14}],
                metrics={"candidates": float(leaving), "reclaimable": 312.4 * 1024 ** 3},
                meta={"status_reason": ""},
            )
        if widget_kind == "tasks":
            rows = [("Sync Media", "0 3 * * *", "ran 7 h ago", "in 17 h", "ok"),
                    ("Scan Cleanup Candidates", "0 10 * * *", "ran 1 h ago", "in 23 h", "ok"),
                    ("Refresh Playback Data", "every 15 min", "ran 4 min ago", "in 11 min", "ok"),
                    ("Delete Cleanup Candidates", "0 2 * * *", "ran 8 h ago", "Failed", "bad")]
            return WidgetData(status="bad", items=[
                {"id": name, "title": name, "subtitle": f"{every} · {last}", "value": value, "status": status,
                 "actions": [] if name.startswith("Delete") else [Action(id="run", label="Run now", icon="play", params={"task": name})]}
                for name, every, last, value, status in rows], meta={"empty": "No task is enabled."})
        rows = [("The Copper Lantern (2019)", "Movie · 8.4 GB", "in 2 d", "warn"),
                ("Northbound Tides S02", "Season · Delete request open", "in 4 d", "warn"),
                ("Harbour Lights (2021)", "Movie · 21.7 GB", "in 9 d", "ok"),
                ("Glass Meadow (2020)", "Whole series · 46.2 GB", "Postponed, in 23 d", "ok"),
                ("Quiet Orchard (2017)", "Movie · 4.1 GB · Protected", "in 12 d", "warn")]
        days = str(options.get("postpone") or "7")
        return WidgetData(status="ok", items=[
            {"id": index, "title": title, "subtitle": subtitle, "value": value, "status": status, "actions": [
                Action(id="postpone", label=f"Postpone {days} d", icon="clock", params={"id": index, "days": int(days)}),
                Action(id="keep", label="Keep", icon="check", confirm=True, params={"id": index}),
                Action(id="reset", label="Reset timer", icon="rotate-cw", confirm=True, params={"id": index}),
                Action(id="protect", label="Protect", icon="shield", confirm=True, params={"id": index})]}
            for index, (title, subtitle, value, status) in enumerate(rows, start=1)],
            secondary=[{"label": "Candidates", "value": 11}], meta={"empty": "No title is marked for deletion."})


ADAPTER = ReclaimerrAdapter()
