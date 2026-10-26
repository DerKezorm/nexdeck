"""What a custom card may ask of a service, and how the answer is read.

One function, ``fetch_source``, stands between a card and the connection it reads through, and every guard rail of
KARTEN-2 lives in it: the path is relative to the address of the connection, the method is GET, a redirect is not
followed, the answer is at most 2 MB, JSON counts as JSON whatever the service calls it, and a short plain text is one
value. A card can come from the shop, so none of this is left to the author.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..adapters.base import Adapter, AdapterError, AuthFailed, Context, path_segment
from .schema import Request, every_seconds, stays_underneath

#: The most a card reads from one answer (KARTEN-2 AC-8).
MAX_ANSWER_BYTES = 2 * 1024 * 1024
#: The longest plain text that is one value (KARTEN-2 EC-4): a version number, a state word.
MAX_TEXT_BYTES = 2048
#: Cards that sit on the same connection share an answer for this long, and so does one card with itself.
SHARED_SECONDS = 5.0
#: A request that says "every 5m" is not asked for again before then.
MOST_SECONDS = 3600.0

_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]{0,29})\}")


def fill_path(path: str, values: dict[str, Any] | None = None) -> str:
    """The path with its ``{name}`` places filled from the data of a row (KARTEN-2 EC-1).

    ⚠️ A value that is not one plain name is refused, not cleaned: ``../admin`` or ``7?x=1`` would otherwise ask a
    different address than the author wrote, with the connection's credentials.
    """
    def one(found: re.Match[str]) -> str:
        name = found.group(1)
        if values is None or name not in values:
            raise AdapterError(f"The request needs {name}, which is not there.", code="bad_param")
        return path_segment(values[name], name)

    return _PLACEHOLDER.sub(one, path)


def read_answer(response: Any) -> Any:
    """JSON whatever the content type says (KARTEN-2 EC-7), else a short plain text as one value (EC-4), else an error."""
    content: bytes = response.content
    if len(content) > MAX_ANSWER_BYTES:
        raise AdapterError(
            "Answer too large. The service answered with more than a custom card reads.",
            code="answer_too_large",
            hint="A card reads at most 2 MB of one answer. Ask for less, or use a different path of the service.",
        )
    try:
        return json.loads(content)
    except RecursionError as failure:
        # ⚠️ 2 MB of opening brackets nest deeper than the interpreter reads; it was a 500 (found in the review, 25.10.2026).
        raise AdapterError(
            "The answer is nested too deeply. The service answered with JSON that a custom card cannot read.",
            code="not_json",
            hint="The path probably points at something other than the data the card needs.",
        ) from failure
    except ValueError:
        pass
    if 0 < len(content) <= MAX_TEXT_BYTES:
        try:
            text = content.decode("utf-8").strip()
        except UnicodeDecodeError:
            text = ""
        # A page of markup is a login page or a proxy, not a value.
        if text and not text.startswith("<") and all(char.isprintable() or char in "\n\r\t" for char in text):
            return text
    raise AdapterError(
        "The service did not answer with JSON or a short text.",
        code="not_json",
        hint="The path probably points at a login page or a reverse proxy.",
    )


def cache_for(request: Request) -> float:
    """How long the answer to a request is kept: the time it names, else the shared five seconds."""
    named = every_seconds(request.every)
    return SHARED_SECONDS if named is None else min(MOST_SECONDS, max(SHARED_SECONDS, float(named)))


async def fetch_source(
    adapter: Adapter,
    config: dict[str, Any],
    ctx: Context,
    request: Request,
    *,
    values: dict[str, Any] | None = None,
    method: str = "GET",
) -> Any:
    """Ask the connection one request of a card and return the answer, parsed.

    Raises ``AdapterError`` the way the built-in cards of this connection do: ``AuthFailed`` for 401 and 403,
    ``Unreachable`` for a service that does not answer in time, and the codes ``no_raw_access``, ``redirected``,
    ``answer_too_large``, ``not_json`` and ``http_error`` for what a custom card adds.
    """
    # ⚠️ GET and nothing else (KARTEN-2 AC-5). The parameter exists so that a test can show the refusal; no card can set it.
    if method.upper() != "GET":
        raise AdapterError("A custom card only reads.", code="read_only", hint="Reading is a GET request.")
    path = fill_path(request.path, values)
    if not stays_underneath(path):
        raise AdapterError("The path of a card stays underneath the connection's address.", code="bad_path")
    response = await adapter.raw_request("GET", path, config, ctx, cache_seconds=cache_for(request))
    for _hop in range(MAX_HOPS):
        if not 300 <= response.status_code < 400:
            break
        moved = same_place_move(adapter, config, path, response)
        if moved is None:
            break
        config, path = moved
        response = await adapter.raw_request("GET", path, config, ctx, cache_seconds=cache_for(request))
    if 300 <= response.status_code < 400:
        raise AdapterError(
            "Redirected, not followed. The service answered with a redirect to another place, which a custom card does not follow.",
            code="redirected",
            hint="Use the address the redirect leads to as the connection's address.",
        )
    if response.status_code in (401, 403):
        raise AuthFailed()
    if response.status_code >= 400:
        raise AdapterError(
            f"The service answered with HTTP {response.status_code}.",
            code="http_error",
            hint="Check the path of the request; the service may not have it.",
        )
    return read_answer(response)


#: How many redirects to the same place a card follows, as http to https and on to a login-free path.
MAX_HOPS = 3


def same_place_move(adapter: Adapter, config: dict[str, Any], path: str, response: Any) -> tuple[dict[str, Any], str] | None:
    """The connection's address and the path a redirect leads to, when it stays where the credentials may follow it.

    ⚠️ The rule of every outbound client (``same_place``): the same host, and http raised to https or the same scheme
    and port. A connection typed as http that its service raises to https (UniFi, 26.10.2026) reads like the built-in
    cards; a redirect to another host, port or a path above the connection's own is still refused. The card goes on
    with the same credentials under the new address, so only an address the kind builds from ``url`` can move.
    """
    import httpx

    from ..adapters.base import same_place
    from ..adapters.jsonapi import join_path

    location = response.headers.get("location")
    if not location:
        return None
    base = adapter.raw_base(config)
    start = httpx.URL(join_path(base, path))
    target = start.join(location)
    if not same_place(start, target):
        return None
    prefix = httpx.URL(base).path.rstrip("/")
    if not target.path.startswith(prefix + "/") and target.path != prefix:
        return None
    rest = target.raw_path.decode("ascii")[len(prefix):] or "/"
    if not stays_underneath(rest):
        return None
    moved = {**config, "url": str(target.copy_with(path=prefix or "/", query=None, fragment=None)).rstrip("/")}
    if adapter.raw_base(moved).rstrip("/") != moved["url"]:
        return None
    return moved, rest


def sources() -> list[dict[str, Any]]:
    """The kinds of connection a custom card can read through, for the editor and the shop (KARTEN-2 AC-12)."""
    from ..adapters import all_adapters

    return [
        {"kind": one.kind, "label": one.label, "icon": one.icon, "category": one.category}
        for one in all_adapters()
        if one.raw_access
    ]
