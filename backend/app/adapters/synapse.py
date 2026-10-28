"""Synapse (Matrix): users, rooms and reports of your homeserver, through its Admin API.

Measured on 27.10.2026 against matrixdotorg/synapse 1.164.0 (SQLite, one
server admin, two users, two rooms, one reported message, one deactivated user).

- ``Authorization: Bearer <access token>`` of a user who is a **server admin**.
  Anybody else is **403** ``M_FORBIDDEN`` ("You are not a server admin"), no
  token **401** ``M_MISSING_TOKEN``, a wrong one **401** ``M_UNKNOWN_TOKEN``.
- ⚠️ ``/_synapse/admin/v1/server_version`` answers **without any token**, so
  it proves nothing about the sign-in; the test asks for the user list.
- ``/_synapse/admin/v2/users?limit=1&guests=false``: ``total`` counts the
  users that are not deactivated; with ``deactivated=true`` it counts them
  all, so the deactivated ones are the difference. Two small requests, no
  list of names.
- ``/_synapse/admin/v1/rooms``: ``total_rooms`` and ``rooms`` with ``name``,
  ``canonical_alias``, ``joined_members``, ``join_rules`` and ``encryption``.
  ⚠️ ``order_by=joined_members`` with ``dir=f`` (the default) puts the biggest
  first and ``dir=b`` the smallest: measured with rooms of 3 and 1 members,
  the opposite of what "backwards" suggests. The same letters on the report
  list are left at their default, which Synapse's documentation says is the
  newest first; that was seen with one report only, so the card sorts the
  newest to the top itself.
- ``/_synapse/admin/v1/event_reports``: ``total`` and ``event_reports`` with
  ``reason``, ``user_id`` (who reported), ``sender``, the room's ``name`` and
  ``received_ts`` in milliseconds. A report stays until an admin deletes it,
  so the count is of the reports not dealt with. The text of the reported
  message is not in this list and not read.
- ``/_synapse/admin/v1/federation/destinations``: ``destinations`` and
  ``total``. A destination with a ``failure_ts`` cannot be reached. Measured
  only with none (the server had not spoken to any); the fields are from
  Synapse's documentation.
"""

from __future__ import annotations

import time
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
    ago,
    base_url,
)

ADMIN = "/_synapse/admin"
#: How many destinations are read to count the ones that fail.
DESTINATIONS = 200


def _name(room: dict[str, Any]) -> str:
    return str(room.get("name") or room.get("canonical_alias") or "Unnamed room")


