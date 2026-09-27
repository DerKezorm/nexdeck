"""OctoPrint: what the 3D printer is doing, how hot it is, and how far the print has got.

Measured on 27.09.2026 against OctoPrint 1.11.8 from ``octoprint/octoprint``
with its bundled virtual printer: straight after the first start, with the
printer disconnected, connected and idle, heating, printing a small G-code
file, paused, resumed, finished and cancelled, after a firmware error, and
with a profile of two nozzles, a heated bed and a heated chamber. Four keys:
an administrator's, one of the group Users, one of Read-only and one of a
user in no group at all.

⚠️ A wrong key and a key whose user may not see the status get the same
answer: 403 with the same text. ``/api/currentuser`` tells them apart, it
answers every key with 200: a wrong one as the anonymous guest (``name:
null``), a real one with its user's name and an empty list of permissions.

⚠️ ``/api/printer`` answers 409 "Printer is not operational" whenever
OctoPrint is not connected to the printer, which is every evening for a
printer that gets switched off. The card then reads the state from
``/api/job``, which answers either way: ``Offline``, or ``Offline after
error`` with the firmware's own words in ``error``.

⚠️ The temperatures follow the printer profile, not the printer: a profile
without a heated bed has no ``bed`` at all, one with two nozzles has
``tool0`` and ``tool1``, one with a heated chamber has ``chamber``.

⚠️ After a print, the job still stands there with ``completion: 100`` and
``printTimeLeft: 0`` in the state ``Operational``; the card calls that
finished. After a cancelled one the progress is all ``null`` again and the
file still selected: it looks exactly like a file nobody started.

⚠️ ``completion`` is how far through the file OctoPrint has read, not how
far through the time: it stood at 1.8 % for the twenty seconds the nozzle
heated up, then ran ahead. The time left is an estimate whose source changes
under way (``analysis``, then ``linear``, ``average`` once a file was
printed before); at the start it said 139 s for a print that took 27.

⚠️ ``printTime`` stops while a print is paused. Straight after the pause
command the state text is ``Pausing`` while the flags already say
``paused``.

⚠️ Straight after the first start, before the setup wizard has an
administrator, only the global API key in ``config.yaml`` gets in, and it
got in for everything. Without a key the wizard looks like any wrong key.
"""

from __future__ import annotations

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
    base_url,
    duration_short,
    gauge_view_field,
    measured,
)

RIGHTS_HINT = "Put the user in the group Users or Read-only in OctoPrint under Settings > Access Control."
KEY_HINT = "Create an application key in OctoPrint under User Settings > Application Keys."
#: The state texts of a print under way, and the word the card uses for each.
RUNNING = {"Printing": "Printing", "Printing from SD": "Printing", "Pausing": "Pausing", "Paused": "Paused",
           "Resuming": "Resuming", "Cancelling": "Cancelling", "Finishing": "Finishing",
           "Starting": "Starting", "Starting print from SD": "Starting"}


def _word(text: str) -> str:
    """OctoPrint's state text as one of the card's words."""
    text = str(text or "").strip()
    if text in RUNNING:
        return RUNNING[text]
    lowered = text.lower()
    if "error" in lowered:
        return "Error"
    if lowered.startswith("offline") or lowered == "closed":
        return "Offline"
    if "connect" in lowered or "opening" in lowered or "detecting" in lowered:
        return "Connecting"
    if lowered in ("operational", "ready"):
        return "Ready"
    return text or "Unknown"


def _status(word: str) -> str:
    if word == "Error":
        return "bad"
    if word in ("Paused", "Pausing"):
        return "warn"
    if word in ("Offline", "Connecting", "Unknown"):
        return "unknown"
    return "ok"


def _temperature(entry: Any) -> str:
    if not isinstance(entry, dict) or not isinstance(entry.get("actual"), (int, float)):
        return "?"
    target = entry.get("target")
    if isinstance(target, (int, float)) and target > 0:
        return f"{entry['actual']:.1f} / {target:.0f} °C"
    return f"{entry['actual']:.1f} °C"


