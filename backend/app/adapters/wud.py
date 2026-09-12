"""What's Up Docker: which containers run an image with a newer version, with the update where WUD may run one.

Measured against WUD 9.0.0 on 11.09.2026, released that day, with five test
containers: one on nginx 1.25-alpine for which WUD found 1.31-alpine, one held
on its tag, one on a mutable tag with an older build behind it, one whose image
no registry has, and a Docker trigger that only the first of them named.
Nothing else on the host was watched: ``WATCHBYDEFAULT=false``, and
``wud.watch=true`` on the test containers alone.

⚠️ WUD 9 lets nobody in without credentials. A personal API token from My
Profile goes as ``Authorization: Bearer wud_...``. No header, a made-up token
and a wrong password all got 401. ``/api/app`` answers without anything, so it
proves nothing about them.

⚠️ The token, never the account. Basic authentication with the administrator
worked, but its answer set a ``connect.sid`` session cookie, and the same
client, which keeps cookies as httpx does, then got in with no header, with a
made-up token and with a wrong password, and a read-only token could run a
check. A token answer sets no cookie.

⚠️ A token carries scopes. One with only ``read`` reads both cards and got 403
"API token missing write scope" on the update and on the check.

⚠️ An update is a trigger run, ``POST /api/containers/{id}/triggers/docker/{name}``.
It answered 200 ``{}`` after 8 seconds, once the new image was pulled and the
container recreated. The container comes back under a new id: for a few
seconds it is ``removing`` or missing from the list, and the old id gets 404,
or, pressed again straight away, 500 with Docker's "no such container".
The same call on a container without an update crashed with 500 "Cannot read
properties of undefined", so the button is offered only on a row that has an
update and a docker or docker-compose trigger WUD lists for that container.

⚠️ A container WUD could not look up carries ``error.message`` next to
``updateAvailable: false``; an image no registry has got "Request failed with
status code 401". The error is read before the flag.

⚠️ ``wud.watch.digest`` did nothing on a tag that reads as a version
(``1-alpine``). On ``mainline-alpine`` it reported ``kind: digest`` with both
digests as the values, which say nothing on a card.

The API keeps no time of the last check, so no card shows one.
"""

from __future__ import annotations

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
    base_url,
    path_segment,
    ring_of,
)

#: The trigger types that replace a container rather than send a message about it.
UPDATE_TRIGGERS = ("docker", "dockercompose")
#: Biggest step first; a tag WUD cannot compare and a new build of the same tag last.
ORDER = {"major": 0, "minor": 1, "patch": 2, "prerelease": 3}
STEP_LABEL = {"major": "Major", "minor": "Minor", "patch": "Patch", "prerelease": "Pre-release"}

CHECK_NOW = Action(id="check", label="Check now", icon="refresh-cw")


def _kind(container: dict[str, Any]) -> dict[str, Any]:
    kind = container.get("updateKind")
    return kind if isinstance(kind, dict) else {}


def _step(container: dict[str, Any]) -> tuple[int, str]:
    """Where an update sorts, and the word for it."""
    kind = _kind(container)
    if kind.get("kind") == "digest":
        return 5, "New build"
    diff = str(kind.get("semverDiff") or "")
    return ORDER.get(diff, 4), STEP_LABEL.get(diff, "New tag")


def _failed(container: dict[str, Any]) -> str | None:
    """Why WUD could not check a container, or ``None`` when it could."""
    error = container.get("error")
    if not isinstance(error, dict):
        return None
    return " ".join(str(error.get("message") or "").split())


def _name(container: dict[str, Any]) -> str:
    return str(container.get("displayName") or container.get("name") or "?")


def _image(container: dict[str, Any]) -> str:
    image = container.get("image") if isinstance(container.get("image"), dict) else {}
    return str(image.get("name") or "").removeprefix("library/")


