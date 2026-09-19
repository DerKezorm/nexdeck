"""nexpulse: the speed test tracker of the nexapps family, read through its API keys.

Measured against nexpulse 0.1.0 and 0.1.1 on 2026-09-19 with a key of each
kind, which took the adapter out of beta. Three things from that measurement
shape the cards:

- ``GET /api/v1/me`` (nexpulse 0.1.1) says what a key may do, in
  ``can_run_tests``. The button is offered on that answer. ⚠️ Nothing is ever
  POSTed to find something out: 0.1.0 started a real Cloudflare test for a
  body without a source. On 0.1.0 the address answers 404, the rights are
  unknown, and the button is shown; a key that may only read then gets
  nexpulse's 403 as a sentence when it is pressed, and the connection test
  asks for the update.
- ``/api/v1/latest`` and ``latest`` in ``/status`` are the newest
  *successful* result. A test that failed afterwards is only in
  ``/results``, and a card that showed the older numbers without saying so
  would call a broken line fine.
- ``below_plan`` is worked out by nexpulse against the plan and threshold set
  there. The card takes that verdict rather than a second plan typed into
  nexdeck, which would sooner or later disagree with the first.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import httpx

from . import demo as fake
from .base import (
    Action,
    Adapter,
    AdapterError,
    Context,
    Deed,
    Field,
    WidgetData,
    WidgetType,
    ago,
    as_gauge,
    base_url,
    gauge_fields,
    measured,
    timeline,
)

#: What nexpulse measures with, in the words it uses on its own pages.
SOURCES: tuple[tuple[str, str], ...] = (("cloudflare", "Cloudflare"), ("librespeed", "LibreSpeed"), ("ookla", "Ookla"))
SOURCE_NAMES = dict(SOURCES)
#: What a test is started with when the card shows every source. It is also
#: what nexpulse itself starts when nothing is named.
DEFAULT_SOURCE = "cloudflare"

#: The periods ``/api/v1/stats`` knows, and what they are in seconds.
RANGES: dict[str, int] = {"24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400, "90d": 90 * 86400}
RANGE_CHOICES = (("24h", "24 hours"), ("7d", "7 days"), ("30d", "30 days"), ("90d", "90 days"))

#: nexpulse hands out at most this many results in one answer.
MOST = 5000

#: How much the ping may grow under load before the grade drops, in ms, with
#: the grade it earns below that. The steps are the ones the Waveform
#: bufferbloat test publishes, so a grade here reads like a grade there.
GRADES: tuple[tuple[float, str], ...] = ((5, "A+"), (30, "A"), (60, "B"), (200, "C"), (400, "D"))

#: A share of tests above which a period is not called fine any more.
TROUBLING = 0.1

READ_ONLY = ("This API key may only read. Create a key with “Read and start tests” in nexpulse "
             "to start a test from nexdeck.")

#: nexpulse's refusals by the code in ``detail``, as a sentence that says what
#: to do and a code the interface translates by.
REFUSALS: dict[str, tuple[str, str]] = {
    "invalid_api_key": (
        "nexpulse does not know this API key, or it was revoked. Create a key in nexpulse under "
        "Settings → API keys and enter it in this connection.",
        "nexpulse_key_invalid",
    ),
    "key_read_only": (READ_ONLY, "nexpulse_read_only"),
    "busy": ("nexpulse is already running a test. The card shows it as soon as it is done.", "nexpulse_busy"),
    "source_disabled": (
        "This source is turned off in nexpulse. Turn it on there, or pick another source in the card's settings.",
        "nexpulse_source_off",
    ),
    "unknown_source": ("nexpulse does not know this source. Pick another one in the card's settings.",
                       "nexpulse_source_unknown"),
    "invalid_range": ("nexpulse does not know this period. Pick another one in the card's settings.",
                      "nexpulse_bad_range"),
}

RUN = Action(id="run", label="Run a test", icon="play", confirm=True)


def _source(options: dict[str, Any]) -> str:
    """The source a card is narrowed to, or ``""`` for all of them."""
    wanted = str(options.get("source") or "")
    return wanted if wanted in SOURCE_NAMES else ""


def _number(value: Any, digits: int = 1) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _when(result: dict[str, Any]) -> float | None:
    text = str(result.get("started_at") or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.replace(tzinfo=moment.tzinfo or UTC).timestamp()


def _loaded(result: dict[str, Any]) -> float | None:
    """The ping while the line was busy, the worse of the two directions."""
    values = [value for value in (_number(result.get("loaded_down_ms")), _number(result.get("loaded_up_ms")))
              if value is not None]
    return max(values) if values else None


def grade(result: dict[str, Any]) -> tuple[str, float] | None:
    """The bufferbloat grade of one result and the growth it rests on.

    ⚠️ None when the result has no ping under load. That is a measurement that
    did not happen, not one that went perfectly, and an "A+" for it would be
    the best mark for the thing nobody looked at.
    """
    idle, busy = _number(result.get("ping_ms")), _loaded(result)
    if idle is None or busy is None:
        return None
    growth = max(0.0, round(busy - idle, 1))
    for limit, mark in GRADES:
        if growth < limit:
            return mark, growth
    return "F", growth


def _grade_status(mark: str) -> str:
    if mark in ("A+", "A", "B"):
        return "ok"
    return "warn" if mark in ("C", "D") else "bad"


def _where(result: dict[str, Any]) -> str:
    source = SOURCE_NAMES.get(str(result.get("source") or ""), str(result.get("source") or ""))
    location = str(result.get("server_location") or "").strip()
    return " · ".join(part for part in (source, location) if part)


def _result_row(result: dict[str, Any], base: str) -> dict[str, Any]:
    failed = result.get("status") == "failed"
    below = bool(result.get("below_plan"))
    if failed:
        title = "Failed"
        # The code, not a sentence: nexpulse names what went wrong and its own
        # page explains it in the reader's language.
        subtitle = " · ".join(part for part in (_where(result), str(result.get("error_code") or "")) if part)
    else:
        down, up = _number(result.get("download_mbps"), 0), _number(result.get("upload_mbps"), 0)
        title = f"{'?' if down is None else int(down)} / {'?' if up is None else int(up)} Mbps"
        subtitle = " · ".join(part for part in (_where(result), "Below plan" if below else "") if part)
    return {
        "id": str(result.get("id")),
        "title": title,
        "subtitle": subtitle,
        "value": ago(result.get("started_at")),
        "status": "bad" if failed else "warn" if below else "ok",
        # Ookla keeps a page of its own for every result; the others do not.
        "url": str(result.get("result_url") or "") or base,
    }


class NexpulseAdapter(Adapter):
    kind = "nexpulse"
    label = "nexpulse"
    category = "network"
    description = "Speed tests from nexpulse: the latest result, the history, a summary, latency under load and a button to test now."
    icon = "nexpulse"
    docs_url = "https://github.com/DerKezorm/nexpulse"
    # Every card, the refusals and the button ran against nexpulse 0.1.0 on 2026-09-19.
    beta = False
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://nexpulse:8080",
              help="The address nexpulse is reached at, with its sub-path if it has one."),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="A key from nexpulse under Settings → API keys. A key that may only read fills every card; "
                   "one that may also start tests adds a button for it."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="latest", label="Latest result",
            description="Download, upload, ping and jitter of the newest test, a running test as it happens, "
                        "and a button to start one.",
            renderer="value", default_size=(2, 2), refresh_seconds=60, metrics=("download", "upload", "ping"),
            options=(
                Field("source", "Source", type="select", default="",
                      options=(("", "All sources"), *SOURCES),
                      help="Which results the card shows, and what the button tests with. "
                           "With all sources it tests with Cloudflare."),
                *gauge_fields("What your line is supposed to deliver, in Mbps.", "1000"),
            ),
        ),
        WidgetType(
            kind="history", label="History",
            description="Download and upload, or ping, over a period, as a line or as bars.",
            renderer="timeline", default_size=(4, 3), min_size=(3, 2), refresh_seconds=900,
            options=(
                Field("period", "Period", type="select", default="7d", options=RANGE_CHOICES),
                Field("show", "Show", type="select", default="speed",
                      options=(("speed", "Download and upload"), ("download", "Download only"),
                               ("upload", "Upload only"), ("latency", "Ping, idle and under load"))),
                Field("shape", "Shape", type="select", default="line", options=(("line", "A line"), ("bars", "Bars"))),
                Field("source", "Source", type="select", default="", options=(("", "All sources"), *SOURCES)),
            ),
        ),
        WidgetType(
            kind="summary", label="Period summary",
            description="Averages over a period, how many tests failed and how often the line fell below the plan.",
            renderer="value", default_size=(3, 2), refresh_seconds=900, metrics=("download", "upload", "ping"),
            options=(
                Field("period", "Period", type="select", default="7d", options=RANGE_CHOICES),
                Field("figure", "Figure", type="select", default="avg",
                      options=(("avg", "Average"), ("median", "Median"), ("min", "Lowest"), ("max", "Highest"))),
                Field("source", "Source", type="select", default="", options=(("", "All sources"), *SOURCES)),
            ),
        ),
        WidgetType(
            kind="recent", label="Recent tests",
            description="The newest tests, failed ones red and those below the plan yellow.",
            renderer="list", default_size=(3, 3), refresh_seconds=120,
            options=(
                Field("limit", "Entries", type="number", default=8, help="Between 1 and 50."),
                Field("source", "Source", type="select", default="", options=(("", "All sources"), *SOURCES)),
            ),
        ),
        WidgetType(
            kind="bufferbloat", label="Latency under load",
            description="How much the ping grows while the line is busy, graded from A+ to F.",
            renderer="value", default_size=(2, 2), refresh_seconds=300, metrics=("growth",),
            options=(Field("source", "Source", type="select", default="", options=(("", "All sources"), *SOURCES)),),
        ),
    )
    # No target: a test is of the whole line. The button tests with Cloudflare.
    deeds = (Deed(widget_kind="latest", id="run", label="Run a speed test", target_label="", icon="play"),)

    # -- talking to nexpulse -------------------------------------------------

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"Authorization": f"Bearer {config.get('api_key', '')}", "Accept": "application/json"}

    async def _call(self, method: str, config: dict[str, Any], ctx: Context, path: str, *,
                    params: Any = None, body: Any = None, cache: float = 30) -> httpx.Response:
        return await ctx.request(
            method, f"{base_url(config)}{path}", params=params, json_body=body, headers=self._headers(config),
            verify=not config.get("insecure"), cache_seconds=cache,
            # ⚠️ Not turned into "the credentials were rejected": a key that
            # may only read gets 403 when it starts a test, and that is a
            # decision somebody made in nexpulse, not a bad key.
            auth_errors=False,
        )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, *,
                   params: Any = None, cache: float = 30) -> Any:
        response = await self._call("GET", config, ctx, path, params=params, cache=cache)
        if response.status_code >= 400:
            raise self._refusal(response)
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("nexpulse did not answer with data. The URL probably points at a login page "
                               "or at something else.", code="not_json") from error

    @staticmethod
    def _code(response: httpx.Response) -> str:
        try:
            detail = response.json().get("detail")
        except (ValueError, AttributeError):
            return ""
        return str(detail.get("code") or "") if isinstance(detail, dict) else ""

    def _refusal(self, response: httpx.Response) -> AdapterError:
        code = self._code(response)
        if code in REFUSALS:
            message, ours = REFUSALS[code]
            return AdapterError(message, code=ours)
        if response.status_code == 404:
            return AdapterError("nexpulse has no API at this address. Check the URL, including a sub-path.",
                                code="http_error")
        return AdapterError(f"nexpulse answered with HTTP {response.status_code}.", code="http_error")

    async def may_run(self, config: dict[str, Any], ctx: Context, *, fresh: bool = False) -> bool | None:
        """Whether this key may start tests: yes, no, or ``None`` for unknown.

        Asked of ``/api/v1/me`` and kept five minutes, as a key's rights change
        only in nexpulse's settings. The remembered answer is keyed by the
        request headers, so a key swapped in the connection is asked afresh.
        ``None`` is nexpulse 0.1.0, which has no such address.
        """
        response = await self._call("GET", config, ctx, "/api/v1/me", cache=0 if fresh else 300)
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise self._refusal(response)
        try:
            me = response.json()
        except ValueError as error:
            raise AdapterError("nexpulse did not answer with data. The URL probably points at a login page "
                               "or at something else.", code="not_json") from error
        return bool(me.get("can_run_tests")) if isinstance(me, dict) else None

    async def _results(self, config: dict[str, Any], ctx: Context, *, source: str, since: float | None = None,
                       limit: int = MOST, cache: float = 60) -> list[dict[str, Any]]:
        params: dict[str, str] = {"limit": str(limit)}
        if since is not None:
            params["from"] = datetime.fromtimestamp(since, UTC).isoformat()
        if source:
            params["source"] = source
        answer = await self._get(config, ctx, "/api/v1/results", params=params, cache=cache)
        if not isinstance(answer, list):
            raise AdapterError("nexpulse did not answer in the shape this card knows.", code="not_json")
        return [one for one in answer if isinstance(one, dict)]

    async def _latest_ok(self, config: dict[str, Any], ctx: Context, source: str) -> dict[str, Any] | None:
        answer = await self._get(config, ctx, "/api/v1/latest", params={"source": source} if source else None)
        return answer if isinstance(answer, dict) else None

    # -- hooks ---------------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        status = await self._get(config, ctx, "/api/v1/status", cache=0)
        if not isinstance(status, dict) or "running" not in status:
            raise AdapterError("This address answers, but not the way nexpulse does.", code="not_nexpulse")
        version = str(status.get("version") or "?")
        # ⚠️ Said at setup, so the missing button is not a riddle on the board.
        allowed = await self.may_run(config, ctx, fresh=True)
        if allowed is None:
            return (f"nexpulse {version} answers, but cannot say what the key may do. The start button is "
                    "shown and says so if the key may only read. nexpulse 0.1.1 or newer knows.")
        if allowed:
            return f"nexpulse {version} answers. The key may read results and start tests."
        return f"nexpulse {version} answers. The key may read results; starting a test needs another key."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "latest":
            return await self._latest(config, options, ctx)
        if widget_kind == "history":
            period = str(options.get("period") or "7d")
            since = time.time() - RANGES.get(period, RANGES["7d"])
            return self._history(await self._results(config, ctx, source=_source(options), since=since, cache=300), options)
        if widget_kind == "summary":
            period = str(options.get("period") or "7d")
            params = {"range": period if period in RANGES else "7d"}
            if _source(options):
                params["source"] = _source(options)
            stats = await self._get(config, ctx, "/api/v1/stats", params=params, cache=300)
            return self._summary(stats if isinstance(stats, dict) else {}, options)
        if widget_kind == "recent":
            limit = _limit(options)
            rows = await self._results(config, ctx, source=_source(options), limit=limit)
            return self._recent(rows, base_url(config), limit)
        if widget_kind == "bufferbloat":
            return self._bufferbloat(await self._latest_ok(config, ctx, _source(options)))
        raise AdapterError("This adapter has no such widget.", code="no_such_widget")

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        if widget_kind != "latest" or action_id != "run":
            raise AdapterError("nexpulse has no such action.", code="no_such_action")
        source = _source(options) or DEFAULT_SOURCE
        response = await self._call("POST", config, ctx, "/api/v1/tests", body={"source": source}, cache=0)
        if response.status_code >= 400:
            raise self._refusal(response)
        ctx.forget_answers()
        return f"nexpulse is testing with {SOURCE_NAMES[source]}. The card shows the result in about half a minute."

    # -- the cards -----------------------------------------------------------

    async def _latest(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        source = _source(options)
        status = await self._get(config, ctx, "/api/v1/status", cache=10)
        status = status if isinstance(status, dict) else {}
        latest = status.get("latest") if not source else await self._latest_ok(config, ctx, source)
        newest = await self._results(config, ctx, source=source, limit=1, cache=10)
        live = status.get("live") if status.get("running") else None
        if isinstance(live, dict) and source and live.get("source") != source:
            live = None
        card = self._latest_data(latest if isinstance(latest, dict) else None, newest[0] if newest else None,
                                 live if isinstance(live, dict) else None, options)
        # Unknown (0.1.0) counts as allowed: a refused press says why, a
        # missing button says nothing.
        if not live and await self.may_run(config, ctx) is not False:
            card.actions = [RUN]
        return card

    @staticmethod
    def _latest_data(latest: dict[str, Any] | None, newest: dict[str, Any] | None,
                     live: dict[str, Any] | None, options: dict[str, Any]) -> WidgetData:
        running = None
        if live:
            now = _number(live.get("current_mbps"), 0)
            running = {"label": "Test running", "value": now if now is not None else "…",
                       "unit": "Mbps" if now is not None else ""}
        if latest is None:
            if running:
                return WidgetData(status="ok", primary=running)
            return WidgetData(status="unknown", meta={"empty": "No measurement yet"})
        download = _number(latest.get("download_mbps"))
        upload = _number(latest.get("upload_mbps"))
        ping = _number(latest.get("ping_ms"))
        jitter = _number(latest.get("jitter_ms"))
        secondary = [
            {"label": "Upload", "value": upload, "unit": "Mbps"},
            {"label": "Ping", "value": ping, "unit": "ms"},
        ]
        if jitter is not None:
            secondary.append({"label": "Jitter", "value": jitter, "unit": "ms"})
        secondary.append({"label": "Tested", "value": ago(latest.get("started_at"))})
        if running:
            secondary.insert(0, running)
        meta: dict[str, Any] = {}
        state = "ok"
        if latest.get("below_plan"):
            state = "warn"
            meta["status_reason"] = "Below the plan set in nexpulse"
        # ⚠️ The newest attempt failed after the result shown. Said, because the
        # numbers on the card are then from before the line broke.
        if newest and newest.get("status") == "failed" and newest.get("id") != latest.get("id") \
                and (_when(newest) or 0) > (_when(latest) or 0):
            state = "warn"
            meta["status_reason"] = "The newest test failed"
            meta["notice"] = "The newest test failed. The numbers are from the test before it."
        card = WidgetData(
            status=state,
            primary={"label": "Download", "value": download, "unit": "Mbps"},
            secondary=secondary,
            metrics=measured({"download": download, "upload": upload, "ping": ping}),
            meta=meta,
        )
        return as_gauge(card, options)

    @staticmethod
    def _history(results: list[dict[str, Any]], options: dict[str, Any]) -> WidgetData:
        inside = sorted(((at, one) for one in results if (at := _when(one)) is not None), key=lambda pair: pair[0])
        if not inside:
            return WidgetData(status="unknown", meta={"empty": "No measurement in this period"})
        shown = str(options.get("show") or "speed")
        shape = str(options.get("shape") or "line")

        def series(read: Any) -> list[tuple[float, float | None]]:
            # ⚠️ A failed test is a gap, not a nought. Its numbers are null
            # anyway, but a line dropping to the floor would draw an outage
            # of a size nobody measured.
            return [(at, None if one.get("status") == "failed" else read(one)) for at, one in inside]

        tests = {"label": "Tests", "value": len(inside)}
        if shown == "latency":
            newest = inside[-1][1]
            return WidgetData(
                primary={"label": "Ping", "value": _number(newest.get("ping_ms")), "unit": "ms"},
                secondary=[{"label": "Under load", "value": _loaded(newest), "unit": "ms"}, tests],
                metrics=measured({"ping": _number(newest.get("ping_ms"))}),
                meta=timeline(("ping", "Ping", series(lambda one: _number(one.get("ping_ms")))),
                              ("loaded", "Under load", series(_loaded)), unit="ms", shape=shape),
            )
        lines = []
        if shown in ("speed", "download"):
            lines.append(("download", "Download", series(lambda one: _number(one.get("download_mbps")))))
        if shown in ("speed", "upload"):
            lines.append(("upload", "Upload", series(lambda one: _number(one.get("upload_mbps")))))
        good = [one for _at, one in inside if one.get("status") == "ok"]
        newest = good[-1] if good else {}
        down, up = _number(newest.get("download_mbps")), _number(newest.get("upload_mbps"))
        primary = {"label": "Upload", "value": up, "unit": "Mbps"} if shown == "upload" \
            else {"label": "Download", "value": down, "unit": "Mbps"}
        secondary = [{"label": "Upload", "value": up, "unit": "Mbps"}, tests] if shown == "speed" else [tests]
        return WidgetData(
            primary=primary, secondary=secondary,
            metrics=measured({"download": down, "upload": up}),
            meta=timeline(*lines, unit="Mbps", shape=shape),
        )

    @staticmethod
    def _summary(stats: dict[str, Any], options: dict[str, Any]) -> WidgetData:
        figure = str(options.get("figure") or "avg")
        if figure not in ("avg", "median", "min", "max"):
            figure = "avg"
        tests, ok = int(stats.get("tests") or 0), int(stats.get("ok") or 0)
        failed, below = int(stats.get("failed") or 0), int(stats.get("below_plan") or 0)
        if tests == 0:
            return WidgetData(status="unknown", meta={"empty": "No measurement in this period"})

        def pick(name: str) -> float | None:
            described = stats.get(name)
            return _number(described.get(figure)) if isinstance(described, dict) else None

        download, upload, ping = pick("download_mbps"), pick("upload_mbps"), pick("ping_ms")
        secondary: list[dict[str, Any]] = [
            {"label": "Upload", "value": upload, "unit": "Mbps"},
            {"label": "Ping", "value": ping, "unit": "ms"},
            {"label": "Tests", "value": tests},
        ]
        # ⚠️ Only when there is something to count. Two more chips at zero ran
        # a card of this width off its edge, and a zero here says nothing the
        # green dot does not.
        if failed:
            secondary.append({"label": "Failed", "value": failed})
        if below:
            secondary.append({"label": "Below plan", "value": below})
        reasons = []
        if failed / tests >= TROUBLING:
            reasons.append(f"{failed} of {tests} tests failed")
        if ok and below / ok >= TROUBLING:
            reasons.append(f"{below} of {ok} tests below the plan")
        return WidgetData(
            status="warn" if reasons else "ok",
            primary={"label": "Download", "value": download, "unit": "Mbps"},
            secondary=secondary,
            metrics=measured({"download": download, "upload": upload, "ping": ping}),
            meta={"status_reason": " · ".join(reasons)} if reasons else {},
        )

    @staticmethod
    def _recent(results: list[dict[str, Any]], base: str, limit: int) -> WidgetData:
        # nexpulse answers oldest first; the card reads newest first.
        rows = [_result_row(one, base) for one in reversed(results)][:limit]
        worst = "bad" if rows and rows[0]["status"] == "bad" else "ok"
        return WidgetData(status=worst, items=rows, meta={"empty": "No measurement yet"})

    @staticmethod
    def _bufferbloat(latest: dict[str, Any] | None) -> WidgetData:
        if latest is None:
            return WidgetData(status="unknown", meta={"empty": "No measurement yet"})
        graded = grade(latest)
        if graded is None:
            return WidgetData(status="unknown", meta={"empty": "This test did not measure the ping under load"})
        mark, growth = graded
        return WidgetData(
            status=_grade_status(mark),
            primary={"label": "Grade", "value": mark},
            secondary=[
                {"label": "Idle", "value": _number(latest.get("ping_ms")), "unit": "ms"},
                {"label": "Under load", "value": _loaded(latest), "unit": "ms"},
                {"label": "Growth", "value": growth, "unit": "ms"},
            ],
            metrics={"growth": growth},
            meta={"status_reason": "The ping grows a lot while the line is busy"} if mark not in ("A+", "A", "B") else {},
        )

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = time.time()
        history = _demo_results(now, tick, days=RANGES.get(str(options.get("period") or "7d"), RANGES["7d"]) // 86400)
        source = _source(options)
        if source:
            history = [one for one in history if one["source"] == source] or history
        good = [one for one in history if one["status"] == "ok"]
        if widget_kind == "latest":
            card = self._latest_data(good[-1], history[-1], None, options)
            card.actions = [RUN]
            return card
        if widget_kind == "history":
            return self._history(history, options)
        if widget_kind == "summary":
            return self._summary(_demo_stats(history), options)
        if widget_kind == "recent":
            limit = _limit(options)
            return self._recent(history[-limit:], "https://nexpulse.example.com", limit)
        return self._bufferbloat(good[-1])


def _limit(options: dict[str, Any]) -> int:
    try:
        wanted = int(options.get("limit") or 8)
    except (TypeError, ValueError):
        wanted = 8
    return max(1, min(50, wanted))


def _demo_results(now: float, tick: int, days: int) -> list[dict[str, Any]]:
    """One test every six hours, which is nexpulse's usual schedule."""
    steps = min(360, max(4, days * 4))
    made = []
    for step in range(steps):
        at = now - (steps - 1 - step) * 21600
        failed = step % 23 == 11
        down = fake.walk(f"np-down{step}", tick, 820, 960, period=900)
        idle = fake.walk(f"np-ping{step}", tick, 9, 14, period=600)
        made.append({
            "id": step + 1,
            "started_at": datetime.fromtimestamp(at, UTC).isoformat(),
            "source": "librespeed" if step % 5 == 2 else "cloudflare",
            "status": "failed" if failed else "ok",
            "error_code": "timeout" if failed else None,
            "server_location": "FRA · DE",
            "result_url": None,
            "download_mbps": None if failed else down,
            "upload_mbps": None if failed else fake.walk(f"np-up{step}", tick, 41, 52, period=900),
            "ping_ms": None if failed else idle,
            "jitter_ms": None if failed else fake.walk(f"np-jit{step}", tick, 1, 4, period=600),
            "loaded_down_ms": None if failed else idle + fake.walk(f"np-load{step}", tick, 12, 40, period=600),
            "loaded_up_ms": None if failed else idle + fake.walk(f"np-loadup{step}", tick, 6, 22, period=600),
            # ⚠️ A few below the plan, so the demo shows the yellow row too.
            "below_plan": not failed and step % 17 == 5,
        })
    return made


def _demo_stats(results: list[dict[str, Any]]) -> dict[str, Any]:
    good = [one for one in results if one["status"] == "ok"]

    def described(name: str) -> dict[str, float | None]:
        values = sorted(float(one[name]) for one in good if one.get(name) is not None)
        if not values:
            return {"avg": None, "median": None, "min": None, "max": None}
        return {"avg": sum(values) / len(values), "median": values[len(values) // 2],
                "min": values[0], "max": values[-1]}

    return {
        "tests": len(results), "ok": len(good),
        "failed": sum(1 for one in results if one["status"] == "failed"),
        "below_plan": sum(1 for one in good if one["below_plan"]),
        "download_mbps": described("download_mbps"), "upload_mbps": described("upload_mbps"),
        "ping_ms": described("ping_ms"),
    }


ADAPTER = NexpulseAdapter()
