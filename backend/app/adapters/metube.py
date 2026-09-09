"""MeTube: hand it a video address and it fetches the file.

The point of this adapter is one card with a field and a button. Everything
else nexdeck can be told to do is picked from a list the service handed over;
this is the one place where the value comes from whoever is standing in front
of the board. What that means for the guard of 0.2.0 is written down at
:class:`~app.adapters.base.Ask`.

⚠️ MeTube has no login. Not a token, not a user, nothing in its configuration
offers one: whoever reaches the port may queue downloads and delete them. That
is why this adapter asks for an address and nothing else, and why MeTube
belongs behind whatever guards the rest of the house.

Measured against MeTube 2026.08.28 with yt-dlp 2026.08.19:

* ``POST /add`` answers **HTTP 200 even when it failed**. A page that is not a
  video came back as ``{"status": "error", "msg": "ERROR: ... HTTP Error 404"}``
  with a 200 in front of it. Reading the status code alone reports a download
  that never started, so the body decides here.
* ``GET /history`` returns ``done``, ``queue`` and ``pending``. ``done`` is not
  "finished": a failed download lands there with ``status: "error"`` and stays.
* A queued entry passes through ``preparing`` with no percentage at all before
  it starts counting, so a card must survive a row with nothing to show.
* ``timestamp`` counts **nanoseconds** since the epoch.
* ``POST /delete`` takes ``{"where", "ids"}`` and answers ok for an id that was
  never there; ``POST /retry`` takes a single ``{"id"}``.
"""

from __future__ import annotations

import time
from typing import Any

from . import demo as fake
from .base import (
    Action,
    Adapter,
    AdapterError,
    Ask,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    duration_short,
    human_bytes,
    human_rate,
)

#: What MeTube calls its three lists, in the order a card shows them: what is
#: running first, what is waiting next, what is over last.
LISTS = ("queue", "pending", "done")

#: MeTube's own words for a row that has no progress yet, in ours.
#:
#: ⚠️ Not the service's word with a capital letter on it. The card translates
#: what an adapter writes by looking the English up, and "Preparing" straight
#: from the service is a word no translation file has: it stood there in
#: English on a German board while everything around it was translated.
WAITING = {
    "preparing": "Preparing",
    "pending": "Waiting",
    "downloading": "Downloading",
}


def _status(entry: dict[str, Any]) -> str:
    state = str(entry.get("status") or "").lower()
    if state == "error":
        return "bad"
    if state == "finished":
        return "ok"
    return "warn" if state in ("downloading", "preparing", "pending") else "unknown"


def _subtitle(entry: dict[str, Any], where: str) -> str:
    """One line under the title: the failure, else the progress, else the size."""
    if str(entry.get("status") or "").lower() == "error":
        # yt-dlp's message runs to several lines and names its own module.
        return str(entry.get("msg") or entry.get("error") or "Failed.").strip().splitlines()[0][:160]
    if where != "done":
        percent = entry.get("percent")
        speed = entry.get("speed")
        eta = entry.get("eta")
        if percent is None:
            return WAITING.get(str(entry.get("status") or "").lower(), "Waiting")
        parts = [f"{float(percent):.0f}%"]
        if speed:
            parts.append(human_rate(float(speed)))
        if eta:
            parts.append(duration_short(float(eta)) + " left")
        return " · ".join(parts)
    size = entry.get("size")
    return human_bytes(float(size)) if size else str(entry.get("format") or "")


