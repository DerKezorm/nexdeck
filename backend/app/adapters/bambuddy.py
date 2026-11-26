"""Bambuddy: what the Bambu Lab printers it manages are doing, what sits in their AMS, and what waits in its queue.

Built from the code of Bambuddy 1.3.2 (tag ``v1.3.2``, commit ``b7d894b``, 26.11.2026), not run against an
installation, hence beta. Where each answer comes from:

- ``GET /api/v1/updates/version``: ``{"version", "repo"}``, without a sign-in (``backend/app/api/routes/updates.py``).
- ``GET /api/v1/printers/``: the printers the caller may see, ordered by name, each with ``id``, ``name``, ``model``
  and ``is_active`` (``list_printers`` in ``routes/printers.py``, ``PrinterResponse`` in ``schemas/printer.py``).
- ``GET /api/v1/printers/{id}/status``: ``PrinterStatus`` in ``schemas/printer.py``, filled by ``_printer_status`` in
  ``routes/printers.py``. ``connected``; ``state`` is the printer's own ``gcode_state`` (IDLE, PREPARE, SLICING,
  RUNNING, PAUSE, FINISH, FAILED, or ``unknown`` before the first report, ``services/bambu_mqtt.py``);
  ``subtask_name``, ``current_print``, ``gcode_file``; ``progress`` in per cent (``mc_percent``);
  ``remaining_time`` in minutes (``mc_remaining_time``); ``layer_num``, ``total_layers``; ``temperatures`` with
  ``nozzle``, ``nozzle_target``, ``bed``, ``bed_target``, ``chamber`` (left out for models without a sensor),
  ``nozzle_2`` and ``nozzle_2_target`` on two nozzles; ``hms_errors`` with ``severity`` (1 error, 2 warning,
  3 notification) and ``description``; ``ams``, a list of units (``AMSUnit``: ``id``, ``is_ams_ht``,
  ``module_type``, ``tray``) and ``vt_tray``, the external spools. A tray (``AMSTray``, serialised by
  ``ams_units_to_dicts`` in ``services/printer_manager.py``) carries ``id``, ``tray_type`` ("PLA"),
  ``tray_sub_brands`` ("PLA Basic"), ``tray_color`` (``RRGGBBAA``), ``remain`` in per cent and ``exists``.
- ``GET /api/v1/archives/last-per-printer``: the latest print of every printer (``routes/archives.py``), with
  ``printer_id``, ``print_name``, ``status`` (``printing`` while it runs, then completed, failed, stopped or
  cancelled) and ``completed_at``.
- ``GET /api/v1/queue/?status=pending,printing``: queue items in the order they are started (``list_queue`` in
  ``routes/print_queue.py``, ``PrintQueueItemResponse`` in ``schemas/print_queue.py``) with ``status``,
  ``archive_name`` or ``library_file_name``, ``printer_name``, ``target_model`` and ``print_time_seconds``.

The key goes in ``X-API-Key`` (``require_auth_if_enabled`` and ``_validate_api_key`` in ``core/auth.py``); keys start
with ``bb_``. Every read here needs a key with "read status" (``can_read_status``), and a key reaches only the
printers of whoever made it. A Bambuddy without sign-in answers without a key. 401 says the key is unknown, expired or
missing; 403 names what the key lacks, in ``detail``.

⚠️ Bambuddy answers every path it does not know with its web page (``/{full_path:path}`` in ``main.py``), 200 and
HTML: an address with a wrong path looks reachable, and only the body tells.

⚠️ ``remain`` is what the AMS reads off a Bambu spool's tag; a spool without one reports -1, which is no level.
Read only: the cards never pause, stop or start anything.
"""

from __future__ import annotations

import re
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
    base_url,
    duration_short,
    measured,
)

API = "/api/v1"
ADDRESS_HINT = "Check the URL; it is the address Bambuddy's web interface opens at, usually port 8000."
KEY_HINT = "Make a key in Bambuddy under Settings > API Keys and give it the permission to read status."
PICK_HINT = "Pick a printer in the card's settings."
LOW_PERCENT = 15

