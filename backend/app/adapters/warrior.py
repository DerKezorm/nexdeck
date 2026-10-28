"""ArchiveTeam Warrior: what the warrior is doing, which project it works on and how many items it has in hand.

Measured against the warrior container (seesaw-kit 0.10.3, atdr.meo.ws/archiveteam/warrior-dockerfile)
on 27.10.2026, **cut off from the network**: it was started with ``--network none``, because a
connected warrior picks ArchiveTeam's current project at once and downloads other people's
websites on this machine. So the two states a warrior without a tracker can be in were
measured, ``INVALID_SETTINGS`` and ``NO_PROJECT``; a warrior at work was not.

⚠️ The warrior has no JSON API. Its web page (Tornado, port 8001) takes commands as POSTs
(``/api/stop``, ``/api/select-project`` ...) and answers HTML fragments, and ``/api/status``
answers an empty page. What the page shows it gets over a SockJS connection at the root of
the server (``/info``, ``/<server>/<session>/xhr``). That connection works as plain HTTP
long polling: ``POST /000/<session>/xhr`` answers ``o`` for the open, the next one the first
frame, ``a["<json>","<json>"]``, one JSON text per event ``{"event_name", "message"}``. A
second poll waits for the next event, which is the timestamp every second.

On open the warrior sends ``instance_id``, ``project.refresh`` (null without a project),
``warrior.projects_loaded``, ``warrior.status`` and ``warrior.broadcast_message``. The status
is one of ``UNINITIALIZED`` (no contact with the tracker yet), ``INVALID_SETTINGS`` (no
nickname), ``NO_PROJECT``, ``STARTING_PROJECT``, ``RUNNING_PROJECT``, ``STOPPING_PROJECT``,
``SWITCHING_PROJECT``, ``RESTARTING_PROJECT``, ``SHUTTING_DOWN`` and ``REBOOTING``.

Only from the source of seesaw-kit, not measured: with a project selected, ``project.refresh``
carries ``{"project": {"title": ...}, "status": "running"|"stopping", "items": [{"id", "name",
"status": "running"|"completed"|"failed"|"canceled", ...}]}``, and ``bandwidth`` events carry
``{"received", "sent", "receiving", "sending"}`` in bytes and bytes per second.

If the web interface is protected (Settings > HTTP username and password), it is HTTP basic
authentication.
"""

from __future__ import annotations

import json
import secrets
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
    human_rate,
)

#: What each status of the warrior means for a card: its words, its colour.
STATES = {
    "RUNNING_PROJECT": ("Working", "ok"),
    "STARTING_PROJECT": ("Starting", "warn"),
    "STOPPING_PROJECT": ("Stopping", "warn"),
    "SWITCHING_PROJECT": ("Switching project", "warn"),
    "RESTARTING_PROJECT": ("Restarting", "warn"),
    "NO_PROJECT": ("No project", "warn"),
    "INVALID_SETTINGS": ("Needs a nickname", "warn"),
    "UNINITIALIZED": ("Not connected to the tracker", "warn"),
    "SHUTTING_DOWN": ("Shutting down", "warn"),
    "REBOOTING": ("Rebooting", "warn"),
}
#: One poll is quick; the second after the open carries the state, the third may carry the bandwidth.
POLLS = 3