def _pending(containers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Containers with an update, biggest step first."""
    waiting = [one for one in containers if _failed(one) is None and one.get("updateAvailable")]
    return sorted(waiting, key=lambda one: (_step(one)[0], _name(one).lower()))


class WudAdapter(Adapter):
    kind = "wud"
    label = "What's Up Docker"
    category = "hosts"
    description = "Which containers run an image with a newer version, with an update button where WUD may run one."
    icon = "whats-up-docker"
    #: Confirmed against a live instance on 2026-09-11.
    beta = False
    docs_url = "https://github.com/getwud/wud"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://wud:3000"),
        Field("token", "API token", type="password", secret=True, required=True,
              help="My Profile > API tokens. Read is enough for the cards; the update and check buttons need write."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="updates", label="Container updates",
                   description="Containers with a newer image, the biggest step first, then the ones WUD could not check.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300, metrics=("updates",),
                   options=(Field("limit", "Entries", type="number", default=10),)),
        WidgetType(kind="summary", label="Updates waiting",
                   description="How many watched containers have an update, and how many WUD could not check.",
                   renderer="value", default_size=(3, 2), refresh_seconds=300, ring=True, metrics=("updates",)),
    )

    async def _call(self, method: str, config: dict[str, Any], ctx: Context, path: str, *,
                    cache: float = 0, timeout: float = 15.0) -> Any:
        response = await ctx.request(
            method, f"{base_url(config)}/api{path}", headers={"Authorization": f"Bearer {str(config.get('token') or '').strip()}"},
            verify=not config.get("insecure"), cache_seconds=cache, timeout=timeout, auth_errors=False,
        )
        if response.status_code == 401:
            raise AuthFailed("WUD rejected the API token.")
        return response

    async def _json(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 10) -> Any:
        response = await self._call("GET", config, ctx, path, cache=cache)
        if response.status_code == 403:
            raise AuthFailed("WUD refused the API token. It needs the read scope.")
        if response.status_code >= 400:
            raise AdapterError(f"WUD answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of WUD itself, without /api.")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("WUD did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a reverse proxy.") from error

    async def _containers(self, config: dict[str, Any], ctx: Context, cache: float = 10) -> list[dict[str, Any]]:
        answer = await self._json(config, ctx, "/containers", cache=cache)
        if not isinstance(answer, list):
            raise AdapterError("This address answers, but not the way WUD does.", code="not_wud")
        return [one for one in answer if isinstance(one, dict)]

    async def _update_trigger(self, config: dict[str, Any], ctx: Context, container: dict[str, Any]) -> tuple[str, str] | None:
        """The first trigger WUD lists for this container that updates it, if any."""
        try:
            identifier = path_segment(container.get("id"), "The container")
        except AdapterError:
            return None
        response = await self._call("GET", config, ctx, f"/containers/{identifier}/triggers", cache=60)
        # A container being recreated is briefly unknown; that row simply has no button this time.
        if response.status_code != 200:
            return None
        try:
            triggers = response.json()
        except ValueError:
            return None
        for trigger in triggers if isinstance(triggers, list) else []:
            if isinstance(trigger, dict) and str(trigger.get("type") or "") in UPDATE_TRIGGERS and trigger.get("name"):
                return str(trigger["type"]), str(trigger["name"])
        return None

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        app = await self._json(config, ctx, "/app", cache=0)
        containers = await self._containers(config, ctx, cache=0)
        version = app.get("version") if isinstance(app, dict) else None
        return f"What's Up Docker {version or '?'} answers with {len(containers)} watched containers."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        containers = await self._containers(config, ctx)
        if widget_kind == "summary":
            return self._summary(containers)
        limit = max(1, int(options.get("limit") or 10))
        triggers: dict[str, tuple[str, str]] = {}
        for container in _pending(containers)[:limit]:
            trigger = await self._update_trigger(config, ctx, container)
            if trigger:
                triggers[str(container.get("id") or "")] = trigger
        return self._updates(containers, triggers, limit)

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any],
                     config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        if action_id == "check":
            response = await self._call("POST", config, ctx, "/containers/watch", timeout=120)
            self._refused(response)
            ctx.forget_answers()
            return "WUD has checked every watched container again."
        if action_id != "update":
            raise AdapterError("WUD has no such action.", code="no_such_action")
        container = path_segment(params.get("id"), "The container")
        trigger_type = path_segment(params.get("type"), "The trigger")
        trigger_name = path_segment(params.get("name"), "The trigger")
        if trigger_type not in UPDATE_TRIGGERS:
            raise AdapterError("That trigger does not update containers.", code="bad_param")
        # ⚠️ WUD answers once the new image is pulled and the container recreated:
        # 8 seconds for nginx, and a large image takes as long as its download.
        response = await self._call("POST", config, ctx, f"/containers/{container}/triggers/{trigger_type}/{trigger_name}", timeout=300)
        if response.status_code == 404:
            raise AdapterError("WUD no longer knows this container.", code="action_failed",
                               hint="An update gives the container a new id; the card shows it after its next refresh.")
        self._refused(response)
        ctx.forget_answers()
        return "WUD has updated the container."

    @staticmethod
    def _refused(response: Any) -> None:
        if response.status_code == 403:
            raise AuthFailed("WUD refused. This button needs an API token with the write scope.")
        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                body = None
            message = str(body.get("message") or body.get("error") or "") if isinstance(body, dict) else ""
            raise AdapterError(f"WUD could not do it: {message}" if message else f"WUD answered with HTTP {response.status_code}.",
                               code="action_failed")

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _updates(containers: list[dict[str, Any]], triggers: dict[str, tuple[str, str]], limit: int) -> WidgetData:
        items: list[dict[str, Any]] = []
        pending = _pending(containers)
        for container in pending:
            order, word = _step(container)
            kind = _kind(container)
            row: dict[str, Any] = {
                "title": _name(container),
                # ⚠️ The word goes in the subtitle, the versions in the value:
                # only the subtitle is translated.
                "subtitle": " · ".join(part for part in (word, _image(container)) if part),
                "status": "warn" if order == 0 else "ok",
            }
            if kind.get("kind") != "digest" and kind.get("localValue") and kind.get("remoteValue"):
                row["value"] = f"{kind['localValue']} → {kind['remoteValue']}"
            trigger = triggers.get(str(container.get("id") or ""))
            if trigger:
                row["actions"] = [Action(id="update", label="Update", icon="download", confirm=True,
                                         params={"id": str(container.get("id") or ""), "type": trigger[0], "name": trigger[1]})]
            items.append(row)
        unchecked = [one for one in containers if _failed(one) is not None]
        for container in sorted(unchecked, key=lambda one: _name(one).lower()):
            items.append({
                "title": _name(container),
                "subtitle": " · ".join(part for part in ("Not checked", (_failed(container) or "")[:160]) if part),
                "status": "unknown",
            })
        return WidgetData(
            status="warn" if pending else "ok",
            items=items[:limit],
            secondary=[{"label": "Not checked", "value": len(unchecked)}] if unchecked else [],
            meta={"empty": "Every watched container is up to date."},
            metrics={"updates": float(len(pending))},
        )

    @staticmethod
    def _summary(containers: list[dict[str, Any]]) -> WidgetData:
        pending = _pending(containers)
        failed = sum(1 for one in containers if _failed(one) is not None)
        major = sum(1 for one in pending if _step(one)[0] == 0)
        secondary: list[dict[str, Any]] = []
        if major:
            secondary.append({"label": "Major", "value": major})
        if failed:
            secondary.append({"label": "Not checked", "value": failed})
        return WidgetData(
            status="warn" if pending else "ok" if containers else "unknown",
            primary={"label": "Updates", "value": len(pending), "unit": f"/ {len(containers)}"},
            secondary=secondary,
            actions=[CHECK_NOW],
            meta={"ring": ring_of(("Up to date", len(containers) - len(pending) - failed), ("Updates", len(pending)), ("Not checked", failed))},
            metrics={"updates": float(len(pending))},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        fresh = fake.flicker("wud-traefik", tick, 0.6)

        def tag(identifier: str, name: str, image: str, local: str, remote: str, diff: str, update: bool = True) -> dict[str, Any]:
            return {"id": identifier, "name": name, "image": {"name": image}, "updateAvailable": update,
                    "updateKind": {"kind": "tag", "localValue": local, "remoteValue": remote, "semverDiff": diff}}

        containers: list[dict[str, Any]] = [
            tag("a1c3", "postgres", "library/postgres", "16-alpine", "17-alpine", "major"),
            tag("b7e2", "traefik", "library/traefik", "v3.4.1", "v3.5.0", "minor", update=not fresh),
            tag("c5d8", "paperless", "paperless-ngx/paperless-ngx", "2.17.1", "2.17.2", "patch"),
            {"id": "d9f4", "name": "homeassistant", "image": {"name": "home-assistant/home-assistant"}, "updateAvailable": True,
             "updateKind": {"kind": "digest", "semverDiff": None}},
            {"id": "e2b6", "name": "internal-app", "image": {"name": "example/internal-app"}, "updateAvailable": False,
             "error": {"message": "Request failed with status code 401"}},
            *({"id": f"f{number}", "name": f"service-{number}", "image": {"name": "library/nginx"}, "updateAvailable": False}
              for number in range(9)),
        ]
        if widget_kind == "summary":
            return self._summary(containers)
        triggers = {"a1c3": ("docker", "local"), "b7e2": ("docker", "local"), "c5d8": ("docker", "local"), "d9f4": ("dockercompose", "stacks")}
        return self._updates(containers, triggers, max(1, int(options.get("limit") or 10)))


ADAPTER = WudAdapter()