class MetubeAdapter(Adapter):
    kind = "metube"
    label = "MeTube"
    category = "downloads"
    description = "Hand MeTube a video address and watch the file come down."
    icon = "metube"
    docs_url = "https://github.com/alexta69/metube"
    #: Seen against a live MeTube 2026.08.28 (08.09.2026), all three cards.
    beta = False
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://metube:8081",
              help="MeTube has no login of its own: whoever reaches this address may queue downloads and delete them."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="fetch",
            label="Fetch a video",
            description="A field for an address and a button that starts the download.",
            renderer="ask",
            default_size=(3, 2),
            min_size=(2, 2),
            refresh_seconds=15,
            metrics=("running",),
            options=(
                Field("what", "Fetch", type="select", default="video", options=(
                    ("video", "Video"),
                    ("audio", "Audio only"),
                )),
                Field("quality", "Quality", type="select", default="best", only_when=("what", "video"), options=(
                    ("best", "Best available"),
                    ("1080", "1080p at most"),
                    ("720", "720p at most"),
                    ("480", "480p at most"),
                )),
                Field("format", "Format", type="select", default="any", options=(
                    ("any", "Whatever the site offers"),
                    ("mp4", "mp4"),
                    ("mp3", "mp3"),
                    ("m4a", "m4a"),
                )),
                Field("show_running", "Show what is running", type="bool", default=True),
            ),
        ),
        WidgetType(
            kind="downloads",
            label="Downloads",
            description="What is running, what is waiting and what is over, newest first.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=15,
            metrics=("running", "failed"),
            options=(
                Field("limit", "Entries", type="number", default=8),
                Field("show", "Show", type="select", default="all", options=(
                    ("all", "Everything"),
                    ("busy", "Only what is running"),
                    ("done", "Only what is over"),
                )),
            ),
        ),
        WidgetType(
            kind="counts",
            label="Download count",
            description="How much is running, done and failed.",
            renderer="value",
            default_size=(2, 2),
            min_size=(2, 2),
            refresh_seconds=30,
            metrics=("running", "failed"),
        ),
    )

    # -- talking to the service ----------------------------------------------

    async def _history(self, config: dict[str, Any], ctx: Context, cache: float = 10) -> dict[str, list[dict[str, Any]]]:
        payload = await ctx.get_json(
            f"{base_url(config)}/history",
            verify=not config.get("insecure"),
            cache_seconds=cache,
        )
        if not isinstance(payload, dict):
            raise AdapterError("MeTube answered with something other than its history.", code="unexpected")
        return {name: [row for row in (payload.get(name) or []) if isinstance(row, dict)] for name in LISTS}

    async def _post(self, config: dict[str, Any], ctx: Context, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """A POST whose answer is read, not counted.

        ⚠️ MeTube says HTTP 200 and ``status: "error"`` in the same breath, so
        the status code proves nothing. A refusal carries plain text rather
        than JSON, so that is not trusted without looking either.
        """
        response = await ctx.request(
            "POST", f"{base_url(config)}{path}", json_body=body, verify=not config.get("insecure"), timeout=30.0,
        )
        try:
            answer = response.json()
        except ValueError:
            answer = {}
        if not isinstance(answer, dict):
            answer = {}
        if response.status_code >= 400:
            raise AdapterError(
                str(answer.get("msg") or response.text or f"MeTube refused with HTTP {response.status_code}.")[:200],
                code="http_error",
            )
        if str(answer.get("status") or "").lower() == "error":
            raise AdapterError(
                str(answer.get("msg") or "MeTube could not fetch that.").strip().splitlines()[0][:200],
                code="rejected",
            )
        return answer

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        version = await ctx.get_json(f"{base_url(config)}/version", verify=not config.get("insecure"), cache_seconds=0)
        lists = await self._history(config, ctx, cache=0)
        busy = len(lists["queue"]) + len(lists["pending"])
        return (f"MeTube {version.get('version', '?')} with yt-dlp {version.get('yt-dlp', '?')} answers: "
                f"{busy} running, {len(lists['done'])} in the history.")

    # -- the cards -----------------------------------------------------------

    def _add_action(self, options: dict[str, Any]) -> Action:
        """The button, with the one blank whoever is at the board fills in."""
        audio = str(options.get("what") or "video") == "audio"
        return Action(
            id="add",
            label="Fetch",
            icon="download",
            params={
                "download_type": "audio" if audio else "video",
                "quality": "best" if audio else str(options.get("quality") or "best"),
                "format": str(options.get("format") or "any"),
            },
            ask=Ask(name="url", label="Video address", kind="url", placeholder="https://...", max_length=2048),
        )

    def _rows(self, lists: dict[str, list[dict[str, Any]]], show: str, limit: int) -> list[dict[str, Any]]:
        wanted = {"all": LISTS, "busy": ("queue", "pending"), "done": ("done",)}.get(show, LISTS)
        rows: list[dict[str, Any]] = []
        for where in wanted:
            entries = lists[where]
            if where == "done":
                # Nanoseconds, newest first; an entry without one goes last.
                entries = sorted(entries, key=lambda one: float(one.get("timestamp") or 0), reverse=True)
            for entry in entries:
                identifier = str(entry.get("id") or "")
                failed = str(entry.get("status") or "").lower() == "error"
                actions: list[dict[str, Any]] = [
                    {"id": "remove", "label": "Remove", "icon": "trash-2",
                     "params": {"where": where, "id": identifier}},
                ]
                if failed:
                    actions.insert(0, {"id": "retry", "label": "Try again", "icon": "rotate-cw",
                                       "params": {"id": identifier}})
                rows.append({
                    "title": str(entry.get("title") or identifier or "?"),
                    "subtitle": _subtitle(entry, where),
                    "status": _status(entry),
                    "progress": float(entry.get("percent") or 0) if where != "done" else None,
                    "actions": actions if identifier else [],
                })
        return rows[:limit]

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        lists = await self._history(config, ctx)
        running = len(lists["queue"])
        waiting = len(lists["pending"])
        failed = sum(1 for entry in lists["done"] if str(entry.get("status") or "").lower() == "error")
        done = len(lists["done"]) - failed
        counted = {"running": float(running + waiting), "failed": float(failed)}

        if widget_kind == "counts":
            return WidgetData(
                status="bad" if failed else "warn" if running + waiting else "ok",
                primary={"label": "Running", "value": running + waiting},
                secondary=[{"label": "Done", "value": done}, {"label": "Failed", "value": failed}],
                metrics=counted,
            )

        if widget_kind == "downloads":
            return WidgetData(
                status="bad" if failed else "ok",
                items=self._rows(lists, str(options.get("show") or "all"), int(options.get("limit") or 8)),
                secondary=[{"label": "Running", "value": running + waiting}, {"label": "Done", "value": done}],
                metrics=counted,
            )

        return WidgetData(
            status="warn" if running + waiting else "ok",
            actions=[self._add_action(options)],
            items=self._rows({**lists, "done": []}, "busy", 3) if options.get("show_running", True) else [],
            secondary=[{"label": "Running", "value": running + waiting}],
            metrics={"running": counted["running"]},
        )

    # -- what a card may be asked to do --------------------------------------

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any],
                     config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        if action_id == "add":
            answer = await self._post(config, ctx, "/add", {
                "url": str(params.get("url") or ""),
                "download_type": str(params.get("download_type") or "video"),
                "quality": str(params.get("quality") or "best"),
                "format": str(params.get("format") or "any"),
                "auto_start": True,
            })
            # ⚠️ An address that is already in the queue answers ok as well,
            # with a message saying so. Reporting "started" there is the button
            # taking credit for work it did not cause.
            note = str(answer.get("msg") or "").strip()
            return note[:200] if note else "MeTube is fetching it."
        if action_id == "retry":
            await self._post(config, ctx, "/retry", {"id": str(params.get("id") or "")})
            return "Trying again."
        if action_id == "remove":
            where = str(params.get("where") or "done")
            if where not in LISTS:
                raise AdapterError("MeTube has no such list.", code="no_such_action")
            await self._post(config, ctx, "/delete", {"where": where, "ids": [str(params.get("id") or "")]})
            return "Removed."
        raise AdapterError("This widget has no such action.", code="no_such_action")

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = time.time()
        lists: dict[str, list[dict[str, Any]]] = {
            "queue": [{"id": "aBc123", "title": "How a cylinder lock works", "status": "downloading",
                       "percent": 4 + (tick * 7) % 92, "speed": 2_400_000, "eta": 40}],
            "pending": [{"id": "dEf456", "title": "Building a workbench in a weekend", "status": "pending"}],
            "done": [
                {"id": "gHi789", "title": "Soldering for the impatient", "status": "finished",
                 "size": 184_000_000, "timestamp": (now - 600) * 1e9},
                {"id": "jKl012", "title": "A page that turned out not to be a video", "status": "error",
                 "msg": "ERROR: Unable to download webpage: HTTP Error 404", "timestamp": (now - 3600) * 1e9},
            ],
        }
        failed = 1 if fake.flicker("metube-failed", tick, 0.5) else 0
        finished = fake.counter("metube-done", tick, 41, 0.02)
        if widget_kind == "counts":
            return WidgetData(
                status="bad" if failed else "warn",
                primary={"label": "Running", "value": 2},
                secondary=[{"label": "Done", "value": finished}, {"label": "Failed", "value": failed}],
                metrics={"running": 2.0, "failed": float(failed)},
            )
        if widget_kind == "downloads":
            return WidgetData(
                status="bad" if failed else "ok",
                items=self._rows(lists, str(options.get("show") or "all"), int(options.get("limit") or 8)),
                secondary=[{"label": "Running", "value": 2}, {"label": "Done", "value": finished}],
                metrics={"running": 2.0, "failed": float(failed)},
            )
        return WidgetData(
            status="warn",
            actions=[self._add_action(options)],
            items=self._rows({**lists, "done": []}, "busy", 3) if options.get("show_running", True) else [],
            secondary=[{"label": "Running", "value": 2}],
            metrics={"running": 2.0},
        )


ADAPTER = MetubeAdapter()