class WarriorAdapter(Adapter):
    kind = "warrior"
    label = "ArchiveTeam Warrior"
    category = "monitoring"
    description = "What the ArchiveTeam Warrior is doing: its state, the project it works on and the items in hand."
    icon = "archiveteam-warrior"
    #: Two idle states measured on 2026-10-27 without a network; a warrior at work is from the source of seesaw-kit.
    beta = True
    docs_url = "https://wiki.archiveteam.org/index.php/ArchiveTeam_Warrior"
    keywords = ("archive team", "seesaw")
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://warrior:8001"),
        Field("username", "User name", help="Only when the warrior's web interface has a user name and password (its Settings)."),
        Field("password", "Password", type="password", secret=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="status", label="Warrior", description="Its state, the project it works on, the items in hand and the traffic.",
                   renderer="value", default_size=(3, 2), refresh_seconds=60, metrics=("items", "receiving", "sending")),
    )

    async def _events(self, config: dict[str, Any], ctx: Context) -> dict[str, Any]:
        """The newest message of each event the warrior sends on open and in the first seconds."""
        session = secrets.token_hex(4)
        user = str(config.get("username") or "").strip()
        auth = (user, str(config.get("password") or "")) if user or config.get("password") else None
        found: dict[str, Any] = {}
        for poll in range(POLLS):
            response = await ctx.request("POST", f"{base_url(config)}/000/{session}/xhr", content=b"", verify=not config.get("insecure"),
                                         auth=auth, auth_errors=False, timeout=6.0)
            if response.status_code == 401:
                raise AuthFailed("The warrior asks for its user name and password.")
            if response.status_code >= 400:
                raise AdapterError(f"The warrior answered with HTTP {response.status_code}.", code="http_error",
                                   hint="Check the URL; it is the address of the warrior's web page, port 8001 by default.")
            text = response.text.strip()
            if poll == 0 and text != "o":
                raise AdapterError("This address answers, but not the way an ArchiveTeam Warrior does.", code="not_a_warrior")
            if text.startswith("a["):
                try:
                    for raw in json.loads(text[1:]):
                        event = json.loads(raw)
                        if isinstance(event, dict) and event.get("event_name"):
                            found[str(event["event_name"])] = event.get("message")
                except (ValueError, TypeError) as error:
                    raise AdapterError("The warrior sent something unreadable.", code="bad_answer") from error
            # The state arrives in the first frame; the bandwidth only once the warrior has two samples.
            if "warrior.status" in found and (poll >= 1 and "bandwidth" in found or poll >= POLLS - 1):
                break
        if "warrior.status" not in found:
            raise AdapterError("The warrior did not say what it is doing.", code="no_status")
        return found

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        events = await self._events(config, ctx)
        words = STATES.get(str((events.get("warrior.status") or {}).get("status")), ("Unknown", "warn"))[0]
        return f"The warrior answers: {words}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        return self._card(await self._events(config, ctx))

    @staticmethod
    def _card(events: dict[str, Any]) -> WidgetData:
        code = str((events.get("warrior.status") or {}).get("status") or "")
        words, status = STATES.get(code, (code.replace("_", " ").capitalize() or "Unknown", "warn"))
        refresh = events.get("project.refresh") if isinstance(events.get("project.refresh"), dict) else None
        project = str(((refresh or {}).get("project") or {}).get("title") or "")
        items = [one for one in (refresh or {}).get("items") or [] if isinstance(one, dict)]
        running = sum(1 for one in items if one.get("status") == "running")
        secondary: list[dict[str, Any]] = []
        if project:
            secondary.append({"label": "Project", "value": project})
        if refresh is not None:
            secondary.append({"label": "Items in hand", "value": running})
        metrics: dict[str, float] = {"items": float(running)} if refresh is not None else {}
        band = events.get("bandwidth") if isinstance(events.get("bandwidth"), dict) else None
        if band:
            secondary.append({"label": "Receiving", "value": human_rate(band.get("receiving"))})
            secondary.append({"label": "Sending", "value": human_rate(band.get("sending"))})
            for key in ("receiving", "sending"):
                if isinstance(band.get(key), int | float):
                    metrics[key] = float(band[key])
        return WidgetData(status=status, primary={"label": "State", "value": words, "unit": ""}, secondary=secondary, metrics=metrics)

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        items = [{"id": number, "name": f"Item {number}", "status": "running"} for number in range(int(fake.walk("wr-items", tick, 1, 2.99)))]
        return self._card({
            "warrior.status": {"status": "RUNNING_PROJECT"},
            "project.refresh": {"project": {"title": "URLs"}, "status": "running", "items": items},
            "bandwidth": {"received": 4_800_000_000, "sent": 900_000_000, "receiving": fake.walk("wr-rx", tick, 20_000, 900_000),
                          "sending": fake.walk("wr-tx", tick, 5_000, 300_000)},
        })


ADAPTER = WarriorAdapter()