#: The printer's own state (``gcode_state``), in the card's words.
STATE_WORDS = {"IDLE": "Idle", "PREPARE": "Preparing", "SLICING": "Slicing", "RUNNING": "Printing", "PAUSE": "Paused",
               "FINISH": "Finished", "FAILED": "Failed"}
#: How a print ended, as the archive writes it, in the words of the line that tells the last one.
LAST_WORDS = {"completed": "Last print", "failed": "Last print failed", "stopped": "Last print stopped",
              "cancelled": "Last print cancelled"}
HEX = re.compile(r"^[0-9A-Fa-f]{6}")


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _status(word: str) -> str:
    if word == "Failed":
        return "bad"
    if word == "Paused":
        return "warn"
    if word in ("Offline", "Unknown"):
        return "unknown"
    return "ok"


def _word(status: dict[str, Any]) -> str:
    if not status.get("connected"):
        return "Offline"
    return STATE_WORDS.get(str(status.get("state") or "").upper(), "Unknown")


def _job(status: dict[str, Any]) -> str:
    """The name of the print: Bambuddy prefers the subtask's name and falls back on the file, as its own card does."""
    name = str(status.get("subtask_name") or status.get("current_print") or status.get("gcode_file") or "").strip()
    return name.replace("\\", "/").rsplit("/", 1)[-1]


def _temperature(temps: dict[str, Any], name: str) -> str | None:
    actual = _number(temps.get(name))
    if actual is None:
        return None
    target = _number(temps.get(f"{name}_target"))
    if target is not None and target > 0:
        return f"{actual:.0f} / {target:.0f} °C"
    return f"{actual:.0f} °C"


def _trouble(status: dict[str, Any]) -> tuple[str, str]:
    """The worst HMS message the printer holds, as a status and its words: 1 stops a print, 2 pauses it, 3 only tells."""
    worst, said = "", ""
    for error in status.get("hms_errors") or []:
        if not isinstance(error, dict):
            continue
        severity = _number(error.get("severity"))
        text = str(error.get("description") or "").strip() or f"HMS {error.get('full_code') or error.get('code') or '?'}"
        if severity == 1:
            return "bad", text
        if severity == 2 and not worst:
            worst, said = "warn", text
    return worst, said


def _swatch(colour: Any) -> str:
    """The colour of a spool as ``#rrggbb``: Bambu writes ``RRGGBBAA``, and an empty slot ``00000000``."""
    text = str(colour or "").lstrip("#")
    return f"#{text[:6].lower()}" if HEX.match(text) else ""


def _slot_label(unit: dict[str, Any], tray: dict[str, Any]) -> str:
    """A slot named the way Bambuddy names it (``formatSlotLabel`` in ``frontend/src/utils/amsHelpers.ts``)."""
    unit_id = int(_number(unit.get("id")) or 0)
    tray_id = int(_number(tray.get("id")) or 0)
    if unit.get("module_type") == "n10a":
        return f"3H-{tray_id + 1}"
    letter = chr(65 + max(0, min(25, unit_id - 128 if unit_id >= 128 else unit_id)))
    if unit.get("is_ams_ht"):
        return f"HT-{letter}"
    return f"{letter}{tray_id + 1}"


def _low_line(options: dict[str, Any]) -> float:
    line = _number(options.get("low_percent"))
    return min(100.0, max(1.0, line)) if line is not None else float(LOW_PERCENT)


def _limit(options: dict[str, Any], default: int = 8) -> int:
    count = _number(options.get("limit"))
    return max(1, min(50, int(count))) if count else default


