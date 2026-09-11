"""Cup: which container images have a newer version waiting.

Measured against Cup 3.5.1 on 11.09.2026. Cup has no sign-in of its own:
``/api/v3/json`` answers anyone who reaches the port, and the adapter sends
nothing but the request.

⚠️ Cup checks at start and on a refresh, and otherwise only when a
``refresh_interval`` is set in its configuration. Without one the answer
stays the one from the day the container started. The cards therefore say
when Cup last looked, and offer a button that makes it look again.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from . import demo as fake
from .base import (
    Action,
    Adapter,
    AdapterError,
    Context,
    Field,
    WidgetData,
    WidgetType,
    ago,
    base_url,
    ring_of,
)

#: Biggest jump first. ``digest`` is Cup's word for the same tag with a new build behind it.
ORDER = {"major": 0, "minor": 1, "patch": 2, "digest": 3}
KIND_LABEL = {"major": "Major", "minor": "Minor", "patch": "Patch", "digest": "New build"}

CHECK_AGAIN = Action(id="refresh", label="Check now", icon="refresh-cw")
#: After this long without a check the summary says when Cup last looked.
STALE_AFTER = 86400.0


def _age(moment: Any) -> float:
    """Seconds since an ISO time, or 0 when there is none to read."""
    try:
        when = datetime.fromisoformat(str(moment).replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (datetime.now(UTC) - when).total_seconds())


def _kind(result: dict[str, Any]) -> str:
    info = result.get("info") or {}
    if info.get("type") == "version":
        return str(info.get("version_update_type") or "patch")
    return "digest"


class CupAdapter(Adapter):
    kind = "cup"
    label = "Cup"
    category = "hosts"
    description = "Which container images have a newer version waiting."
    icon = "cup"
    beta = False
    docs_url = "https://github.com/sergi0g/cup"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://cup:8000",
              help="Cup started with serve. It has no sign-in of its own, so keep its port inside the network."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="updates", label="Image updates", description="Images with a newer version, the biggest jumps first.",
                   renderer="list", default_size=(3, 3), refresh_seconds=120, metrics=("updates",),
                   options=(Field("limit", "Entries", type="number", default=10),
                            Field("in_use", "Only images a container uses", type="bool", default=False))),
        WidgetType(kind="summary", label="Updates waiting", description="How many images have an update, by how big a step.",
                   renderer="value", default_size=(3, 2), refresh_seconds=120, ring=True, metrics=("updates", "major")),
    )

    async def _answer(self, config: dict[str, Any], ctx: Context, cache: float = 10) -> dict[str, Any]:
        response = await ctx.request("GET", f"{base_url(config)}/api/v3/json", verify=not config.get("insecure"), cache_seconds=cache)
        if response.status_code == 404:
            raise AdapterError("This address answers, but not the way Cup 3 does.", code="not_cup",
                               hint="Cup needs version 3 or newer and has to run with serve.")
        if response.status_code >= 400:
            raise AdapterError(f"Cup answered with HTTP {response.status_code}.", code="http_error")
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("Cup did not answer with JSON.", code="not_cup",
                               hint="The URL probably points at a login page or a reverse proxy.") from error
        if not isinstance(answer, dict) or not isinstance(answer.get("images"), list):
            raise AdapterError("This address answers, but not the way Cup 3 does.", code="not_cup")
        return answer

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        answer = await self._answer(config, ctx, cache=0)
        numbers = answer.get("metrics") or {}
        return (f"Cup answers: {numbers.get('monitored_images', len(answer['images']))} images, "
                f"{numbers.get('updates_available', 0)} with an update.")

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        answer = await self._answer(config, ctx)
        if widget_kind == "summary":
            return self._summary(answer)
        return self._updates(answer, options)

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any],
                     config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        if action_id != "refresh":
            raise AdapterError("Cup has no such action.", code="unknown_action")
        # ⚠️ Cup answers only once it has asked every registry, which took
        # two seconds for sixteen images and grows with the list.
        response = await ctx.request("GET", f"{base_url(config)}/api/v3/refresh", verify=not config.get("insecure"), timeout=120)
        if response.status_code >= 400:
            raise AdapterError(f"Cup answered with HTTP {response.status_code}.", code="http_error")
        return "Cup has checked every image again."

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _summary(answer: dict[str, Any]) -> WidgetData:
        numbers = answer.get("metrics") or {}

        def count(key: str) -> int:
            return int(numbers.get(key) or 0)

        updates, unknown = count("updates_available"), count("unknown")
        # ⚠️ Seen on a real board: five chips and a button on a card two columns
        # wide ran off its edge. A chip at zero only where the zero says something.
        steps = (("Major", "major_updates"), ("Minor", "minor_updates"), ("Patch", "patch_updates"), ("New build", "other_updates"), ("Not checked", "unknown"))
        secondary: list[dict[str, Any]] = [{"label": label, "value": count(key)} for label, key in steps if count(key)]
        # ⚠️ On the summary only when it matters: Cup without a refresh interval
        # keeps the answer from the day it started. Measured on a board: with
        # the step chips and the button, a fourth chip ran off the card.
        if _age(answer.get("last_updated")) > STALE_AFTER:
            secondary.append({"label": "Last check", "value": ago(answer.get("last_updated"))})
        return WidgetData(
            status="warn" if updates else "ok",
            primary={"label": "Updates", "value": updates, "unit": f"/ {count('monitored_images')}"},
            secondary=secondary,
            actions=[CHECK_AGAIN],
            meta={"ring": ring_of(("Up to date", count("up_to_date")), ("Updates", updates), ("Not checked", unknown))},
            metrics={"updates": float(updates), "major": float(count("major_updates"))},
        )

    @staticmethod
    def _updates(answer: dict[str, Any], options: dict[str, Any]) -> WidgetData:
        only_used = bool(options.get("in_use"))
        waiting: list[tuple[int, str, dict[str, Any]]] = []
        unchecked: list[dict[str, Any]] = []
        for image in answer["images"]:
            if not isinstance(image, dict) or (only_used and not image.get("in_use")):
                continue
            reference = str(image.get("reference") or "?")
            result = image.get("result") or {}
            if result.get("error"):
                # ⚠️ Measured: an image Cup could not look up comes with
                # ``has_update: null`` and the registry's refusal as text,
                # led by the whole request: "HEAD https://registry…: Not found!".
                reason = str(result["error"]).rsplit(": ", 1)[-1][:160]
                unchecked.append({"title": reference, "subtitle": f"Not checked · {reason}", "status": "unknown"})
                continue
            if not result.get("has_update"):
                continue
            kind = _kind(result)
            info = result.get("info") or {}
            # ⚠️ The word goes in the subtitle, the versions in the value: a
            # list row's value is drawn as it comes, and only the subtitle is
            # translated. "Major" on the right stayed English in German.
            row: dict[str, Any] = {
                "title": reference,
                "subtitle": KIND_LABEL.get(kind, kind),
                "status": "warn" if kind == "major" else "ok",
            }
            if kind != "digest":
                row["value"] = f"{info.get('current_version', '?')} → {info.get('new_version', '?')}"
            if image.get("url"):
                row["url"] = str(image["url"])
            waiting.append((ORDER.get(kind, 9), reference.lower(), row))
        waiting.sort(key=lambda entry: (entry[0], entry[1]))
        limit = int(options.get("limit") or 10)
        items = [row for _order, _name, row in waiting][:limit]
        items += unchecked[: max(0, limit - len(items))]
        # The rows already show how many are waiting; the footer keeps what they do not.
        secondary: list[dict[str, Any]] = []
        if unchecked:
            secondary.append({"label": "Not checked", "value": len(unchecked)})
        checked = ago(answer.get("last_updated"))
        if checked:
            secondary.append({"label": "Last check", "value": checked})
        return WidgetData(
            status="warn" if waiting else "ok",
            items=items,
            secondary=secondary,
            actions=[CHECK_AGAIN],
            meta={"empty": "Every image is up to date."},
            metrics={"updates": float(len(waiting))},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        fresh = fake.flicker("cup-traefik", tick, 0.6)
        images: list[dict[str, Any]] = [
            {"reference": "postgres:17-alpine", "in_use": True, "url": None,
             "result": {"error": None, "has_update": True, "info": {"type": "version", "version_update_type": "major", "current_version": "17", "new_version": "18"}}},
            {"reference": "traefik:v3.4.1", "in_use": True, "url": "https://github.com/traefik/traefik",
             "result": {"error": None, "has_update": not fresh, "info": {"type": "version", "version_update_type": "minor", "current_version": "3.4.1", "new_version": "3.5.0"}}},
            {"reference": "ghcr.io/home-assistant/home-assistant:2026.8.3", "in_use": True, "url": "https://www.home-assistant.io",
             "result": {"error": None, "has_update": True, "info": {"type": "version", "version_update_type": "patch", "current_version": "2026.8.3", "new_version": "2026.8.4"}}},
            {"reference": "jellyfin/jellyfin:latest", "in_use": True, "url": "https://jellyfin.org",
             "result": {"error": None, "has_update": True, "info": {"type": "digest"}}},
        ]
        updates = sum(1 for image in images if image["result"]["has_update"])
        answer = {
            "images": images,
            "last_updated": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "metrics": {"monitored_images": 24, "updates_available": updates, "up_to_date": 24 - updates,
                        "major_updates": 1, "minor_updates": 0 if fresh else 1, "patch_updates": 1, "other_updates": 1, "unknown": 0},
        }
        if widget_kind == "summary":
            return self._summary(answer)
        return self._updates(answer, options)


ADAPTER = CupAdapter()
