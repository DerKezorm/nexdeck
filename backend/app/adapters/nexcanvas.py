"""nexcanvas: the whiteboards of the nexapps family, read through its API tokens.

Written against nexcanvas 0.4.1 and its ``docs/api.md`` (``routers/v1.py``),
which is built for this card. Not yet measured against a running instance,
which is why the adapter is in beta.

- The token (``nxa_…``) goes in ``Authorization: Bearer``, never in the
  address. nexcanvas refuses any request that carries an ``Origin`` header
  (403 ``origin_refused``), so it is only ever called from nexdeck's server.
- API tokens are off until nexcanvas's operator opens them: 401 ``api_off``,
  even for a token made before. A wrong, withdrawn or run-out token answers
  401 ``token_invalid``; the card tells the two apart. 429 ``slow_down`` after
  600 requests in a minute.
- A token reads what its account may read. A board it may not read answers
  404 like one that does not exist.
- The picture of a board is an SVG that needs the token, so the browser never
  asks for it: nexdeck fetches it (``image_source``) and hands it on. The
  answer carries the title of the board and nothing else of its words; the
  image route checks it for script all the same.
- ``/dashboard`` counts "today" on nexcanvas's clock, not on nexdeck's.

What the cards leave out on purpose: the words on a board (the picture shows
them as plain boxes), who may open it, and everything that would change it:
nexcanvas's API only reads.
"""

from __future__ import annotations

import re
import time
from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    Context,
    Field,
    MediaSource,
    WidgetData,
    WidgetType,
    base_url,
)
from .nexapp_base import NexappApi, count_of, epoch_of

#: nexcanvas's board ids; the same rule it applies to its own paths.
BOARD_ID = re.compile(r"^[A-Za-z0-9_-]{6,40}$")
#: ``/board/<id>/<look>/<width>/<version>`` is the only image path this adapter serves. The version is the second
#: the board last changed, so a changed board has a new address and no browser keeps the old picture; ``live`` is
#: the card that wants a fresh picture every time.
PICTURE_PATH = re.compile(r"^/board/([A-Za-z0-9_-]{6,40})/(dark|light)/(\d{3,4})/(live|\d{1,12})$")
LOOKS = (("dark", "Dark"), ("light", "Light"))
#: How wide the pictures are drawn: a thumbnail beside a row, and a card of its own.
THUMBNAIL = 320
LARGE = 1200