class SynapseAdapter(Adapter):
    kind = "synapse"
    label = "Synapse"
    category = "hosts"
    description = "Users, rooms, reported messages and unreachable servers of your Matrix homeserver, through Synapse's Admin API."
    icon = "synapse"
    docs_url = "https://element-hq.github.io/synapse/latest/usage/administration/admin_api/"
    keywords = ("matrix", "element")
    #: Measured against Synapse 1.164.0 with two rooms and one report; federation not seen with a failing server.
    beta = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://matrix.example.com",
              help="Where Synapse answers the client API, with its path if it is served under one. The Admin API has to be reachable there: a reverse proxy often hides /_synapse/admin."),
        Field("token", "Access token of a server admin", type="password", secret=True, required=True,
              help="Of a user who is a server admin: in Element under All settings > Help & About > Advanced > Access Token. Logging that session out ends the token, so a session of its own is best."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="overview",
            label="Synapse overview",
            description="Users, rooms, deactivated users, reported messages waiting for a moderator and servers that cannot be reached.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=300,
            metrics=("users", "rooms", "reports"),
        ),
        WidgetType(
            kind="reports",
            label="Reported messages",
            description="The newest reports with the room, the reason and who reported, until an admin deletes them.",
            renderer="list",
            default_size=(4, 3),
            min_size=(3, 2),
            refresh_seconds=300,
            metrics=("reports",),
            options=(Field("limit", "Entries", type="number", default=8),),
        ),
        WidgetType(
            kind="rooms",
            label="Largest rooms",
            description="The rooms with the most members, and whether they are public or encrypted.",
            renderer="list",
            default_size=(4, 3),
            min_size=(3, 2),
            refresh_seconds=900,
            options=(Field("limit", "Entries", type="number", default=8),),
        ),
    )

    # -- asking Synapse -------------------------------------------------------------

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 30) -> dict[str, Any]:
        response = await ctx.request(
            "GET", f"{base_url(config)}{ADMIN}{path}", params=params, headers={"Authorization": f"Bearer {str(config.get('token') or '').strip()}"},
            verify=not config.get("insecure"), cache_seconds=cache, timeout=25, auth_errors=False)
        if response.status_code in (401, 403):
            forbidden = response.status_code == 403
            failure = AuthFailed("This user is not a server admin." if forbidden else "Synapse rejected the access token.")
            failure.hint = ("Make an admin of the user (the column admin in the users table, or the Admin API) and use the token of that user."
                            if forbidden else "A token ends when its session is logged out; make a new one and paste it here.")
            raise failure
        if response.status_code == 429:
            raise AdapterError("Synapse is limiting the requests of this token.", code="rate_limited", hint="Give the cards a longer interval.")
        if response.status_code == 404:
            raise AdapterError("This address answers, but does not offer the Admin API.", code="no_admin_api",
                               hint="A reverse proxy often keeps /_synapse/admin from the outside; point nexdeck at Synapse's own port, 8008.")
        if response.status_code >= 400:
            raise AdapterError(f"Synapse answered with HTTP {response.status_code}.", code="http_error")
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("Synapse did not answer with JSON.", code="not_json", hint="The URL probably points at a web page or a reverse proxy.") from error
        if not isinstance(answer, dict):
            raise AdapterError("This address answers, but not the way Synapse does.", code="not_synapse")
        return answer

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        users = await self._get(config, ctx, "/v2/users", {"limit": 1, "guests": "false"}, cache=0)
        if "total" not in users:
            raise AdapterError("This address answers, but not the way Synapse does.", code="not_synapse")
        version = (await self._get(config, ctx, "/v1/server_version", cache=0)).get("server_version")
        return f"Synapse {version} accepts the token, {users['total']} users." if version else f"Synapse accepts the token, {users['total']} users."

    # -- the cards ---------------------------------------------------------------------

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        link = base_url(config)
        limit = max(1, min(50, int(options.get("limit") or 8)))
        if widget_kind == "reports":
            return self.reports_card(await self._get(config, ctx, "/v1/event_reports", {"limit": limit}), link)
        if widget_kind == "rooms":
            return self.rooms_card(await self._get(config, ctx, "/v1/rooms", {"limit": limit, "order_by": "joined_members", "dir": "f"}), link)
        active = await self._get(config, ctx, "/v2/users", {"limit": 1, "guests": "false"})
        everyone = await self._get(config, ctx, "/v2/users", {"limit": 1, "guests": "false", "deactivated": "true"})
        rooms = await self._get(config, ctx, "/v1/rooms", {"limit": 1})
        reports = await self._get(config, ctx, "/v1/event_reports", {"limit": 1})
        try:
            federation = await self._get(config, ctx, "/v1/federation/destinations", {"limit": DESTINATIONS})
        except AdapterError as error:
            # A Synapse before 1.64 has no such list; the other figures stand.
            if error.code != "no_admin_api":
                raise
            federation = {}
        return self.overview_card(active, everyone, rooms, reports, federation, link)

    @staticmethod
    def overview_card(active: dict[str, Any], everyone: dict[str, Any], rooms: dict[str, Any], reports: dict[str, Any],
                      federation: dict[str, Any], link: str | None = None) -> WidgetData:
        users, total = int(active.get("total") or 0), int(everyone.get("total") or 0)
        waiting = int(reports.get("total") or 0)
        destinations = [one for one in federation.get("destinations") or [] if isinstance(one, dict)]
        failing = sum(1 for one in destinations if one.get("failure_ts"))
        more = int(federation.get("total") or 0) > len(destinations)
        secondary = [{"label": "Rooms", "value": int(rooms.get("total_rooms") or 0)}, {"label": "Reports", "value": waiting}]
        if total > users:
            secondary.insert(1, {"label": "Deactivated", "value": total - users})
        if failing:
            secondary.append({"label": "Servers unreachable", "value": f"{failing}+" if more else failing})
        return WidgetData(
            status="warn" if waiting or failing else "ok",
            primary={"label": "Users", "value": users},
            secondary=secondary,
            metrics={"users": float(users), "rooms": float(rooms.get("total_rooms") or 0), "reports": float(waiting)},
            link=link,
        )

    @staticmethod
    def reports_card(answer: dict[str, Any], link: str | None = None) -> WidgetData:
        reports = sorted((one for one in answer.get("event_reports") or [] if isinstance(one, dict)), key=lambda one: -(one.get("received_ts") or 0))
        total = int(answer.get("total") or len(reports))
        items = []
        for report in reports:
            reason = " ".join(str(report.get("reason") or "").split())[:100]
            items.append({
                "title": _name(report),
                "subtitle": " · ".join(part for part in (reason or "No reason given", f"by {report['user_id']}" if report.get("user_id") else "") if part),
                "status": "warn",
                "value": ago((report.get("received_ts") or 0) / 1000) if report.get("received_ts") else "",
            })
        return WidgetData(
            status="warn" if total else "ok",
            items=items,
            secondary=[{"label": "Reports", "value": total}],
            metrics={"reports": float(total)},
            link=link,
            meta={"empty": "No message is reported."},
        )

    @staticmethod
    def rooms_card(answer: dict[str, Any], link: str | None = None) -> WidgetData:
        rooms = sorted((one for one in answer.get("rooms") or [] if isinstance(one, dict)), key=lambda one: -int(one.get("joined_members") or 0))
        biggest = max((int(one.get("joined_members") or 0) for one in rooms), default=0)
        items = []
        for room in rooms:
            members = int(room.get("joined_members") or 0)
            items.append({
                "title": _name(room),
                "subtitle": " · ".join(part for part in ("Public" if room.get("join_rules") == "public" else "Private", "Encrypted" if room.get("encryption") else "") if part),
                "value": f"{members}",
                "progress": round(100 * members / biggest, 1) if biggest else 0.0,
            })
        return WidgetData(
            status="ok",
            items=items,
            secondary=[{"label": "Rooms", "value": int(answer.get("total_rooms") or len(rooms))}],
            link=link,
            meta={"empty": "There is no room yet."},
        )

    # -- demo -----------------------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = (time.time() - tick % 60) * 1000
        reports = int(fake.walk("synapse-reports", tick, 0, 3))
        if widget_kind == "reports":
            rows = [{"name": "General", "reason": "Spam", "user_id": "@alice:example.com", "received_ts": now - 3_600_000},
                    {"name": "Off topic", "reason": "", "user_id": "@bob:example.com", "received_ts": now - 86_400_000}]
            return self.reports_card({"event_reports": rows[: max(1, reports)], "total": max(1, reports)})
        if widget_kind == "rooms":
            return self.rooms_card({"total_rooms": 41, "rooms": [
                {"name": "General", "joined_members": 48, "join_rules": "public"},
                {"name": "Family", "joined_members": 7, "join_rules": "invite", "encryption": "m.megolm.v1.aes-sha2"},
                {"name": "Homelab", "joined_members": 4, "join_rules": "invite"}]})
        failing = [{"destination": "chat.example.net", "failure_ts": now}] if fake.flicker("synapse-fed", tick, 0.3) else []
        return self.overview_card({"total": 12}, {"total": 13}, {"total_rooms": 41}, {"total": reports},
                                  {"destinations": [{"destination": "matrix.example.org"}, *failing], "total": 2})


ADAPTER = SynapseAdapter()
