"""How a custom card signs in to a connection: the way the built-in cards of that connection do.

A custom card asks one path of a service. Every kind of connection has its own way to prove who is asking: a header,
a login name and password, a key in the address, a session that is opened first and renewed when it runs out. Nobody
writes that down a second time for the cards. Where a kind has the small helpers for headers and login
(``_headers``, ``_auth``) they are used as they are; everything else is **watched**: the kind's own connection test is
run once with a watcher on its requests, and what its first signed GET carried (headers, login, the parameters that
carry a key or a session) is what the card sends too. A kind that opens a session does so by its own sign-in, with its
own memory, and the card renews it the way the kind does: it forgets the session and signs in again.

⚠️ What is copied from the watched request is only what proves who asks. The parameters that merely ask (``cmd=``,
``limit=``) belong to the kind's own question and stay behind. The credentials are used for the address of the
connection and no other: the request goes through the same ``Context.request`` as every built-in card, which refuses a
redirect to another place when a card asks, and a card cannot set a header itself.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .base import (
    CACHE_PREFIX,
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Unreachable,
    _refuse_a_giant_answer,
    guard_outbound,
)

#: How long what was watched is used before the kind is asked again. Cheap for a key (nothing leaves the server) and for
#: a session the kind keeps (its own memory answers), and it keeps a session id that ran out from living for ever.
SIGNED_FOR = 300.0
#: The memory key, in the connection's own memory.
MEMORY = "card:signed"
#: Parameters that prove who asks. Matched on the name; a kind with a name that does not look like one lists it itself
#: in ``raw_param_names``.
CREDENTIAL_PARAM = re.compile(r"key|token|secret|pass|pwd|sid|session|auth|ticket|signature|credential|user|login", re.I)
#: Headers every client sets, or that belong to a request body: not a proof of anything, and not copied.
NOT_COPIED = {"content-type", "content-length", "host", "connection", "accept-encoding", "transfer-encoding"}
#: Headers that prove nothing when they are the only ones there.
PLAIN = {"accept", "accept-language", "user-agent", "referer", "origin", "x-requested-with"}


@dataclass
class Sent:
    """What proves who asks, taken from a request of the kind itself."""

    headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    auth: tuple[str, str] | None = None

    def signed(self) -> bool:
        return bool(self.auth or self.params or any(name.lower() not in PLAIN for name in self.headers))


class _Seen(BaseException):
    """Ends the connection test the moment its first signed request is known.

    ⚠️ Not an ``Exception``: a test that wraps whatever goes wrong into "could not be reached" must not swallow it.
    """

    def __init__(self, sent: Sent) -> None:
        super().__init__("signed request seen")
        self.sent = sent


def _origin(url: str) -> tuple[str, str, int]:
    parts = httpx.URL(url)
    return parts.scheme, (parts.host or "").lower(), parts.port or (443 if parts.scheme == "https" else 80)


def _takes_the_parameter(adapter: Adapter, name: str) -> bool:
    return bool(CREDENTIAL_PARAM.search(name)) or name in adapter.raw_param_names


def _is_static(adapter: Adapter) -> bool:
    """The kind has helpers that build its credentials from the connection alone."""
    cls = type(adapter)
    return callable(getattr(adapter, "_headers", None)) or callable(getattr(adapter, "_auth", None)) \
        or cls.raw_params is not Adapter.raw_params


#: A request that signs in, not one that asks: its credentials are the means to a session, never the template.
SIGN_IN_PATH = re.compile(r".*(log-?in|log-?on|sign-?in|authenticate|oauth2?|tokens?|sessions?|auth|anonymous)(\.php|\.cgi)?", re.I)
SIGN_IN_PARAM = re.compile(r"pass|pwd|login|account|^user", re.I)


def _asks_to_sign_in(url: str, params: dict[str, Any] | None, data: Any) -> bool:
    parts = httpx.URL(url)
    names = [*(params or {}), *(dict(data) if isinstance(data, dict) else {}), *parts.params.keys()]
    return bool(SIGN_IN_PATH.fullmatch(parts.path.rstrip('/').rsplit('/', 1)[-1])) or any(SIGN_IN_PARAM.search(str(name)) for name in names)


async def watch(adapter: Adapter, config: dict[str, Any], ctx: Context) -> Sent:
    """Run the kind's own connection test and keep what its first signed request to the connection's address carried.

    A GET is the best template. A kind that only speaks POST (a JSON-RPC, a GraphQL) is taken from its first signed POST
    when the test sees no signed GET: the headers and the login, never the body. A request that signs in (by its address
    or by a password in it) is passed over: what it carries is the way to a session, and the session is what the next
    request carries.
    """
    origin = _origin(adapter.raw_base(config))
    fallback: list[Sent] = []

    def tap(method: str, url: str, headers: dict[str, str] | None, params: dict[str, Any] | None, auth: Any, data: Any) -> None:
        if _origin(url) != origin or _asks_to_sign_in(url, params, data):
            return
        kept = {name: value for name, value in (headers or {}).items() if name.lower() not in NOT_COPIED}
        found = {**dict(httpx.URL(url).params), **(params or {}), **(dict(data) if isinstance(data, dict) else {})}
        carried = {name: value for name, value in found.items() if _takes_the_parameter(adapter, str(name))}
        sent = Sent(kept, carried, tuple(auth) if auth else None)  # type: ignore[arg-type]
        if not sent.signed():
            return
        if method.upper() == "GET":
            raise _Seen(sent)
        if not fallback:
            fallback.append(sent)

    try:
        await adapter.test(config, ctx.tapped(tap))
    except _Seen as seen:
        return seen.sent
    except (AuthFailed, Unreachable):
        # The service refuses the sign-in or does not answer: the card is told what the Test button would tell.
        raise
    except Exception:  # noqa: BLE001 - the test may fail for a reason of its own (an empty rule list); the card asks anyway
        pass
    # No signed GET was seen: take a signed POST, or none for a service that needs no sign-in.
    return fallback[0] if fallback else Sent()


def forget_session(ctx: Context) -> bool:
    """Drop what a kind remembers of a sign-in, so that its next request signs in again. ``True`` if there was any."""
    gone = [name for name in ctx.cache if not name.startswith(CACHE_PREFIX) and name != MEMORY]
    for name in gone:
        ctx.cache.pop(name, None)
    ctx.cache.pop(MEMORY, None)
    return bool(gone)


async def signed(adapter: Adapter, config: dict[str, Any], ctx: Context, *, again: bool = False) -> Sent:
    fetched = await adapter.raw_signed_headers(config, ctx)
    if fetched is not None:
        return Sent(dict(fetched))
    if _is_static(adapter):
        return Sent(adapter.raw_headers(config), dict(adapter.raw_params(config)), adapter.raw_auth(config))
    fingerprint = json.dumps(config, sort_keys=True, default=str)
    held = ctx.cache.get(MEMORY)
    if held and not again and held[0] == fingerprint and held[1] > time.monotonic():
        return held[2]
    sent = await watch(adapter, config, ctx)
    ctx.cache[MEMORY] = (fingerprint, time.monotonic() + SIGNED_FOR, sent)
    return sent


async def for_a_picture(adapter: Adapter, config: dict[str, Any], ctx: Context) -> tuple[dict[str, str], dict[str, Any]]:
    """Headers and parameters that sign a picture the server fetches on a card's behalf, the way the card's requests are."""
    import base64

    sent = await signed(adapter, config, ctx)
    headers = dict(sent.headers)
    if sent.auth is not None and not any(name.lower() == "authorization" for name in headers):
        headers["Authorization"] = "Basic " + base64.b64encode(f"{sent.auth[0]}:{sent.auth[1]}".encode()).decode()
    return headers, dict(sent.params)


async def ask(
    adapter: Adapter,
    method: str,
    path: str,
    config: dict[str, Any],
    ctx: Context,
    *,
    params: dict[str, Any] | None = None,
    json_body: Any = None,
    cache_seconds: float = 0,
) -> httpx.Response:
    """One request of a card, signed the way the kind signs its own."""
    from .jsonapi import join_path

    url = join_path(adapter.raw_base(config), path)
    held = adapter.raw_client(config, ctx)
    if held is not None:
        return await _through_the_clients_own_cookies(adapter, held, url, config, ctx, params)
    for attempt in (0, 1):
        sent = await signed(adapter, config, ctx, again=attempt == 1)
        try:
            # ⚠️ Merged into the address here: httpx replaces the query of an address when ``params`` is given, and the
            # card's own question (``?api=...&method=...``) is the point of the request.
            more = {**sent.params, **(params or {})}
            response = await ctx.request(
                method.upper(),
                str(httpx.URL(url).copy_merge_params(more)) if more else url,
                headers=dict(sent.headers) or None,
                json_body=json_body,
                verify=adapter.raw_verify(config),
                auth=sent.auth,
                cache_seconds=cache_seconds,
                follow_redirects=False,
                note=False,
            )
            if adapter.raw_expired(response):
                raise AuthFailed()
            return response
        except AuthFailed:
            # A session runs out. The kind signs in again by itself when its memory is gone, as it does for its own cards.
            if attempt == 1 or _is_static(adapter) or not forget_session(ctx):
                raise
    raise AdapterError("The service did not accept the sign-in.", code="auth_failed")  # pragma: no cover


async def _through_the_clients_own_cookies(
    adapter: Adapter, client: httpx.AsyncClient, url: str, config: dict[str, Any], ctx: Context, params: dict[str, Any] | None
) -> httpx.Response:
    """A kind that keeps the cookie of its sign-in in a client of its own (qBittorrent, UniFi): the card uses that client.

    ⚠️ The same client the kind's cards use, so the session is theirs and the card signs in again, with the kind's own
    sign-in, when the service says 401 or 403.
    """
    guard_outbound(url)
    for attempt in (0, 1):
        try:
            response = await client.request(
                "GET", url, headers=adapter.raw_headers(config) or None, params=params, follow_redirects=False,
            )
        except httpx.TimeoutException as error:
            raise Unreachable("The service did not answer in time.") from error
        except httpx.HTTPError as error:
            raise Unreachable(f"The service could not be reached: {error.__class__.__name__}.") from error
        if response.status_code in (401, 403) and attempt == 0:
            await adapter.raw_sign_in(config, ctx)
            continue
        _refuse_a_giant_answer(url, response)
        return response
    raise AdapterError("The service did not accept the sign-in.", code="auth_failed")  # pragma: no cover