class NexcanvasAdapter(NexappApi, Adapter):
    kind = "nexcanvas"
    label = "nexcanvas"
    category = "other"
    description = "The whiteboards of nexcanvas: the boards changed last with a small picture each, and one board large and alive."
    icon = "nexcanvas"
    #: Beta until every card has run against a nexcanvas in use; measured against a fresh one on 11.10.2026.
    beta = True
    docs_url = "https://www.nexcanvas.de"
    app = "nexcanvas"
    own_fields = ("spaces",)
    thing = "token"
    where_on = "nexcanvas's operator switches API tokens on under Settings > Server > API"
    where_make = "Make a token under My account > Connections in nexcanvas."
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://nexcanvas:8500"),
        Field("api_key", "API token", type="password", secret=True, required=True,
              help="My account > Connections in nexcanvas, after the operator has switched on API tokens. It starts with nxa_ and only reads."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="boards",
            label="Boards",
            description="The boards changed last, newest first, each with a small picture and opening in nexcanvas, and how many changed today and this week.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=120,
            options=(Field("look", "Pictures", type="select", default="dark", options=LOOKS),),
        ),
        WidgetType(
            kind="board",
            label="Board",
            description="One board as a picture, large and fetched again every few seconds. Clicking it opens the board in nexcanvas.",
            renderer="camera",
            default_size=(4, 3),
            min_size=(2, 2),
            refresh_seconds=300,
            options=(
                Field("board", "Board", type="choices", required=True),
                Field("look", "Look", type="select", default="dark", options=LOOKS),
                Field("interval", "Picture every (seconds)", type="number", default=30),
            ),
        ),
    )

    def default_link(self, config: dict[str, Any]) -> str:
        return base_url(config)

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        me = await self._me(config, ctx)
        me = me if isinstance(me, dict) else {}
        spaces = me.get("spaces")
        return f"nexcanvas {me.get('version') or '?'} answers; the token of {me.get('name') or '?'} reads {len(spaces) if isinstance(spaces, list) else 0} space(s)."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        look = _look(options)
        if widget_kind == "board":
            board_id = _board_id(options)
            board = await self._get(config, ctx, f"/boards/{board_id}", missing=(
                "nexcanvas has no such board, or the token may not read it.", "no_board",
                "Pick the board again in the card's settings."))
            return board_of(board if isinstance(board, dict) else {}, look, _interval(options))
        numbers = self._expect(await self._get(config, ctx, "/dashboard"), "boards", "recent", "changed_today", "changed_week")
        return boards_of(numbers if isinstance(numbers, dict) else {}, look)

    async def choices(self, field: str, config: dict[str, Any], ctx: Context) -> list[tuple[str, str]]:
        if field != "board":
            return await super().choices(field, config, ctx)
        rows = await self._get(config, ctx, "/boards", {"order": "title", "limit": 200}, cache=60)
        return board_choices(rows if isinstance(rows, list) else [])

    def demo_choices(self, field: str) -> list[tuple[str, str]]:
        return [(f"demo-board-{number}", f"{title} · {space}") for number, (title, space) in enumerate(DEMO_BOARDS, start=1)] if field == "board" else []

    async def image_source(self, config: dict[str, Any], path: str, ctx: Context) -> MediaSource:
        """The picture of one board, fetched with the token.

        ⚠️ Only ``/board/<id>/<look>/<width>/<version>``. The default would fetch any path under nexcanvas's address
        with the card's token. A picture that comes with a version is kept for an hour, since a changed board has a
        new version and with it a new address; the live card's is never kept.
        """
        found = PICTURE_PATH.match(path)
        if not found:
            raise AdapterError("nexcanvas pictures are /board/<id>/<look>/<width>/<version>.", code="bad_path")
        board_id, look, width, version = found.groups()
        if not 120 <= int(width) <= 1600:
            raise AdapterError("nexcanvas draws pictures from 120 to 1600 pixels wide.", code="bad_path")
        return MediaSource(
            url=f"{base_url(config)}/api/v1/boards/{board_id}/picture.svg",
            params={"look": look, "width": int(width)},
            headers={"Authorization": f"Bearer {config.get('api_key') or ''}", "Accept": "image/svg+xml"},
            cache_seconds=0 if version == "live" else 3600,
            media_type="image/svg+xml",
            svg=True,
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = time.time()
        base = "http://nexcanvas.example.com"
        rows = [
            {"id": f"demo-board-{number}", "title": title, "space": space, "updated_by": ["sam", "alex", "robin"][number % 3],
             "updated_at": _iso(now - 1800 * number ** 2), "items": 12 * number, "url": f"{base}/b/demo-board-{number}",
             "picture": f"/api/v1/boards/demo-board-{number}/picture.svg"}
            for number, (title, space) in enumerate(DEMO_BOARDS, start=1)
        ]
        if widget_kind == "board":
            wanted = str(options.get("board") or rows[0]["id"])
            row = next((one for one in rows if one["id"] == wanted), rows[0])
            data = board_of(row, _look(options), _interval(options))
            for item in data.items:
                # A demo connection points nowhere, so there is no picture to fetch.
                item["art"] = ""
            return data
        data = boards_of({"spaces": 2, "boards": 14 + int(fake.walk("nexcanvas-boards", tick, 0, 3)), "changed_today": 3,
                          "changed_week": 6, "recent": rows[:5]}, _look(options))
        for item in data.items:
            item["art"] = ""
        return data


DEMO_BOARDS = (
    ("Garden shed plan", "Home"),
    ("Network map", "Homelab"),
    ("Holiday ideas", "Home"),
    ("Rack layout", "Homelab"),
    ("Birthday party", "Home"),
)


def _iso(moment: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(moment))


def _look(options: dict[str, Any]) -> str:
    return "light" if options.get("look") == "light" else "dark"


def _interval(options: dict[str, Any]) -> int:
    try:
        return max(5, int(options.get("interval") or 30))
    except (TypeError, ValueError):
        return 30


def _board_id(options: dict[str, Any]) -> str:
    """The card's board. Never a guess, and never a value that could leave the path it stands in."""
    board_id = str(options.get("board") or "").strip()
    if not board_id:
        raise AdapterError("Pick a board in the card's settings.", code="bad_param")
    if not BOARD_ID.match(board_id):
        raise AdapterError("That is not the id of a board.", code="bad_param", hint="Pick the board again in the card's settings.")
    return board_id


def _picture(board: dict[str, Any], look: str, width: int, version: str) -> str:
    board_id = str(board.get("id") or "")
    return f"proxy:/board/{board_id}/{look}/{width}/{version}" if BOARD_ID.match(board_id) else ""


def board_choices(rows: list[Any]) -> list[tuple[str, str]]:
    """Every board the token may read, by title, with its space to tell two of one name apart."""
    return [
        (str(row["id"]), " · ".join(part for part in (str(row.get("title") or "?"), str(row.get("space") or "")) if part))
        for row in rows if isinstance(row, dict) and BOARD_ID.match(str(row.get("id") or ""))
    ]


def board_of(board: dict[str, Any], look: str, interval: int) -> WidgetData:
    """One board large: its picture, its title and the space it lives in under it."""
    if not board:
        return WidgetData(status="unknown", meta={"empty": "No board"})
    return WidgetData(
        status="ok",
        items=[{
            "id": board.get("id"),
            "title": str(board.get("title") or "?"),
            "subtitle": str(board.get("space") or ""),
            "status": "ok",
            "art": _picture(board, look, LARGE, "live"),
        }],
        link=str(board.get("url") or "") or None,
        meta={"mode": "snapshot", "live": False, "interval": interval, "empty": "No board"},
    )


def boards_of(numbers: dict[str, Any], look: str) -> WidgetData:
    """The number of boards above the ones changed last, with the day's and the week's changes under them."""
    rows = [one for one in numbers.get("recent") or [] if isinstance(one, dict)]
    items = []
    for row in rows:
        changed = row.get("updated_at")
        version = int(epoch_of(changed) or 0)
        items.append({
            "id": row.get("id"),
            "title": str(row.get("title") or "?"),
            "subtitle": " · ".join(part for part in (str(row.get("space") or ""), str(row.get("updated_by") or "")) if part),
            "when": epoch_of(changed),
            "url": str(row.get("url") or ""),
            "art": _picture(row, look, THUMBNAIL, str(version)),
            "art_shape": "wide",
        })
    return WidgetData(
        status="ok",
        primary={"label": "Boards", "value": count_of(numbers.get("boards"))},
        secondary=[
            {"label": "Changed today", "value": count_of(numbers.get("changed_today"))},
            {"label": "This week", "value": count_of(numbers.get("changed_week"))},
            {"label": "Spaces", "value": count_of(numbers.get("spaces"))},
        ],
        items=items,
        meta={"headline": True, "empty": "No board yet."},
    )


ADAPTER = NexcanvasAdapter()
