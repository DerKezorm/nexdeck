"""nexbrand: the design sets of an agency's clients, read through its API tokens.

Written against nexbrand 0.2.0 and its ``docs/api.md`` (``routers/v1.py``),
which is built for programs such as this one. Not yet measured against a
running instance, which is why the adapter is in beta.

- The token (``nxb_…``) goes in ``Authorization: Bearer``, never in the
  address. nexbrand refuses any request that carries an ``Origin`` header
  (403 ``origin_refused``), so it is only ever called from nexdeck's server.
- API tokens are off until nexbrand's operator opens them: 401 ``api_off``.
  A wrong, withdrawn or run-out token answers 401 ``token_invalid``; the card
  tells the two apart. 429 ``slow_down`` after 600 requests in a minute.
- A token reads the clients its account may read. A level of ``read`` is
  enough; a ``draft`` token also works, and the cards never use what it adds.
- ``GET /clients`` is one request for all clients; their versions are one
  request each (``/clients/{client}/versions``). The card asks for at most
  ``LOOKED_AT`` clients and keeps every answer for two minutes, so a board
  with this card costs nexbrand a dozen requests every few minutes at most.
- nexbrand tells no time of change: a version has the day it applies from
  (``valid_from``, only once published) and who made it. "Latest" therefore
  means the newest day, with the drafts, which have no day yet, first.

What the cards leave out on purpose: colours, fonts, logos, files and the
notes of a version. A dashboard is often seen by guests, and a client's brand
before its launch is not for them. Fonts with an internal licence never leave
nexbrand through a token in any case.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from urllib.parse import quote

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
)
from .nexapp_base import NexappApi, count_of

#: How many clients the version list looks at. One request each; more than this on one card is a lot to ask.
LOOKED_AT = 12


class NexbrandAdapter(NexappApi, Adapter):
    kind = "nexbrand"
    label = "nexbrand"
    category = "other"
    description = "The design sets of an agency's clients in nexbrand: how many clients and projects there are, and the versions published or waiting as drafts."
    icon = "nexbrand"
    #: Beta until every card has run against a nexbrand in use; measured against a fresh one on 11.10.2026.
    beta = True
    docs_url = "https://github.com/DerKezorm/nexbrand"
    app = "nexbrand"
    own_fields = ("clients",)
    thing = "token"
    where_on = "nexbrand's operator switches API tokens on under Settings > Server > API"
    where_make = "Make a token under My account > Connections in nexbrand."
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://nexbrand:8540"),
        Field("api_key", "API token", type="password", secret=True, required=True,
              help="My account > Connections in nexbrand, after the operator has switched on API tokens. It starts with nxb_; the level Read is enough."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="clients",
            label="nexbrand overview",
            description="How many clients the token reads, how many of them have a published version, and how many projects there are.",
            renderer="value",
            default_size=(3, 2),
            refresh_seconds=300,
            metrics=("clients",),
        ),
        WidgetType(
            kind="versions",
            label="Latest versions",
            description="The versions of the clients' design sets, drafts first, then the newest published ones, each opening its client in nexbrand. Names and days only, no colours.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=300,
            options=(
                Field("client", "Client", type="choices",
                      help="Empty looks at the first twelve clients by name."),
                Field("limit", "Entries", type="number", default=8),
            ),
        ),
    )

    def default_link(self, config: dict[str, Any]) -> str:
        return base_url(config)

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        me = await self._me(config, ctx)
        me = me if isinstance(me, dict) else {}
        return (f"nexbrand {me.get('version') or '?'} answers; the token of {me.get('name') or '?'} "
                f"({me.get('level') or '?'}) reads {count_of(me.get('clients'))} client(s).")

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        clients = await self._get(config, ctx, "/clients", cache=60)
        clients = [one for one in clients if isinstance(one, dict)] if isinstance(clients, list) else []
        if widget_kind != "versions":
            return clients_of(clients)
        wanted = str(options.get("client") or "").strip()
        if wanted:
            clients = [one for one in clients if str(one.get("id")) == wanted]
            if not clients:
                raise AdapterError("nexbrand has no such client, or the token may not read it.", code="no_client",
                                   hint="Pick the client again in the card's settings.")
        looked_at = clients[:LOOKED_AT]
        answers = await asyncio.gather(
            *(self._versions(config, ctx, str(one.get("id") or "")) for one in looked_at), return_exceptions=True)
        # ⚠️ A client whose versions could not be read does not take the card down with it; but if none could be
        # read, the reason is the card's, not an empty list. The first refusal says why.
        failures = [one for one in answers if isinstance(one, BaseException)]
        if failures and len(failures) == len(answers):
            raise failures[0]
        rows = [(client, answer) for client, answer in zip(looked_at, answers, strict=True) if isinstance(answer, list)]
        return versions_of(rows, _today(), base_url(config), _limit(options), len(clients) - len(looked_at))

    async def _versions(self, config: dict[str, Any], ctx: Context, client_id: str) -> list[Any]:
        if not client_id:
            return []
        # The id is nexbrand's own, but it still becomes part of a path: one segment, nothing else.
        answer = await self._get(config, ctx, f"/clients/{quote(client_id, safe='')}/versions", cache=120)
        return answer if isinstance(answer, list) else []

    async def choices(self, field: str, config: dict[str, Any], ctx: Context) -> list[tuple[str, str]]:
        if field != "client":
            return await super().choices(field, config, ctx)
        rows = await self._get(config, ctx, "/clients", cache=60)
        return [(str(one["id"]), str(one.get("name") or "?")) for one in rows
                if isinstance(rows, list) and isinstance(one, dict) and one.get("id")]

    def demo_choices(self, field: str) -> list[tuple[str, str]]:
        return [(f"demo-client-{number}", name) for number, (name, _sector) in enumerate(DEMO_CLIENTS, start=1)] if field == "client" else []

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        today = _today()
        clients = [
            {"id": f"demo-client-{number}", "name": name, "sector": sector, "current_version": "2026" if number != 4 else None,
             "colors": [], "projects": [{"id": f"p{number}", "name": "Website"}] * (number % 3)}
            for number, (name, sector) in enumerate(DEMO_CLIENTS, start=1)
        ]
        if widget_kind != "versions":
            return clients_of(clients)
        rows = []
        for number, client in enumerate(clients, start=1):
            published = {"id": f"v{number}", "label": "2026", "status": "published", "valid_from": f"2026-0{number}-01",
                         "origin": "hand", "author": "robin", "note": ""}
            draft = {"id": f"d{number}", "label": "2027", "status": "draft", "valid_from": None, "origin": "mcp",
                     "author": "sam", "note": ""}
            rows.append((client, [published, draft] if number == 2 and fake.flicker("nexbrand-draft", tick, 0.8) else [published]))
        wanted = str(options.get("client") or "").strip()
        if wanted:
            rows = [(client, versions) for client, versions in rows if client["id"] == wanted]
        return versions_of(rows, today, "http://nexbrand.example.com", _limit(options), 0)


DEMO_CLIENTS = (
    ("Example Bakery", "Bakery"),
    ("Example Outdoor", "Retail"),
    ("Example Clinic", "Health"),
    ("Example Studio", "Design"),
)


def _today() -> str:
    """Today on nexdeck's clock, as nexbrand writes a day."""
    return datetime.now().astimezone().date().isoformat()


