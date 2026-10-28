"""LubeLogger: the reminders of the vehicles (the next service first), the vehicles with their odometer, and what is due.

Measured on 28.10.2026 against LubeLogger 1.7.4 (ghcr.io/hargata/lubelogger)
with two invented vehicles, an odometer reading each and four reminders (one
past due, one very urgent, two not urgent), once with authentication off, once
with it on (EnableAuth, the user and password as hashes).

⚠️ A default installation has no authentication at all: every route answered
without credentials, ``/api/whoami`` named the user "admin" with root rights.
With EnableAuth the same routes get 401 with ``WWW-Authenticate: Basic`` for
no credentials, for a wrong password and for a made-up ``x-api-key``, and
``/api/version`` too. Basic with the user and password was measured; an API
key (``x-api-key``, made in LubeLogger's settings) is read from the source and
was not, since a key could not be made without the interface.

⚠️ ``/api/vehicle/reminders/all`` answers the reminders of every vehicle the
user may see, each with ``urgency`` (``PastDue``, ``VeryUrgent``, ``Urgent``,
``NotUrgent``), ``dueDays`` and ``dueDistance`` as strings of whole numbers,
and ``metric``, which is the one of ``Date`` and ``Odometer`` that decides.
A reminder set to both said ``Date`` while the date was nearer. ``dueDays`` is
"0" for a reminder by odometer and ``dueDistance`` "0" for one by date: not
"due now", but not applicable. The due date is written in the server's
locale ("11/02/2026"), which is why the card reads the numbers and not the
date. The header ``culture-invariant`` is sent so that numbers stay plain.

⚠️ The reminders name their vehicle by ``vehicleId`` only; ``/api/vehicles``
has the name. ``/api/vehicle/info`` answers one entry per vehicle with the
counts of its reminders by urgency, ``nextReminder`` and
``lastReportedOdometer`` (a number, no unit: the unit is a setting of the
server).
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
)

URL_HINT = "Check the URL; it is the address of LubeLogger itself, without /api."
RANK = {"PastDue": 0, "VeryUrgent": 1, "Urgent": 2, "NotUrgent": 3}
STATUS = {"PastDue": "bad", "VeryUrgent": "warn", "Urgent": "warn", "NotUrgent": "ok"}


def _number(value: Any) -> int:
    try:
        return int(float(str(value)))
    except ValueError:
        return 0


def _name(vehicle: dict[str, Any]) -> str:
    return " ".join(str(part) for part in (vehicle.get("year"), vehicle.get("make"), vehicle.get("model")) if part) or "?"


class LubeLoggerAdapter(Adapter):
    kind = "lubelogger"
    label = "LubeLogger"
    category = "other"
    description = "The next services of your vehicles, the vehicles with their odometer, and how many reminders are due."
    icon = "lubelogger"
    beta = True
    docs_url = "https://docs.lubelogger.com/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://lubelogger:8080"),
        Field("username", "User", help="Empty while LubeLogger runs without authentication, which is how it starts."),
        Field("password", "Password", type="password", secret=True),
        Field("api_key", "API key", type="password", secret=True,
              help="Instead of user and password: an API key made in LubeLogger's settings. Sent as x-api-key."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="summary", label="Vehicles", description="How many reminders are due or past due, with the vehicles and the reminders that are not yet due.",
                   renderer="value", default_size=(3, 2), refresh_seconds=900, metrics=("due",),
                   parts=(("past", "Past due"), ("vehicles", "Vehicles"), ("later", "Not yet due"))),
        WidgetType(kind="reminders", label="Next services", description="The reminders of your vehicles, the most urgent first.",
                   renderer="list", default_size=(3, 3), refresh_seconds=900,
                   options=(Field("limit", "Entries", type="number", default=8),
                            Field("urgent", "Only those due soon or past due", type="bool", default=False))),
        WidgetType(kind="garage", label="Garage", description="Each vehicle with its odometer, yellow or red while a reminder is due.",
                   renderer="list", default_size=(3, 2), refresh_seconds=900),
    )

    # -- talking to LubeLogger -----------------------------------------------

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 30) -> Any:
        headers = {"culture-invariant": "true"}
        auth = None
        if config.get("api_key"):
            headers["x-api-key"] = str(config["api_key"])
        elif config.get("username"):
            auth = (str(config["username"]), str(config.get("password") or ""))
        response = await ctx.request(
            "GET", f"{base_url(config)}/api{path}", headers=headers, auth=auth,
            verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("LubeLogger rejected the credentials.")
        if response.status_code >= 400:
            raise AdapterError(f"LubeLogger answered with HTTP {response.status_code}.", code="http_error", hint=URL_HINT)
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("LubeLogger did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a reverse proxy.") from error

    async def _list(self, config: dict[str, Any], ctx: Context, path: str) -> list[dict[str, Any]]:
        answer = await self._get(config, ctx, path)
        if not isinstance(answer, list):
            raise AdapterError("This address answers, but not the way LubeLogger does.", code="not_lubelogger", hint=URL_HINT)
        return [one for one in answer if isinstance(one, dict)]

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        version = await self._get(config, ctx, "/version", cache=0)
        if not isinstance(version, dict) or "currentVersion" not in version:
            raise AdapterError("This address answers, but not the way LubeLogger does.", code="not_lubelogger", hint=URL_HINT)
        vehicles = await self._list(config, ctx, "/vehicles")
        return f"LubeLogger {version['currentVersion']} answers with {len(vehicles)} vehicles."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        base = base_url(config)
        if widget_kind == "reminders":
            reminders = await self._list(config, ctx, "/vehicle/reminders/all")
            vehicles = await self._list(config, ctx, "/vehicles")
            return self._reminders(reminders, vehicles, options, base)
        info = await self._list(config, ctx, "/vehicle/info")
        if widget_kind == "garage":
            return self._garage(info, base)
        return self._summary(info, base)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _summary(info: list[dict[str, Any]], base: str) -> WidgetData:
        def count(key: str) -> int:
            return sum(_number(one.get(key)) for one in info)

        past, very, urgent, later = (count("pastDueReminderCount"), count("veryUrgentReminderCount"),
                                     count("urgentReminderCount"), count("notUrgentReminderCount"))
        due = past + very + urgent
        return WidgetData(
            status="bad" if past else "warn" if due else "ok",
            primary={"label": "Due", "value": due},
            secondary=[
                {"label": "Past due", "value": past, "part": "past"},
                {"label": "Vehicles", "value": len(info), "part": "vehicles"},
                {"label": "Not yet due", "value": later, "part": "later"},
            ],
            link=base,
            metrics={"due": float(due)},
        )

    @staticmethod
    def _reminders(reminders: list[dict[str, Any]], vehicles: list[dict[str, Any]], options: dict[str, Any], base: str) -> WidgetData:
        names = {str(one.get("id")): _name(one) for one in vehicles}
        only_urgent = options.get("urgent") is True

        def order(reminder: dict[str, Any]) -> tuple[int, int]:
            # ⚠️ "0" days is "not applicable" for a reminder by odometer; see the top of the file.
            by_date = reminder.get("metric") == "Date"
            return (RANK.get(str(reminder.get("urgency")), 9),
                    _number(reminder.get("dueDays")) if by_date else 10**6 + _number(reminder.get("dueDistance")))

        shown = [one for one in sorted(reminders, key=order) if not only_urgent or one.get("urgency") != "NotUrgent"]
        items = []
        for reminder in shown[: max(1, int(options.get("limit") or 8))]:
            by_date = reminder.get("metric") == "Date"
            urgency = str(reminder.get("urgency") or "")
            items.append({
                "title": str(reminder.get("description") or "?"),
                "subtitle": names.get(str(reminder.get("vehicleId")), ""),
                "value": f"{_number(reminder.get('dueDays'))} d" if by_date else str(_number(reminder.get("dueDistance"))),
                "status": STATUS.get(urgency, "ok"),
            })
        worst = min((RANK.get(str(one.get("urgency")), 9) for one in reminders), default=9)
        return WidgetData(
            status="bad" if worst == 0 else "warn" if worst <= 2 else "ok",
            items=items,
            link=base,
            meta={"empty": "No reminders are due." if only_urgent else "No reminders yet."},
        )

    @staticmethod
    def _garage(info: list[dict[str, Any]], base: str) -> WidgetData:
        items = []
        for one in info:
            vehicle = one.get("vehicleData") if isinstance(one.get("vehicleData"), dict) else {}
            if _number(one.get("pastDueReminderCount")):
                status = "bad"
            elif _number(one.get("veryUrgentReminderCount")) or _number(one.get("urgentReminderCount")):
                status = "warn"
            else:
                status = "ok"
            items.append({
                "title": _name(vehicle),
                "subtitle": str(vehicle.get("licensePlate") or ""),
                "value": str(_number(one.get("lastReportedOdometer"))),
                "status": status,
            })
        return WidgetData(status="ok", items=items, link=base, meta={"empty": "No vehicles yet."})

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        base = "https://lubelogger.example.com"
        vehicles = [{"id": 1, "year": 2019, "make": "Example", "model": "Wagon", "licensePlate": "EX-123"},
                    {"id": 2, "year": 2012, "make": "Example", "model": "Hatch", "licensePlate": "EX-456"}]
        reminders = [
            {"vehicleId": "1", "description": "Oil change", "urgency": "VeryUrgent", "metric": "Date", "dueDays": "4", "dueDistance": "500"},
            {"vehicleId": "1", "description": "Tyre swap", "urgency": "PastDue", "metric": "Date", "dueDays": "-3", "dueDistance": "0"},
            {"vehicleId": "2", "description": "Timing belt", "urgency": "NotUrgent", "metric": "Odometer", "dueDays": "0", "dueDistance": "9000"},
            {"vehicleId": "2", "description": "Inspection", "urgency": "NotUrgent", "metric": "Date", "dueDays": "199", "dueDistance": "0"},
        ]
        if widget_kind == "reminders":
            return self._reminders(reminders, vehicles, options, base)
        miles = fake.counter("lubelogger-odometer", tick, 84500, 0.05)
        info = [
            {"vehicleData": vehicles[0], "pastDueReminderCount": 1, "veryUrgentReminderCount": 1, "urgentReminderCount": 0,
             "notUrgentReminderCount": 0, "lastReportedOdometer": miles},
            {"vehicleData": vehicles[1], "pastDueReminderCount": 0, "veryUrgentReminderCount": 0, "urgentReminderCount": 0,
             "notUrgentReminderCount": 2, "lastReportedOdometer": 131000},
        ]
        return self._garage(info, base) if widget_kind == "garage" else self._summary(info, base)


ADAPTER = LubeLoggerAdapter()
