"""MySpeed: the latest speed test, the averages of a period and the history, with a button that runs a test.

Measured against MySpeed 1.0.9 on 27.10.2026 (Ookla as the provider), with
three tests in it: two that ran and one that failed.

⚠️ No account, no key. MySpeed has one optional password, sent in the header
``password`` (not ``Authorization``). With a password and the level ``read``
(``passwordLevel`` in ``/api/config``) anybody may read the tests, the
statistics, ``/api/config`` and ``/api/speedtests/status`` and nothing else;
``/api/info/version`` and ``POST /run`` want the password. A wrong or missing
password is 401 ``{"message": "Please provide the correct password in the
header"}``.

⚠️ ``GET /api/speedtests?hours=&limit=`` lists the tests newest first:
``{"id", "ping", "download", "upload", "time", "created"}`` with Mbit/s and
milliseconds. **A test that failed is not left out**: it is a row with
``ping``, ``download`` and ``upload`` all ``-1``, ``time`` null and an
``error`` ("Validation error"). Read as numbers they would draw a line to the
floor, so they are a gap and a word. ``created`` is UTC with a ``Z``.

``/api/speedtests/statistics?days=`` (``days``, not hours) answers
``{"tests": {"total", "failed"}, "ping"|"download"|"upload": {"min", "max",
"avg"}}`` with nulls when there is nothing; failed tests are in ``failed``
and not in the averages. ``/api/config`` carries the expected values
(``ping``, ``download``, ``upload`` as strings), which MySpeed itself holds
the tests against.

``POST /api/speedtests/run`` answers 200 "Speedtest successfully created" at
once, the test runs about 30 seconds on; 410 "No provider selected" (measured
on a fresh MySpeed, which has to be given a provider first) or "The speedtests
are currently paused", 409 "An speedtest is already running" (the last one is
from the source, not measured).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from . import demo as fake
from .base import (
    Action,
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
    ago,
    base_url,
    measured,
    timeline,
)

DAY = 86400.0


def _when(row: dict[str, Any]) -> float | None:
    try:
        return datetime.fromisoformat(str(row.get("created") or "").replace("Z", "+00:00")).astimezone(UTC).timestamp()
    except ValueError:
        return None


def _good(row: dict[str, Any]) -> bool:
    return not row.get("error") and (row.get("download") or -1) >= 0


def _expected(config: dict[str, Any]) -> dict[str, float]:
    result = {}
    for key in ("ping", "download", "upload"):
        try:
            result[key] = float(config.get(key))
        except (TypeError, ValueError):
            continue
    return result


class MyspeedAdapter(Adapter):
    kind = "myspeed"
    label = "MySpeed"
    category = "network"
    description = "The latest speed test, the averages of a period and the history, with a button that runs a test."
    icon = "myspeed"
    #: Measured on 2026-10-27 against MySpeed 1.0.9, not yet an instance in use.
    beta = True
    docs_url = "https://docs.myspeed.dev/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://myspeed:5216"),
        Field("password", "Password", type="password", secret=True,
              help="Only when MySpeed has one. With the level Read, reading works without it, but the test button needs it."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="latest", label="Latest result", description="Download, upload and ping of the newest test, yellow when MySpeed's expected values are missed, with a button that runs a test.",
                   renderer="value", default_size=(2, 2), refresh_seconds=120, metrics=("download", "upload", "ping")),
        WidgetType(kind="statistics", label="Averages", description="Download, upload and ping averaged over a day, a week or a month, with the lowest and highest.",
                   renderer="stats", default_size=(3, 2), refresh_seconds=600,
                   options=(Field("days", "Period", type="select", default="7", options=(("1", "24 hours"), ("7", "7 days"), ("30", "30 days"))),)),
        WidgetType(kind="history", label="History", description="Download and upload over a period, a failed test as a gap.",
                   renderer="timeline", default_size=(4, 3), min_size=(3, 2), refresh_seconds=900,
                   options=(Field("days", "Period", type="select", default="7", options=(("1", "24 hours"), ("7", "7 days"), ("30", "30 days"))),
                            Field("show", "Show", type="select", default="both",
                                  options=(("both", "Download and upload"), ("download", "Download only"), ("upload", "Upload only"))))),
    )

    async def _call(self, config: dict[str, Any], ctx: Context, method: str, path: str, **more: Any) -> Any:
        password = str(config.get("password") or "")
        response = await ctx.request(method, f"{base_url(config)}/api{path}", headers={"password": password} if password else None,
                                     verify=not config.get("insecure"), auth_errors=False, **more)
        if response.status_code == 401:
            raise AuthFailed("MySpeed asks for its password." if not password else "MySpeed rejected the password.")
        return response

    async def _json(self, config: dict[str, Any], ctx: Context, path: str, **more: Any) -> Any:
        response = await self._call(config, ctx, "GET", path, cache_seconds=20, **more)
        if response.status_code >= 400:
            raise AdapterError(f"MySpeed answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of MySpeed's web page, port 5216 by default.")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("MySpeed did not answer with JSON.", code="not_json", hint="The URL probably points at something else than MySpeed.") from error

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        state = await self._json(config, ctx, "/speedtests/status")
        if not isinstance(state, dict) or "paused" not in state:
            raise AdapterError("This address answers, but not the way MySpeed does.", code="not_myspeed")
        version = ""
        try:
            named = await self._json(config, ctx, "/info/version")
            version = f" {named.get('local')}" if isinstance(named, dict) and named.get("local") else ""
        except AdapterError:
            # The version wants the password even where reading does not.
            pass
        return f"MySpeed{version} answers" + (", its tests are paused." if state.get("paused") else ".")

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "statistics":
            days = max(1, int(options.get("days") or 7))
            return self._statistics(await self._json(config, ctx, "/speedtests/statistics", params={"days": days}), days)
        if widget_kind == "history":
            days = max(1, int(options.get("days") or 7))
            return self._history(await self._json(config, ctx, "/speedtests", params={"hours": days * 24}), options, days)
        tests = await self._json(config, ctx, "/speedtests", params={"hours": 24 * 30, "limit": 10})
        state = await self._json(config, ctx, "/speedtests/status")
        try:
            wanted = _expected(await self._json(config, ctx, "/config"))
        except AdapterError:
            wanted = {}
        return self._latest(tests, state if isinstance(state, dict) else {}, wanted)

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any],
                     config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        if action_id != "run":
            raise AdapterError("MySpeed has no such action.", code="no_such_action")
        response = await self._call(config, ctx, "POST", "/speedtests/run")
        ctx.forget_answers()
        if response.status_code < 300:
            return "MySpeed has started a test."
        try:
            message = str(response.json().get("message") or "")
        except (ValueError, AttributeError):
            message = ""
        raise AdapterError(f"MySpeed could not run a test: {message}" if message else f"MySpeed answered with HTTP {response.status_code}.", code="action_failed")

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _latest(tests: list[dict[str, Any]], state: dict[str, Any], expected: dict[str, float], now: float | None = None) -> WidgetData:
        rows = [one for one in tests if isinstance(one, dict)]
        good = next((one for one in rows if _good(one)), None)
        newest = rows[0] if rows else None
        running, paused = bool(state.get("running")), bool(state.get("paused"))
        actions = [] if running or paused else [Action(id="run", label="Run test now", icon="play", confirm=True)]
        if good is None:
            reason = str(newest.get("error") or "") if newest else ""
            return WidgetData(status="warn" if newest else "unknown", primary={"label": "Download", "value": None, "unit": ""},
                              secondary=[{"label": "Last test", "value": f"Failed · {reason}" if reason else "No test yet"}],
                              meta={"empty": "No test yet."}, actions=actions)
        down, up, ping = float(good["download"]), float(good["upload"]), float(good["ping"])
        below = [word for word, key, bad in (("download", "download", down < expected.get("download", 0)), ("upload", "upload", up < expected.get("upload", 0)),
                                             ("ping", "ping", "ping" in expected and ping > expected["ping"])) if bad]
        failed_since = newest is not good and newest is not None and not _good(newest)
        secondary: list[dict[str, Any]] = [
            {"label": "Upload", "metric": "upload", "value": round(up, 1), "unit": "Mbps"},
            {"label": "Ping", "value": round(ping), "unit": "ms"},
            {"label": "Tested", "value": ago(_when(good), now=now) or "?"},
        ]
        if failed_since:
            secondary.append({"label": "Last test", "value": "Failed"})
        if running:
            secondary.append({"label": "State", "value": "Test running"})
        elif paused:
            secondary.append({"label": "State", "value": "Paused"})
        status = "warn" if below or failed_since else "ok"
        return WidgetData(
            status=status,
            primary={"label": "Download", "metric": "download", "value": round(down, 1), "unit": "Mbps"},
            secondary=secondary,
            metrics=measured({"download": down, "upload": up, "ping": ping}),
            meta={"below_expected": below},
            actions=actions,
        )

    @staticmethod
    def _statistics(numbers: dict[str, Any], days: int) -> WidgetData:
        tests = numbers.get("tests") if isinstance(numbers.get("tests"), dict) else {}

        def figure(label: str, key: str, field: str, unit: str, digits: int = 1) -> dict[str, Any]:
            value = (numbers.get(key) or {}).get(field)
            return {"label": label, "value": round(float(value), digits) if value is not None else None, "unit": unit}

        total, failed = int(tests.get("total") or 0), int(tests.get("failed") or 0)
        rows = [figure("Average download", "download", "avg", "Mbps"), figure("Average upload", "upload", "avg", "Mbps"), figure("Average ping", "ping", "avg", "ms", 0),
                figure("Lowest download", "download", "min", "Mbps"), figure("Highest download", "download", "max", "Mbps"),
                {"label": "Tests", "value": total - failed}, {"label": "Failed", "value": failed}]
        return WidgetData(status="unknown" if not total else "warn" if failed and failed * 2 > total else "ok", secondary=rows,
                          meta={"empty": "No test in this period."}, primary=None)

    @staticmethod
    def _history(tests: list[dict[str, Any]], options: dict[str, Any], days: int) -> WidgetData:
        rows = sorted(((at, one) for one in tests if isinstance(one, dict) and (at := _when(one))), key=lambda pair: pair[0])
        if not rows:
            return WidgetData(status="unknown", meta={"empty": "No test in this period."})

        def series(field: str) -> list[tuple[float, float | None]]:
            # A failed test is -1 in all three numbers; as a point it would draw an outage that never was.
            return [(at, float(one[field]) if _good(one) else None) for at, one in rows]

        wanted = str(options.get("show") or "both")
        lines = []
        if wanted in ("both", "download"):
            lines.append(("download", "Download", series("download")))
        if wanted in ("both", "upload"):
            lines.append(("upload", "Upload", series("upload")))
        last = next((one for _at, one in reversed(rows) if _good(one)), None)
        return WidgetData(
            primary={"label": "Download" if wanted != "upload" else "Upload", "value": round(float(last["upload" if wanted == "upload" else "download"]), 1) if last else None, "unit": "Mbps"},
            secondary=[{"label": "Tests", "value": len(rows)}],
            metrics=measured({"download": float(last["download"]) if last else None, "upload": float(last["upload"]) if last else None}),
            meta=timeline(*lines, unit="Mbps"),
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = time.time()
        if widget_kind == "history":
            days = max(1, int(options.get("days") or 7))
            steps = min(240, days * 24)
            tests = [{"created": datetime.fromtimestamp(now - (steps - 1 - step) * 3600, UTC).isoformat(),
                      "download": -1 if step % 20 == 7 else fake.walk(f"ms-d{step}", tick, 820, 960, period=900),
                      "upload": -1 if step % 20 == 7 else fake.walk(f"ms-u{step}", tick, 41, 52, period=900),
                      "ping": 12, **({"error": "Validation error"} if step % 20 == 7 else {})} for step in range(steps)]
            return self._history(tests, options, days)
        if widget_kind == "statistics":
            return self._statistics({"tests": {"total": 168, "failed": 3}, "ping": {"min": 9, "max": 31, "avg": 14}, "download": {"min": 702.4, "max": 951.8, "avg": 884.2},
                                     "upload": {"min": 38.1, "max": 52.3, "avg": 47.9}}, int(options.get("days") or 7))
        down, up = fake.walk("ms-down", tick, 620, 960), fake.walk("ms-up", tick, 38, 52)
        test = {"created": datetime.fromtimestamp(now - 1800, UTC).isoformat(), "download": down, "upload": up, "ping": round(fake.walk("ms-ping", tick, 9, 24))}
        return self._latest([test], {"running": False, "paused": False}, {"download": 700, "upload": 40, "ping": 25}, now=now)


ADAPTER = MyspeedAdapter()