class OctoPrintAdapter(Adapter):
    kind = "octoprint"
    label = "OctoPrint"
    category = "other"
    description = "What the 3D printer is doing, its nozzle, bed and chamber temperatures, and how far the print has got."
    icon = "octoprint"
    beta = False
    docs_url = "https://docs.octoprint.org/en/master/api/index.html"
    keywords = ("3D printer", "OctoPi")
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://octopi.local"),
        Field("api_key", "API key", type="password", required=True, secret=True,
              help="An application key from User Settings > Application Keys. Its user needs the permission Status, "
                   "which the groups Users and Read-only have."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False,
              help="OctoPi over HTTPS comes with a certificate of its own making."),
    )
    widgets = (
        WidgetType(kind="printer", label="Printer",
                   description="Whether the printer is ready, printing, paused or offline, with nozzle, bed and chamber temperatures.",
                   renderer="value", default_size=(3, 2), refresh_seconds=15, metrics=("nozzle_temp", "bed_temp"),
                   parts=(("nozzle", "Nozzle"), ("bed", "Bed"), ("chamber", "Chamber"))),
        WidgetType(kind="job", label="Print job",
                   description="The file being printed, how far it is, the time it has taken and the time it still needs.",
                   renderer="value", default_size=(3, 2), refresh_seconds=15, metrics=("progress",),
                   parts=(("file", "File"), ("elapsed", "Elapsed"), ("left", "Time left")),
                   options=(gauge_view_field(),)),
    )

    # -- talking to OctoPrint ------------------------------------------------

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, *, allow: tuple[int, ...] = ()) -> tuple[int, Any]:
        response = await ctx.request(
            "GET", f"{base_url(config)}{path}", headers={"X-Api-Key": str(config.get("api_key") or "").strip()},
            verify=not config.get("insecure"), timeout=10.0, cache_seconds=5, auth_errors=False)
        if response.status_code in (401, 403):
            await self._refused(config, ctx)
        if response.status_code >= 400 and response.status_code not in allow:
            raise AdapterError(f"OctoPrint answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address OctoPrint's web interface opens at.")
        try:
            return response.status_code, response.json()
        except ValueError as error:
            raise AdapterError("This address answers with something other than OctoPrint.", code="not_octoprint",
                               hint="Check the URL; it is the address OctoPrint's web interface opens at.") from error

    async def _refused(self, config: dict[str, Any], ctx: Context) -> None:
        """Say which refusal it was.

        ⚠️ A wrong key and a key without rights get the same 403; only the
        question "who am I" tells them apart.
        """
        response = await ctx.request(
            "GET", f"{base_url(config)}/api/currentuser", headers={"X-Api-Key": str(config.get("api_key") or "").strip()},
            verify=not config.get("insecure"), timeout=10.0, auth_errors=False)
        try:
            who = response.json() if response.status_code == 200 else {}
        except ValueError:
            who = {}
        name = who.get("name") if isinstance(who, dict) else None
        if name:
            raise AdapterError(f"The user {name} may not see the printer's status.", code="forbidden", hint=RIGHTS_HINT)
        error = AuthFailed("OctoPrint does not know this API key.")
        error.hint = KEY_HINT
        raise error

    async def _job(self, config: dict[str, Any], ctx: Context) -> dict[str, Any]:
        _, job = await self._get(config, ctx, "/api/job")
        if not isinstance(job, dict) or "state" not in job:
            raise AdapterError("This address answers, but not the way OctoPrint does.", code="not_octoprint")
        return job

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        _, version = await self._get(config, ctx, "/api/version")
        job = await self._job(config, ctx)
        text = str(version.get("text") or "OctoPrint") if isinstance(version, dict) else "OctoPrint"
        return f"{text} answers. Printer: {_word(job.get('state'))}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "job":
            return self._job_card(await self._job(config, ctx))
        code, printer = await self._get(config, ctx, "/api/printer", allow=(409,))
        if code == 409:
            # ⚠️ Not connected to the printer; the job endpoint still knows why.
            return self._printer_card(None, await self._job(config, ctx))
        return self._printer_card(printer if isinstance(printer, dict) else {}, None)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _printer_card(printer: dict[str, Any] | None, job: dict[str, Any] | None) -> WidgetData:
        if printer is None:
            job = job or {}
            word = _word(job.get("state"))
            error = str(job.get("error") or "")
            reason = error if error else "OctoPrint is not connected to the printer."
            return WidgetData(status=_status(word) if word != "Ready" else "unknown",
                              primary={"label": "State", "value": word}, meta={"status_reason": reason})
        state = printer.get("state") if isinstance(printer.get("state"), dict) else {}
        # ⚠️ By the text, not the flags: straight after the pause command the
        # flags already say paused while the text still says Pausing.
        word = _word(state.get("text"))
        temperatures = printer.get("temperature") if isinstance(printer.get("temperature"), dict) else {}
        tools = sorted((name for name in temperatures if name.startswith("tool")), key=lambda name: int(name[4:] or 0) if name[4:].isdigit() else 99)
        secondary: list[dict[str, Any]] = []
        for index, name in enumerate(tools):
            label = "Nozzle" if len(tools) == 1 else f"Nozzle {index + 1}"
            secondary.append({"label": label, "value": _temperature(temperatures[name]), "part": "nozzle"})
        # ⚠️ Only there when the printer profile has one.
        if "bed" in temperatures:
            secondary.append({"label": "Bed", "value": _temperature(temperatures["bed"]), "part": "bed"})
        if "chamber" in temperatures:
            secondary.append({"label": "Chamber", "value": _temperature(temperatures["chamber"]), "part": "chamber"})

        def actual(name: str) -> float | None:
            entry = temperatures.get(name)
            value = entry.get("actual") if isinstance(entry, dict) else None
            return float(value) if isinstance(value, (int, float)) else None

        return WidgetData(
            status=_status(word),
            primary={"label": "State", "value": word},
            secondary=secondary,
            metrics=measured({"nozzle_temp": actual(tools[0]) if tools else None, "bed_temp": actual("bed")}),
            meta={"status_reason": str(state.get("error") or "") if word == "Error" else ""},
        )

    @staticmethod
    def _job_card(job: dict[str, Any]) -> WidgetData:
        word = _word(job.get("state"))
        details = job.get("job") if isinstance(job.get("job"), dict) else {}
        file = details.get("file") if isinstance(details.get("file"), dict) else {}
        progress = job.get("progress") if isinstance(job.get("progress"), dict) else {}
        name = str(file.get("display") or file.get("name") or "")
        completion = progress.get("completion")
        done = isinstance(completion, (int, float))
        elapsed = progress.get("printTime")
        left = progress.get("printTimeLeft")
        secondary: list[dict[str, Any]] = []
        if name:
            secondary.append({"label": "File", "value": name, "part": "file"})

        if word in RUNNING.values():
            if isinstance(elapsed, (int, float)):
                secondary.append({"label": "Elapsed", "value": duration_short(elapsed), "part": "elapsed"})
            if isinstance(left, (int, float)):
                secondary.append({"label": "Time left", "value": duration_short(left), "part": "left"})
            share = round(float(completion), 1) if done else None
            return WidgetData(
                status=_status(word),
                primary={"label": word, "value": share, "unit": "%" if share is not None else ""},
                secondary=secondary,
                metrics=measured({"progress": share}),
                meta={"state": word},
            )
        if word == "Ready" and done and float(completion) >= 100:
            # ⚠️ A finished print stays on the job: 100 % in the state Operational.
            if isinstance(elapsed, (int, float)):
                secondary.append({"label": "Elapsed", "value": duration_short(elapsed), "part": "elapsed"})
            return WidgetData(status="ok", primary={"label": "Finished", "value": 100.0, "unit": "%"},
                              secondary=secondary, meta={"state": "Finished"})
        if word == "Ready":
            estimate = details.get("estimatedPrintTime")
            if name and isinstance(estimate, (int, float)):
                secondary.append({"label": "Estimated", "value": duration_short(estimate), "part": "left"})
            return WidgetData(status="ok", primary={"label": "Print job", "value": "Ready" if name else "Nothing selected"},
                              secondary=secondary, meta={"state": "Ready"})
        return WidgetData(
            status=_status(word), primary={"label": "Print job", "value": word}, secondary=secondary,
            meta={"state": word, "status_reason": str(job.get("error") or "")},
        )

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        cycle = tick % 120
        printing = cycle < 100
        heated = printing and cycle > 8
        nozzle = 214.6 + fake.walk("octoprint-nozzle", tick, -0.6, 0.6) if heated else 21.0 + cycle % 9 * 20
        bed = 60.0 + fake.walk("octoprint-bed", tick, -0.3, 0.3) if heated else 22.0 + cycle % 9 * 4
        if widget_kind == "job":
            if not printing:
                return self._job_card({"state": "Operational", "job": {"file": {"display": "benchy.gcode"}},
                                       "progress": {"completion": 100.0, "printTime": 5820, "printTimeLeft": 0}})
            return self._job_card({"state": "Printing", "job": {"file": {"display": "benchy.gcode"}, "estimatedPrintTime": 5900},
                                   "progress": {"completion": cycle, "printTime": cycle * 58, "printTimeLeft": (100 - cycle) * 58}})
        return self._printer_card({
            "state": {"text": "Printing" if printing else "Operational", "flags": {"printing": printing, "ready": not printing, "operational": True}},
            "temperature": {"tool0": {"actual": round(nozzle, 1), "target": 215.0 if printing else 0.0},
                            "bed": {"actual": round(bed, 1), "target": 60.0 if printing else 0.0}},
        }, None)


ADAPTER = OctoPrintAdapter()
