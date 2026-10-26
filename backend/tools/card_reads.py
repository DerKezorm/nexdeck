"""Writes ``app/cards/card_reads.json``: what the built-in cards of each kind of service ask of it, found in the code.

    python tools/card_reads.py          # from backend/, rewrites the file
    python tools/card_reads.py --check  # exits 1 when the file is not what the code gives

Every built-in card of every kind is fetched once against a stubbed service that answers ``{}``, with an invented
connection (only example.com and marker values). The GET requests it makes are written down as they reach the stub, whatever
client sent them (the shared one, or a kind's own such as qBittorrent's or UniFi's), so what counts is what the code really asks, helpers and all. A card that fails on the
empty answer still counts for what it asked before.

⚠️ Nothing that proves who asks is kept: a parameter with the name of a credential is dropped, and a request with the
value of a secret of the connection anywhere in its path is left out. The value of a field of the connection that is
not a secret (a site, an entity) is written as ``{field}``.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlsplit

import httpx
import respx

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.adapters import all_adapters, get_adapter  # noqa: E402
from app.adapters.base import NOT_READ_BY_CARDS, Context  # noqa: E402
from app.cards.card_reads import TARGET, what_proves_who_asks  # noqa: E402
from app.adapters.rawread import _asks_to_sign_in  # noqa: E402
from app.credential_names import is_credential_name  # noqa: E402

BASE = "https://svc.example.com"
#: The most a card of one kind may add: a page of paths, not a copy of the API.
LONGEST = 300

#: A value that says when it was written (a day, a moment, seconds since 1970): it changes with every run, and what it
#: bounds is the card's window of time, not part of where the data lives. The request without it is still one to offer.
WHEN = re.compile(r"^(\d{4}-\d{2}-\d{2}([T ][\d:.]+(Z|[+-]\d{2}:?\d{2})?)?|\d{10}(\d{3})?)$")
#: Options a card needs before it asks anything, for the kinds whose cards stop at "nothing is set" or "not owner/name";
#: the marker is written as the place given in :data:`PLACES`.
OPTIONS: dict[str, dict[str, Any]] = {"github": {"repos": "Zkowner/Zkrepo"}}
PLACES: dict[str, str] = {"Zkowner/Zkrepo": "{owner}/{repo}", "Zkentityids": "{entity_id}"}
#: What a kind offers that no card of it asks, from its documentation. Home Assistant's cards of its own speak WebSocket;
#: the same data is on its REST API, which a custom card can read. ``widgets`` empty: no card behind it.
EXTRA: dict[str, list[dict[str, Any]]] = {
    "homeassistant": [
        {"path": "/api/states", "widgets": ["entities"]},
        {"path": "/api/config", "widgets": []},
    ],
}
NO_VALUE = ("integrations", "items", "choices", "board", "pictures", "cards", "date", "time", "timezone", "colour", "textarea")
FIXES: dict[str, dict[str, Any]] = {"elasticsearch": {"username": ""}}


def invented(kind: str) -> dict[str, Any]:
    """A connection of this kind with every text field filled with a marker, so that it can be found again."""
    config: dict[str, Any] = {}
    for one in get_adapter(kind).fields:
        if one.type in NO_VALUE:
            if one.default is not None:
                config[one.name] = one.default
        elif one.name == "url" or one.type == "url":
            config[one.name] = BASE
        elif one.type == "bool":
            config[one.name] = bool(one.default)
        elif one.type == "select":
            config[one.name] = one.default if one.default is not None else (one.options[0][0] if one.options else "")
        elif one.type == "number":
            config[one.name] = one.default if one.default is not None else 8080
        else:
            config[one.name] = "Zk" + one.name.replace("_", "")
    return {**config, **FIXES.get(kind, {})}


def _options(widget: Any) -> dict[str, Any]:
    """The options of a card as they start, and a marker in the text ones that have no start (an entity, a project)."""
    out: dict[str, Any] = {}
    for one in widget.options:
        if one.default is not None:
            out[one.name] = one.default
        elif one.type in ("text", "textarea"):
            out[one.name] = "Zk" + one.name.replace("_", "")
    return out


POST = "asks with POST only (JSON-RPC, XML-RPC, SOAP, GraphQL or a form), and a custom card reads with GET"
SIGN_IN = "opens a session first in a way the stand-in cannot answer, so no card gets as far as asking"
#: Readable kinds for which the code gives no GET to offer, each with the reason. ``tests/test_cards_card_reads.py`` holds this
#: list against the result: a kind that gains reads, or one that is new and has none, turns the test red until it is put right.
GAPS: dict[str, str] = {
    "backrest": POST + " (gRPC-web)",
    "bookorbit": SIGN_IN,
    "calibreweb": SIGN_IN,
    "deluge": POST + " (JSON-RPC)",
    "duplicati": SIGN_IN,
    "freshrss": SIGN_IN,
    "frigate": SIGN_IN,
    "fritzbox": POST + " (SOAP)",
    "ghostfolio": SIGN_IN,
    "ical": "the address of the connection is the calendar file itself, there is nothing under it to ask",
    "komodo": POST,
    "nzbget": POST + " (JSON-RPC)",
    "openmediavault": POST + " (JSON-RPC)",
    "openwrt": POST + " (ubus)",
    "reolink": SIGN_IN,
    "rtorrent": POST + " (XML-RPC)",
    "synology": SIGN_IN + " (the session id travels in every address)",
    "transmission": POST + " (JSON-RPC)",
    "truenas": "speaks WebSocket, which the stand-in does not answer",
    "twitch": "gets its token from another address (id.twitch.tv) than the connection's",
    "unraid": POST + " (GraphQL)",
    "urbackup": POST,
    "wallos": POST,
    "youtube": "reads public pages of youtube.com, not an address of the connection",
    "zabbix": POST + " (JSON-RPC)",
}

#: What a sign-in of any kind may answer with, so that a kind that opens a session first gets as far as asking.
SIGNED_IN = {
    "token": "Zk-token", "access_token": "Zk-token", "jwt": "Zk-token", "sid": "Zk-sid", "session_id": "Zk-sid", "ok": True,
    "data": {"sid": "Zk-sid", "token": "Zk-token"}, "result": {"token": "Zk-token", "sessionid": "Zk-sid"},
    "session": {"sid": "Zk-sid", "valid": True}, "value": {"Token": "Zk-token", "leaseTime": 60},
}


def _answer(request: httpx.Request) -> httpx.Response:
    """``{}`` for a question, and a session for what looks like a sign-in (a POST to a path of that kind)."""
    if request.method == "POST":
        return httpx.Response(200, json=SIGNED_IN, headers={"set-cookie": "SID=Zk-sid; Path=/"})
    return httpx.Response(200, json={})


def _query(pairs: list[tuple[str, str]]) -> str:
    return "&".join(f"{quote(name, safe='{}')}={quote(value, safe='{}')}" for name, value in pairs)


def _entry(url: str, base: str, secrets: list[str], places: dict[str, str], names: frozenset[str]) -> str | None:
    """The path of one request under the address of the connection, or ``None`` when it is not one to offer."""
    if _asks_to_sign_in(url, None, None):
        return None
    parts = urlsplit(url)
    prefix = urlsplit(base).path.rstrip("/")
    origin = urlsplit(base)
    if f"{parts.scheme}://{parts.netloc}".lower() != f"{origin.scheme}://{origin.netloc}".lower() or not parts.path.startswith(prefix):
        return None
    lowered = {name.lower() for name in names}
    pairs = [(name, value) for name, value in parse_qsl(parts.query, keep_blank_values=True)
             if not is_credential_name(name) and name.lower() not in lowered and not WHEN.match(value)]
    path = parts.path[len(prefix):] or "/"
    if not path.startswith("/") or path == "/":
        return None
    pairs = [(name, value) for name, value in pairs if value not in secrets]
    if any(secret in path for secret in secrets):
        return None
    for marker, field in places.items():
        place = PLACES.get(marker, "{" + field + "}")
        # ⚠️ Some services write what they were given in lower case; the marker is found all the same.
        found = re.compile(re.escape(marker), re.I)
        path = found.sub(lambda _: place, path)
        pairs = [(name, found.sub(lambda _: place, value)) for name, value in pairs]
    shown = path + ("?" + _query(pairs) if pairs else "")
    if len(shown) > LONGEST or any(secret in shown for secret in secrets):
        return None
    return shown


async def _reads_of(kind: str, client: httpx.AsyncClient, why: dict[str, str] | None = None) -> list[dict[str, Any]]:
    adapter = get_adapter(kind)
    config = invented(kind)
    base = adapter.raw_base(config)
    names, proof = what_proves_who_asks(adapter, config)
    secrets = [value for value in proof if value] + ["Zk-token", "Zk-sid"]
    places = {str(v): n for n, v in config.items() if isinstance(v, str) and v.startswith("Zk") and str(v) not in secrets}
    out: list[dict[str, Any]] = []
    by_path: dict[str, dict[str, Any]] = {}
    for widget in adapter.widgets:
        if widget.client_only:
            continue
        noted: list[str] = []
        ctx = Context(client, integration_id=1, widget_id=1, cache={})
        with respx.mock(assert_all_called=False) as router:
            router.route().mock(side_effect=_answer)
            options = {**_options(widget), **OPTIONS.get(kind, {})}
            try:
                await asyncio.wait_for(adapter.fetch(widget.kind, config, options, ctx), 20)
            except Exception as failure:  # noqa: BLE001 - the empty answer may fail a card; what it asked before counts
                if why is not None:
                    why.setdefault(kind, f"{widget.kind}: {type(failure).__name__}: {str(failure)[:100]}")
            noted = [str(call.request.url) for call in router.calls if call.request.method == "GET"]
        for url in noted:
            path = _entry(url, base, secrets, {**places, **{str(v): n for n, v in options.items() if isinstance(v, str) and v.startswith("Zk")}}, names)
            if path is None:
                continue
            if path not in by_path:
                by_path[path] = {"path": path, "widgets": []}
                out.append(by_path[path])
            if widget.kind not in by_path[path]["widgets"]:
                by_path[path]["widgets"].append(widget.kind)
    for one in EXTRA.get(kind, []):
        if one["path"] in by_path:
            by_path[one["path"]]["widgets"] += [w for w in one["widgets"] if w not in by_path[one["path"]]["widgets"]]
        else:
            out.append({"path": one["path"], "widgets": list(one["widgets"])})
    return out


async def _all(why: dict[str, str] | None) -> dict[str, list[dict[str, Any]]]:
    kinds = sorted(one.kind for one in all_adapters() if one.kind not in NOT_READ_BY_CARDS)
    found: dict[str, list[dict[str, Any]]] = {}
    # One client for all: making one costs more than the stubbed request does.
    async with httpx.AsyncClient() as client:
        for kind in kinds:
            reads = await _reads_of(kind, client, why)
            if reads:
                found[kind] = reads
    return found


def build(why: dict[str, str] | None = None) -> dict[str, list[dict[str, Any]]]:
    return asyncio.run(_all(why))


def render(found: dict[str, list[dict[str, Any]]]) -> str:
    return json.dumps(found, indent=1, ensure_ascii=False, sort_keys=True) + "\n"


def main(argv: list[str]) -> int:
    text = render(build())
    if "--check" in argv:
        return 0 if TARGET.exists() and TARGET.read_text(encoding="utf-8") == text else 1
    TARGET.write_text(text, encoding="utf-8")
    print(f"{len(json.loads(text))} kinds, {sum(len(v) for v in json.loads(text).values())} reads -> {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
