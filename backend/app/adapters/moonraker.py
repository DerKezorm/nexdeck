"""Moonraker: what a Klipper printer is doing, how hot it is, and how far the print has got.

Measured on 27.10.2026 against Moonraker (API 1.5.0) with Klipper
``ee2c6fb``, from ``ghcr.io/mainsail-crew/virtual-klipper-printer``: Klipper
on a simulated microcontroller, so the heaters are faked and never get hot.
Measured: ready and idle, a print that stopped with an error, a printer in
shutdown, Klipper not running at all, and a Moonraker that trusts only
127.0.0.1 and asks every other client for its API key. Not measured: a print
that is running, paused or finished. The simulated printer cannot home, and a
heater with a target shuts it down; those states are built from the Moonraker
and Klipper documentation.

⚠️ ``/server/info`` answers whenever Moonraker is up, with ``klippy_state``
and ``klippy_connected``. Everything that asks Klipper (``/printer/...``)
answers 503 "Klippy Host not connected" while Klipper is down, and 400
"Printer is not ready" while it starts. The card asks ``/server/info`` first
and only then the printer.

⚠️ ``moonraker_version`` is ``?`` in a build without a git checkout.

⚠️ An error body carries a Python traceback in ``error.traceback``. It is
never shown; ``error.message`` is.

⚠️ A print that stops on an error ends in ``print_stats.state`` ``error``
with the reason in ``print_stats.message`` ("Must home axis first: ..."), and
the file stays selected. ``display_status.progress`` and
``virtual_sdcard.progress`` stand at where it stopped.

⚠️ ``pause_resume.is_paused`` can be true while ``print_stats.state`` says
``error``; the card goes by ``print_stats``.

⚠️ Moonraker trusts addresses named in ``trusted_clients`` and asks all
others for an API key (``X-Api-Key``), or a login when ``force_logins`` is on.
Only the API key is spoken here; the key is shown in Mainsail and Fluidd
under their settings.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

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
    base_url,
    duration_short,
    gauge_view_field,
    measured,
)

KEY_HINT = "Copy the API key from the settings of Mainsail or Fluidd, or add the address of nexdeck to trusted_clients in moonraker.conf."
ADDRESS_HINT = "Check the URL; it is the address Moonraker listens on, usually port 7125."
#: What a print says about itself, in the card's words.
PRINT_WORDS = {"standby": "Ready", "printing": "Printing", "paused": "Paused", "complete": "Finished",
               "cancelled": "Cancelled", "error": "Error"}
#: What Klipper itself says, when it is not ready.
KLIPPY_WORDS = {"startup": "Starting", "shutdown": "Shutdown", "error": "Error", "disconnected": "Offline"}


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _temperature(entry: Any) -> str:
    actual = _number(entry.get("temperature")) if isinstance(entry, dict) else None
    if actual is None:
        return "?"
    target = _number(entry.get("target"))
    if target is not None and target > 0:
        return f"{actual:.1f} / {target:.0f} °C"
    return f"{actual:.1f} °C"


def _status(word: str) -> str:
    if word in ("Error", "Shutdown"):
        return "bad"
    if word in ("Paused", "Starting"):
        return "warn"
    if word in ("Offline", "Cancelled"):
        return "unknown"
    return "ok"


def _file(name: Any) -> str:
    """The file name without the folders in front of it."""
    return str(name or "").replace("\\", "/").rsplit("/", 1)[-1]


class MoonrakerAdapter(Adapter):
    kind = "moonraker"
    label = "Moonraker"
    category = "other"
    description = "What a Klipper 3D printer is doing, its temperatures, and how far the print has got."
    icon = "moonraker"
    beta = True
    docs_url = "https://moonraker.readthedocs.io/en/latest/external_api/introduction/"
    keywords = ("Klipper", "3D printer", "Fluidd", "Mainsail")
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://printer:7125",
              help="The address Moonraker listens on, usually port 7125."),
        Field("api_key", "API key", type="password", secret=True,
              help="Only if Moonraker does not trust this address (trusted_clients in moonraker.conf). Mainsail and Fluidd show the key in their settings."),
        Field("web_url", "Web interface", type="url", placeholder="http://printer",
              help="Where Mainsail or Fluidd opens, for the link on the cards. Optional."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="printer", label="Printer",
                   description="Whether the printer is ready, printing, paused or in trouble, with the nozzle, bed and chamber temperatures.",
                   renderer="value", default_size=(3, 2), refresh_seconds=15, metrics=("nozzle_temp", "bed_temp"),
                   parts=(("nozzle", "Nozzle"), ("bed", "Bed"), ("chamber", "Chamber"))),
        WidgetType(kind="job", label="Print job",
                   description="The file being printed, how far it is, the time it has taken, the time it still needs and the layer. Pause, resume or cancel it from here.",
                   renderer="value", default_size=(3, 2), refresh_seconds=10, metrics=("progress",),
                   parts=(("file", "File"), ("elapsed", "Elapsed"), ("left", "Time left"), ("layer", "Layer")),
                   options=(gauge_view_field(),)),
        WidgetType(kind="history", label="Print history",
                   description="How many prints Moonraker has recorded, the time spent printing and the filament used.",
                   renderer="stats", default_size=(3, 2), refresh_seconds=300, metrics=("jobs",),
                   parts=(("time", "Print time"), ("filament", "Filament"), ("longest", "Longest print"))),
    )

    def default_link(self, config: dict[str, Any]) -> str:
        return base_url(config, "web_url") or base_url(config)

    # -- talking to Moonraker ------------------------------------------------

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        key = str(config.get("api_key") or "").strip()
        if key:
            headers["X-Api-Key"] = key
        return headers

    async def _call(self, method: str, config: dict[str, Any], ctx: Context, path: str, *,
                    allow: tuple[int, ...] = (), cache: float = 0) -> tuple[int, Any]:
        response = await ctx.request(
            method, f"{base_url(config)}{path}", headers=self._headers(config), verify=not config.get("insecure"),
            timeout=10.0, cache_seconds=cache if method == "GET" else 0, auth_errors=False)
        if response.status_code in (401, 403):
            # ⚠️ A key that is missing and one that is wrong get the same 401.
            error = AuthFailed("Moonraker does not trust this client." if not self._headers(config).get("X-Api-Key")
                               else "Moonraker does not know this API key.")
            error.hint = KEY_HINT
            raise error
        try:
            body = response.json()
        except ValueError as error:
            raise AdapterError("This address answers with something other than Moonraker.", code="not_moonraker",
                               hint=ADDRESS_HINT) from error
        if response.status_code >= 400 and response.status_code not in allow:
            detail = body.get("error") if isinstance(body, dict) and isinstance(body.get("error"), dict) else {}
            # The message, never the traceback that comes with it.
            raise AdapterError(f"Moonraker answered with HTTP {response.status_code}: {str(detail.get('message') or '').strip() or 'no reason given'}.",
                               code="http_error", hint=ADDRESS_HINT)
        if not isinstance(body, dict):
            raise AdapterError("This address answers, but not the way Moonraker does.", code="not_moonraker", hint=ADDRESS_HINT)
        return response.status_code, body.get("result")

    async def _server(self, config: dict[str, Any], ctx: Context) -> dict[str, Any]:
        _, info = await self._call("GET", config, ctx, "/server/info", cache=5)
        if not isinstance(info, dict) or "klippy_state" not in info:
            raise AdapterError("This address answers, but not the way Moonraker does.", code="not_moonraker", hint=ADDRESS_HINT)
        return info

    async def _why_not_ready(self, config: dict[str, Any], ctx: Context) -> str:
        """What Klipper says about itself, when it is connected but not ready. Empty when it says nothing."""
        try:
            code, info = await self._call("GET", config, ctx, "/printer/info", allow=(400, 503), cache=5)
        except AdapterError:
            return ""
        if code < 400 and isinstance(info, dict):
            return str(info.get("state_message") or "").strip()
        return ""

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        info = await self._server(config, ctx)
        version = str(info.get("moonraker_version") or "").strip()
        named = f"Moonraker {version}" if version and version != "?" else "Moonraker"
        word = "Ready" if info.get("klippy_state") == "ready" else KLIPPY_WORDS.get(str(info.get("klippy_state")), "Unknown")
        return f"{named} answers. Klipper: {word}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "history":
            _, totals = await self._call("GET", config, ctx, "/server/history/totals", allow=(404,), cache=30)
            if totals is None:
                raise AdapterError("Moonraker keeps no print history.", code="no_history",
                                   hint="Add a [history] section to moonraker.conf and restart Moonraker.")
            return self._history_card(totals)
        info = await self._server(config, ctx)
        if info.get("klippy_state") != "ready":
            return self._not_ready(info, await self._why_not_ready(config, ctx) if info.get("klippy_connected") else "")
        _, objects = await self._call("GET", config, ctx, "/printer/objects/list", cache=60)
        names = [str(name) for name in (objects.get("objects") if isinstance(objects, dict) else None) or []]
        wanted = ["print_stats", "display_status", "virtual_sdcard", "pause_resume"]
        wanted += [name for name in names if name == "extruder" or (name.startswith("extruder") and name[8:].isdigit())]
        wanted += [name for name in names if name == "heater_bed" or name.startswith("heater_generic ")]
        wanted += [name for name in names if name.startswith("temperature_sensor ") and "chamber" in name.lower()]
        query = "&".join(quote(name, safe="") for name in wanted if name in names)
        _, state = await self._call("GET", config, ctx, f"/printer/objects/query?{query}", cache=3)
        status = state.get("status") if isinstance(state, dict) and isinstance(state.get("status"), dict) else {}
        return self._printer_card(status) if widget_kind == "printer" else self._job_card(status)

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        words = {"pause": "Print paused.", "resume": "Print resumed.", "cancel": "Print cancelled."}
        if action_id not in words:
            raise AdapterError("Unknown print action.", code="no_such_action")
        await self._call("POST", config, ctx, f"/printer/print/{action_id}")
        ctx.forget_answers()
        return words[action_id]

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _not_ready(info: dict[str, Any], reason: str) -> WidgetData:
        word = KLIPPY_WORDS.get(str(info.get("klippy_state")), "Unknown")
        return WidgetData(status=_status(word) if word != "Unknown" else "unknown", primary={"label": "State", "value": word},
                          meta={"status_reason": reason or ("Klipper is not running." if word == "Offline" else "")})

    @staticmethod
    def _print_word(status: dict[str, Any]) -> str:
        stats = status.get("print_stats") if isinstance(status.get("print_stats"), dict) else {}
        return PRINT_WORDS.get(str(stats.get("state") or ""), "Unknown")

    @classmethod
    def _printer_card(cls, status: dict[str, Any]) -> WidgetData:
        stats = status.get("print_stats") if isinstance(status.get("print_stats"), dict) else {}
        word = cls._print_word(status)
        secondary: list[dict[str, Any]] = []
        nozzles = sorted((name for name in status if name == "extruder" or (name.startswith("extruder") and name[8:].isdigit())),
                         key=lambda name: int(name[8:] or 0))
        for index, name in enumerate(nozzles):
            secondary.append({"label": "Nozzle" if len(nozzles) == 1 else f"Nozzle {index + 1}", "value": _temperature(status[name]), "part": "nozzle"})
        # ⚠️ Only there when the printer has one.
        if "heater_bed" in status:
            secondary.append({"label": "Bed", "value": _temperature(status["heater_bed"]), "part": "bed"})
        for name, entry in status.items():
            if name.startswith("heater_generic ") or name.startswith("temperature_sensor "):
                row = {"label": "Chamber" if "chamber" in name.lower() else name.split(" ", 1)[1], "value": _temperature(entry)}
                if "chamber" in name.lower():
                    row["part"] = "chamber"
                secondary.append(row)

        def actual(name: str) -> float | None:
            entry = status.get(name)
            return _number(entry.get("temperature")) if isinstance(entry, dict) else None

        return WidgetData(
            status=_status(word),
            primary={"label": "State", "value": word},
            secondary=secondary,
            metrics=measured({"nozzle_temp": actual(nozzles[0]) if nozzles else None, "bed_temp": actual("heater_bed")}),
            meta={"status_reason": str(stats.get("message") or "").strip() if word == "Error" else ""},
        )

    @classmethod
    def _job_card(cls, status: dict[str, Any]) -> WidgetData:
        stats = status.get("print_stats") if isinstance(status.get("print_stats"), dict) else {}
        sdcard = status.get("virtual_sdcard") if isinstance(status.get("virtual_sdcard"), dict) else {}
        word = cls._print_word(status)
        name = _file(stats.get("filename"))
        elapsed = _number(stats.get("print_duration"))
        fraction = _number(sdcard.get("progress"))
        share = round(max(0.0, min(1.0, fraction)) * 100, 1) if fraction is not None else None
        secondary: list[dict[str, Any]] = []
        if name:
            secondary.append({"label": "File", "value": name, "part": "file"})

        if word in ("Printing", "Paused"):
            if elapsed is not None:
                secondary.append({"label": "Elapsed", "value": duration_short(elapsed), "part": "elapsed"})
            # ⚠️ An estimate from the pace so far, so not before the print has got a little way; the slicer's own
            # figure is not asked for, since Moonraker only has it for files it has read.
            if elapsed and fraction and fraction >= 0.01:
                secondary.append({"label": "Time left", "value": duration_short(elapsed / fraction - elapsed), "part": "left"})
            info = stats.get("info") if isinstance(stats.get("info"), dict) else {}
            layer, total = _number(info.get("current_layer")), _number(info.get("total_layer"))
            if layer is not None and total:
                secondary.append({"label": "Layer", "value": f"{int(layer)} / {int(total)}", "part": "layer"})
            actions = [Action(id="pause" if word == "Printing" else "resume", label="Pause" if word == "Printing" else "Resume",
                              icon="pause" if word == "Printing" else "play"),
                       Action(id="cancel", label="Cancel print", icon="x", confirm=True, danger=True)]
            return WidgetData(status=_status(word), primary={"label": word, "value": share, "unit": "%" if share is not None else ""},
                              secondary=secondary, actions=actions, metrics=measured({"progress": share}), meta={"state": word})
        if word == "Finished":
            if _number(stats.get("total_duration")) is not None:
                secondary.append({"label": "Elapsed", "value": duration_short(_number(stats.get("total_duration"))), "part": "elapsed"})
            return WidgetData(status="ok", primary={"label": "Finished", "value": 100.0, "unit": "%"},
                              secondary=secondary, meta={"state": "Finished"})
        if word == "Ready":
            return WidgetData(status="ok", primary={"label": "Print job", "value": "Ready" if name else "Nothing selected"},
                              secondary=secondary, meta={"state": "Ready"})
        return WidgetData(
            status=_status(word), primary={"label": "Print job", "value": word}, secondary=secondary,
            meta={"state": word, "status_reason": str(stats.get("message") or "").strip() if word == "Error" else ""},
        )

    @staticmethod
    def _history_card(totals: Any) -> WidgetData:
        job = totals.get("job_totals") if isinstance(totals, dict) and isinstance(totals.get("job_totals"), dict) else {}
        jobs = _number(job.get("total_jobs")) or 0.0
        printing = _number(job.get("total_print_time")) or 0.0
        filament = _number(job.get("total_filament_used")) or 0.0
        longest = _number(job.get("longest_print")) or 0.0
        return WidgetData(
            primary={"label": "Prints", "value": int(jobs)},
            secondary=[
                {"label": "Print time", "value": duration_short(printing), "part": "time"},
                # ⚠️ Moonraker counts filament in millimetres.
                {"label": "Filament", "value": f"{filament / 1000:.1f} m", "part": "filament"},
                {"label": "Longest print", "value": duration_short(longest), "part": "longest"},
            ],
            metrics={"jobs": jobs},
        )

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        cycle = tick % 120
        printing = cycle < 100
        heated = printing and cycle > 8
        nozzle = 214.6 + fake.walk("moonraker-nozzle", tick, -0.6, 0.6) if heated else 24.0 + cycle % 9 * 20
        bed = 60.0 + fake.walk("moonraker-bed", tick, -0.3, 0.3) if heated else 23.0 + cycle % 9 * 4
        if widget_kind == "history":
            return self._history_card({"job_totals": {"total_jobs": 128 + tick // 120, "total_print_time": 1_020_000 + tick * 10,
                                                      "total_filament_used": 412_000_000 + tick * 500, "longest_print": 61_200}})
        if widget_kind == "job":
            if not printing:
                return self._job_card({"print_stats": {"state": "complete", "filename": "benchy.gcode", "total_duration": 5820.0},
                                       "virtual_sdcard": {"progress": 1.0}})
            return self._job_card({"print_stats": {"state": "printing", "filename": "benchy.gcode", "print_duration": cycle * 58.0,
                                                   "info": {"current_layer": cycle * 2, "total_layer": 200}},
                                   "virtual_sdcard": {"progress": cycle / 100}})
        return self._printer_card({
            "print_stats": {"state": "printing" if printing else "standby"},
            "extruder": {"temperature": round(nozzle, 1), "target": 215.0 if printing else 0.0},
            "heater_bed": {"temperature": round(bed, 1), "target": 60.0 if printing else 0.0},
            "temperature_sensor chamber": {"temperature": round(31.0 + fake.walk("moonraker-chamber", tick, 0, 6), 1)},
        })


ADAPTER = MoonrakerAdapter()