class BambuddyAdapter(Adapter):
    kind = "bambuddy"
    label = "Bambuddy"
    category = "other"
    description = "What the Bambu Lab printers in Bambuddy are doing, the spools in their AMS, and the print queue."
    icon = "bambuddy"
    beta = True
    docs_url = "https://wiki.bambuddy.cool/"
    keywords = ("Bambu Lab", "3D printer", "AMS", "filament")
    #: ``/printers/{id}/camera/stop`` is a GET that ends the camera streams of everybody watching.
    raw_read_commands = ReadCommands(words=frozenset({"stop"}))
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://bambuddy:8000",
              help="The address Bambuddy's web interface opens at."),
        Field("api_key", "API key", type="password", secret=True,
              help="Settings > API Keys in Bambuddy, with the permission to read status. Not needed while Bambuddy runs without sign-in."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="printer", label="Printer",
            description="Whether a printer is idle, printing, paused or in trouble, its job with progress and time left, the nozzle and bed temperatures, and its last print.",
            renderer="value", default_size=(3, 3), refresh_seconds=15, metrics=("progress", "nozzle_temp", "bed_temp"),
            parts=(("job", "Job"), ("left", "Time left"), ("layer", "Layer"), ("nozzle", "Nozzle"), ("bed", "Bed"),
                   ("chamber", "Chamber"), ("last", "Last print")),
            options=(Field("printer", "Printer", type="choices", help="Empty takes the first printer."),),
        ),
        WidgetType(
            kind="ams", label="AMS", bars=True,
            description="Each slot of a printer's AMS with its filament, colour and what is left on the spool.",
            renderer="list", default_size=(3, 3), refresh_seconds=60,
            options=(
                Field("printer", "Printer", type="choices", help="Empty takes the first printer."),
                Field("low_percent", "Running low below (%)", type="number", default=LOW_PERCENT),
                Field("external", "External spool", type="bool", default=True),
            ),
        ),
        WidgetType(
            kind="printers", label="Printers",
            description="Every printer with its state, its job and how far the print has got.",
            renderer="list", default_size=(3, 3), refresh_seconds=30,
        ),
        WidgetType(
            kind="queue", label="Print queue",
            description="The jobs waiting in Bambuddy's queue, in the order they will start, and the ones printing now.",
            renderer="list", default_size=(3, 3), refresh_seconds=60, metrics=("waiting",),
            options=(
                Field("printer", "Printer", type="choices", help="Empty shows the queue of every printer."),
                Field("limit", "Entries", type="number", default=8),
            ),
        ),
    )

    # -- talking to Bambuddy -------------------------------------------------

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        key = str(config.get("api_key") or "").strip()
        if key:
            headers["X-API-Key"] = key
        return headers

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, *, params: dict[str, Any] | None = None,
                   cache: float = 0, missing: tuple[str, str, str] | None = None) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}{API}{path}", headers=self._headers(config), params=params,
            verify=not config.get("insecure"), timeout=10.0, cache_seconds=cache, auth_errors=False)
        try:
            body = response.json()
        except ValueError:
            body = None
        detail = str(body.get("detail") or "").strip() if isinstance(body, dict) and isinstance(body.get("detail"), str) else ""
        if response.status_code == 401:
            refused = AuthFailed("Bambuddy refused the API key." if self._headers(config).get("X-API-Key")
                                 else "Bambuddy asks for an API key.", status=401)
            refused.hint = KEY_HINT
            raise refused
        if response.status_code == 403:
            refused = AuthFailed(f"Bambuddy refused: {detail or 'not allowed'}.", status=403)
            refused.hint = KEY_HINT
            raise refused
        if response.status_code == 404 and missing:
            raise AdapterError(missing[0], code=missing[1], hint=missing[2])
        if response.status_code >= 400:
            raise AdapterError(f"Bambuddy answered with HTTP {response.status_code}: {detail or 'no reason given'}.",
                               code="http_error", hint=ADDRESS_HINT)
        if body is None:
            # ⚠️ Its web page answers every unknown path with 200.
            raise AdapterError("This address answers with something other than Bambuddy.", code="not_bambuddy", hint=ADDRESS_HINT)
        return body

    async def _printers(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        found = await self._get(config, ctx, "/printers/", cache=60)
        if not isinstance(found, list):
            raise AdapterError("This address answers, but not the way Bambuddy does.", code="not_bambuddy", hint=ADDRESS_HINT)
        return [one for one in found if isinstance(one, dict) and one.get("id") is not None]

    async def _chosen(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> dict[str, Any]:
        """The printer a card shows: the one picked, or the first one Bambuddy lists."""
        printers = await self._printers(config, ctx)
        wanted = str(options.get("printer") or "").strip()
        if not wanted:
            if not printers:
                raise AdapterError("Bambuddy has no printer, or the key may not see one.", code="no_printer", hint=KEY_HINT)
            return printers[0]
        for one in printers:
            if str(one.get("id")) == wanted:
                return one
        raise AdapterError("Bambuddy has no such printer, or the key may not see it.", code="no_printer", hint=PICK_HINT)

    async def _printer_status(self, config: dict[str, Any], ctx: Context, printer: dict[str, Any]) -> dict[str, Any]:
        number = int(_number(printer.get("id")) or 0)
        found = await self._get(config, ctx, f"/printers/{number}/status", cache=5, missing=(
            "Bambuddy has no such printer, or the key may not see it.", "no_printer", PICK_HINT))
        if not isinstance(found, dict):
            raise AdapterError("This address answers, but not the way Bambuddy does.", code="not_bambuddy", hint=ADDRESS_HINT)
        return found

    async def _last_prints(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        """The latest print of every printer; nothing when Bambuddy does not answer it.

        ⚠️ Only a line on the card, so anything but a refused key leaves it out: a Bambuddy without the route reads
        ``last-per-printer`` as the number of an archive and answers 422.
        """
        try:
            found = await self._get(config, ctx, "/archives/last-per-printer", cache=60)
        except AuthFailed:
            raise
        except AdapterError:
            return []
        return [one for one in found if isinstance(one, dict)] if isinstance(found, list) else []

    # -- the hooks -----------------------------------------------------------

    async def choices(self, field: str, config: dict[str, Any], ctx: Context) -> list[tuple[str, str]]:
        if field != "printer":
            return await super().choices(field, config, ctx)
        return [(str(one["id"]), self._printer_name(one)) for one in await self._printers(config, ctx)]

    def demo_choices(self, field: str) -> list[tuple[str, str]]:
        if field != "printer":
            return []
        return [(str(one["id"]), self._printer_name(one)) for one in DEMO_PRINTERS]

    @staticmethod
    def _printer_name(printer: dict[str, Any]) -> str:
        name = str(printer.get("name") or "?")
        model = str(printer.get("model") or "").strip()
        return f"{name} ({model})" if model else name

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        info = await self._get(config, ctx, "/updates/version")
        if not isinstance(info, dict) or "version" not in info:
            raise AdapterError("This address answers, but not the way Bambuddy does.", code="not_bambuddy", hint=ADDRESS_HINT)
        count = len(await self._printers(config, ctx))
        return f"Bambuddy {info['version']} answers with {count} printers."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "queue":
            params: dict[str, Any] = {"status": "pending,printing"}
            wanted = str(options.get("printer") or "").strip()
            if wanted:
                if not wanted.isdigit():
                    raise AdapterError("Bambuddy has no such printer, or the key may not see it.", code="no_printer", hint=PICK_HINT)
                params["printer_id"] = wanted
            items = await self._get(config, ctx, "/queue/", params=params, cache=30)
            if not isinstance(items, list):
                raise AdapterError("This address answers, but not the way Bambuddy does.", code="not_bambuddy", hint=ADDRESS_HINT)
            return self._queue_card([one for one in items if isinstance(one, dict)], options)
        if widget_kind == "printers":
            rows = [(printer, await self._printer_status(config, ctx, printer)) for printer in await self._printers(config, ctx)]
            return self._printers_card(rows)
        printer = await self._chosen(config, options, ctx)
        status = await self._printer_status(config, ctx, printer)
        if widget_kind == "ams":
            return self._ams_card(status, options)
        last = next((one for one in await self._last_prints(config, ctx)
                     if str(one.get("printer_id")) == str(printer.get("id"))), None)
        return self._printer_card(status, last)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _printer_card(status: dict[str, Any], last: dict[str, Any] | None) -> WidgetData:
        word = _word(status)
        temps = status.get("temperatures") if isinstance(status.get("temperatures"), dict) else {}
        running = word in ("Printing", "Paused")
        secondary: list[dict[str, Any]] = []
        # The latest print, once it has ended: while one runs, the archive's latest is that one.
        ended = (last if last and not running and str(last.get("status") or "") in LAST_WORDS and last.get("print_name")
                 else None)
        job = _job(status)
        # ⚠️ The printer keeps the name of a print after it ended; the line of the last print says it then.
        if job and word not in ("Idle", "Offline") and not (ended and word in ("Finished", "Failed")):
            secondary.append({"label": "Job", "value": job, "part": "job"})
        progress = _number(status.get("progress"))
        share = round(max(0.0, min(100.0, progress)), 1) if running and progress is not None else None
        if running:
            minutes = _number(status.get("remaining_time"))
            if minutes is not None and minutes > 0:
                secondary.append({"label": "Time left", "value": duration_short(minutes * 60), "part": "left"})
            layer, total = _number(status.get("layer_num")), _number(status.get("total_layers"))
            if layer is not None and total:
                secondary.append({"label": "Layer", "value": f"{int(layer)} / {int(total)}", "part": "layer"})
        if word != "Offline":
            two = _number(temps.get("nozzle_2")) is not None
            for name, label in (("nozzle", "Nozzle 1" if two else "Nozzle"), ("nozzle_2", "Nozzle 2")):
                shown = _temperature(temps, name)
                if shown:
                    secondary.append({"label": label, "value": shown, "part": "nozzle"})
            for name, label in (("bed", "Bed"), ("chamber", "Chamber")):
                shown = _temperature(temps, name)
                if shown:
                    secondary.append({"label": label, "value": shown, "part": name})
        if ended:
            secondary.append({"label": LAST_WORDS[str(ended["status"])], "value": str(ended["print_name"]), "part": "last"})

        state = _status(word)
        reason = "The last print failed." if word == "Failed" else ""
        trouble, said = _trouble(status) if word != "Offline" else ("", "")
        if trouble == "bad" or (trouble == "warn" and state == "ok"):
            state, reason = trouble, said
        if word == "Offline":
            reason = "Bambuddy is not connected to this printer."
        primary = ({"label": word, "value": share, "unit": "%"} if share is not None
                   else {"label": "State", "value": word})
        return WidgetData(
            status=state,
            primary=primary,
            secondary=secondary,
            metrics=measured({"progress": share, "nozzle_temp": _number(temps.get("nozzle")), "bed_temp": _number(temps.get("bed"))}),
            meta={"status_reason": reason, "state": word},
        )

    @staticmethod
    def _ams_card(status: dict[str, Any], options: dict[str, Any]) -> WidgetData:
        line = _low_line(options)
        items: list[dict[str, Any]] = []
        low = loaded = 0
        slots: list[tuple[dict[str, Any], dict[str, Any], str]] = []
        for unit in status.get("ams") or []:
            if isinstance(unit, dict):
                slots += [(unit, tray, _slot_label(unit, tray)) for tray in unit.get("tray") or [] if isinstance(tray, dict)]
        if options.get("external", True):
            external = [tray for tray in status.get("vt_tray") or [] if isinstance(tray, dict)]
            slots += [({}, tray, "Ext" if len(external) == 1 else f"Ext {index + 1}") for index, tray in enumerate(external)]
        for unit, tray, label in slots:
            kind = str(tray.get("tray_type") or "").strip()
            key = f"{unit.get('id', 'ext')}-{tray.get('id')}"
            if not kind:
                # ⚠️ A spool without a tag is in the slot (``exists``) but names no filament: not an empty slot.
                items.append({"id": key, "title": label, "subtitle": "Unknown filament" if tray.get("exists") is True else "Empty",
                              "value": "", "status": "unknown"})
                continue
            loaded += 1
            name = str(tray.get("tray_sub_brands") or "").strip() or kind
            remain = _number(tray.get("remain"))
            known = remain is not None and 0 <= remain <= 100
            is_low = known and remain < line
            low += int(is_low)
            item: dict[str, Any] = {
                "id": key,
                "title": f"{label} · {name}",
                "subtitle": kind if kind != name else "",
                "value": int(remain) if known else "?",
                "status": "warn" if is_low else "ok" if known else "unknown",
            }
            if known:
                item["unit"] = "%"
                item["progress"] = remain
            swatch = _swatch(tray.get("tray_color"))
            if swatch:
                item["swatch"] = swatch
            items.append(item)
        secondary: list[dict[str, Any]] = [{"label": "Spools", "value": loaded}]
        if low:
            secondary.append({"label": "Running low", "value": low})
        data = WidgetData(status="warn" if low else "ok", items=items, secondary=secondary,
                          metrics={"low_spools": float(low)})
        if not items:
            data.meta["empty"] = "This printer has no AMS and no external spool."
        return data

    @staticmethod
    def _printers_card(rows: list[tuple[dict[str, Any], dict[str, Any]]]) -> WidgetData:
        items: list[dict[str, Any]] = []
        printing = 0
        worst = "ok"
        for printer, status in rows:
            word = _word(status)
            state = _status(word)
            trouble, _said = _trouble(status) if word != "Offline" else ("", "")
            if trouble == "bad" or (trouble == "warn" and state == "ok"):
                state = trouble
            running = word in ("Printing", "Paused")
            printing += int(running)
            progress = _number(status.get("progress"))
            item: dict[str, Any] = {
                "id": printer.get("id"),
                "title": str(printer.get("name") or status.get("name") or "?"),
                "subtitle": _job(status) if running else str(printer.get("model") or ""),
                "value": word,
                "status": state,
            }
            if running and progress is not None:
                share = round(max(0.0, min(100.0, progress)), 1)
                item["value"] = f"{share:.0f} %"
                item["progress"] = share
            items.append(item)
            if state == "bad" or (state == "warn" and worst == "ok"):
                worst = state
        data = WidgetData(status=worst, items=items,
                          secondary=[{"label": "Printers", "value": len(rows)}, {"label": "Printing", "value": printing}],
                          metrics={"printing": float(printing)})
        if not items:
            data.meta["empty"] = "Bambuddy has no printer, or the key may not see one."
        return data

    @staticmethod
    def _queue_card(items: list[dict[str, Any]], options: dict[str, Any]) -> WidgetData:
        # Printing first, then the waiting ones in the order Bambuddy will start them (it sends them in that order).
        ordered = [one for one in items if one.get("status") == "printing"] + [one for one in items if one.get("status") == "pending"]
        waiting = sum(1 for one in items if one.get("status") == "pending")
        printing = len(ordered) - waiting
        rows = []
        for one in ordered[:_limit(options)]:
            name = str(one.get("archive_name") or one.get("library_file_name") or "?")
            where = str(one.get("printer_name") or one.get("target_model") or "").strip()
            estimate = _number(one.get("print_time_seconds"))
            rows.append({
                "id": one.get("id"),
                "title": name,
                "subtitle": " · ".join(part for part in ("Printing" if one.get("status") == "printing" else "", where) if part),
                "value": duration_short(estimate) if estimate else "",
                "status": "ok" if one.get("status") == "printing" else "unknown",
            })
        data = WidgetData(items=rows, secondary=[{"label": "Waiting", "value": waiting}, {"label": "Printing", "value": printing}],
                          metrics={"waiting": float(waiting)})
        if not rows:
            data.meta["empty"] = "The queue is empty."
        return data

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        cycle = tick % 150
        printing = cycle < 120
        progress = round(cycle / 120 * 100, 1)
        nozzle = 220.0 + fake.walk("bambuddy-nozzle", tick, -1.0, 1.0) if printing else 28.0
        bed = 65.0 + fake.walk("bambuddy-bed", tick, -0.4, 0.4) if printing else 26.0
        used = fake.walk("bambuddy-used", tick, 0, 12, period=900)
        first = {
            "id": 1, "name": "Workshop X1C", "connected": True, "state": "RUNNING" if printing else "FINISH",
            "subtask_name": "Planter_v3", "gcode_file": "/data/Metadata/plate_1.gcode", "progress": progress if printing else 100.0,
            "remaining_time": max(0, 120 - cycle) * 2 if printing else 0, "layer_num": int(cycle * 2.1), "total_layers": 252,
            "temperatures": {"nozzle": round(nozzle, 1), "nozzle_target": 220.0 if printing else 0.0, "bed": round(bed, 1),
                             "bed_target": 65.0 if printing else 0.0, "chamber": 34.0},
            "hms_errors": [],
            "ams": [
                {"id": 0, "is_ams_ht": False, "module_type": "ams", "tray": [
                    {"id": 0, "tray_type": "PLA", "tray_sub_brands": "PLA Basic", "tray_color": "F4EE2AFF", "remain": round(72 - used), "exists": True},
                    {"id": 1, "tray_type": "PLA", "tray_sub_brands": "PLA Matte", "tray_color": "000000FF", "remain": 41, "exists": True},
                    {"id": 2, "tray_type": "PETG", "tray_sub_brands": "PETG HF", "tray_color": "0A2989FF", "remain": 9, "exists": True},
                    {"id": 3, "tray_type": "", "tray_color": "00000000", "remain": 0, "exists": False},
                ]},
            ],
            "vt_tray": [{"id": 254, "tray_type": "TPU", "tray_sub_brands": "", "tray_color": "FFFFFFFF", "remain": -1}],
        }
        second = {"id": 2, "name": "Office A1 mini", "connected": True, "state": "IDLE", "temperatures": {"nozzle": 26.0, "bed": 24.0},
                  "ams": [], "vt_tray": []}
        if widget_kind == "printers":
            return self._printers_card([(DEMO_PRINTERS[0], first), (DEMO_PRINTERS[1], second)])
        if widget_kind == "queue":
            queue = [
                {"id": 11, "status": "printing", "archive_name": "Planter_v3", "printer_name": "Workshop X1C", "print_time_seconds": 15_120},
                {"id": 12, "status": "pending", "archive_name": "Cable clips x20", "printer_name": "Office A1 mini", "print_time_seconds": 2_700},
                {"id": 13, "status": "pending", "library_file_name": "Hinge bracket", "target_model": "X1C", "print_time_seconds": 6_300},
            ]
            return self._queue_card(queue if printing else queue[1:], options)
        chosen = second if str(options.get("printer") or "") == "2" else first
        if widget_kind == "ams":
            return self._ams_card(chosen, options)
        last = {"printer_id": 1, "print_name": "Planter_v3" if not printing else "Phone stand", "status": "completed"}
        return self._printer_card(chosen, last if chosen is first else {"printer_id": 2, "print_name": "Keychain", "status": "failed"})


#: The printers of the demo connection, as ``/printers/`` lists them.
DEMO_PRINTERS = [{"id": 1, "name": "Workshop X1C", "model": "X1C", "is_active": True},
                 {"id": 2, "name": "Office A1 mini", "model": "A1 Mini", "is_active": True}]


ADAPTER = BambuddyAdapter()