def _limit(options: dict[str, Any]) -> int:
    try:
        return max(1, min(50, int(options.get("limit") or 8)))
    except (TypeError, ValueError):
        return 8


def clients_of(clients: list[dict[str, Any]]) -> WidgetData:
    """The number of clients, and of those how many apply a published version and how many projects there are."""
    total = len(clients)
    published = sum(1 for one in clients if one.get("current_version"))
    projects = sum(len(one["projects"]) for one in clients if isinstance(one.get("projects"), list))
    return WidgetData(
        status="ok",
        primary={"label": "Clients", "value": total},
        secondary=[
            {"label": "With a version", "value": published},
            {"label": "Projects", "value": projects},
        ],
        metrics={"clients": float(total)},
    )


def versions_of(rows: list[tuple[dict[str, Any], list[Any]]], today: str, base: str, limit: int, left_out: int) -> WidgetData:
    """The drafts first, then the published versions by the day they apply from, the newest on top.

    A published version whose day lies ahead is "Scheduled": it applies from then, and until then the version before
    it is the client's. Names are shown as they are; the words around them are nexdeck's.
    """
    entries: list[dict[str, Any]] = []
    for client, versions in rows:
        for version in versions:
            if isinstance(version, dict):
                entries.append({"client": client, "version": version, "draft": version.get("status") == "draft",
                                "day": str(version.get("valid_from") or "")})
    # Three stable passes, the last one the strongest: the label, then the later day first, then drafts above all.
    entries.sort(key=lambda entry: str(entry["version"].get("label") or ""))
    entries.sort(key=lambda entry: entry["day"], reverse=True)
    entries.sort(key=lambda entry: not entry["draft"])
    items: list[dict[str, Any]] = []
    for entry in entries[:limit]:
        client, version, draft, day = entry["client"], entry["version"], entry["draft"], entry["day"]
        word = "Draft" if draft else "Scheduled" if day > today else "Published"
        client_id = str(client.get("id") or "")
        items.append({
            "id": str(version.get("id") or f"{client_id}:{version.get('label')}"),
            "title": f"{client.get('name') or '?'} · {version.get('label') or '?'}",
            "subtitle": " · ".join(part for part in (word, day, str(version.get("author") or "")) if part),
            "emphasis": draft,
            "url": f"{base}/c/{client_id}" if client_id else "",
        })
    notice = f"Only the first {LOOKED_AT} of {LOOKED_AT + left_out} clients are looked at." if left_out > 0 else ""
    return WidgetData(status="ok", items=items, meta={"empty": "No version yet.", "notice": notice})


ADAPTER = NexbrandAdapter()
